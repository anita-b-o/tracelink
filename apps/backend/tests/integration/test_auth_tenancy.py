import asyncio
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select

from tests.integration.test_relationship_extraction_evidence import (
    add_document,
    add_resolved_mention,
)
from tracelink.core.config import get_settings
from tracelink.domain.enums import (
    AssertionStatus,
    EntityResolutionCandidateStatus,
    EntityType,
    EvidenceType,
    InvestigationReportType,
    RelationshipCandidateStatus,
    RelationshipClaimKind,
    RelationshipType,
)
from tracelink.domain.models import (
    AuthSession,
    Document,
    EntityResolutionCandidate,
    Investigation,
    User,
)
from tracelink.infrastructure.redis import clear_redis_clients
from tracelink.main import app
from tracelink.repositories.entities import EntityRepository
from tracelink.repositories.entity_mentions import EntityResolutionCandidateRepository
from tracelink.repositories.evidence import EvidenceRepository
from tracelink.repositories.relationship_candidates import RelationshipCandidateRepository
from tracelink.repositories.relationships import RelationshipRepository
from tracelink.repositories.reports import InvestigationReportRepository
from tracelink.services.entities import EntityService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _clear_rate_limits() -> None:
    clear_redis_clients()
    client = Redis.from_url(get_settings().redis_url)
    try:
        await client.flushdb()
    finally:
        await client.aclose()


async def _register(client: AsyncClient, email: str) -> dict[str, object]:
    response = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correct-horse-battery", "display_name": email[:1]},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_register_duplicate_login_refresh_rotation_and_logout(db_session) -> None:
    await _clear_rate_limits()
    async with await _client() as client:
        user = await _register(client, "auth-a@example.com")
        assert user["email"] == "auth-a@example.com"
        duplicate = await client.post(
            "/api/auth/register",
            json={"email": " AUTH-A@example.com ", "password": "correct-horse-battery"},
        )
        assert duplicate.status_code == 409
        failed = await client.post(
            "/api/auth/login",
            json={"email": "auth-a@example.com", "password": "incorrect-password"},
        )
        assert failed.status_code == 401
        logged_in = await client.post(
            "/api/auth/login",
            json={"email": "AUTH-A@example.com", "password": "correct-horse-battery"},
        )
        assert logged_in.status_code == 200
        first_refresh = client.cookies.get("tracelink_refresh")
        refreshed = await client.post("/api/auth/refresh")
        assert refreshed.status_code == 200
        second_refresh = client.cookies.get("tracelink_refresh")
        assert first_refresh and second_refresh and first_refresh != second_refresh
        replay = await client.post(
            "/api/auth/refresh", cookies={"tracelink_refresh": first_refresh}
        )
        assert replay.status_code == 401
        invalidated = await client.post(
            "/api/auth/refresh", cookies={"tracelink_refresh": second_refresh}
        )
        assert invalidated.status_code == 401
        logout = await client.post("/api/auth/logout")
        assert logout.status_code == 204


async def test_disabled_user_is_rejected(db_session) -> None:
    await _clear_rate_limits()
    async with await _client() as client:
        data = await _register(client, "disabled@example.com")
        user = await db_session.get(User, data["id"])
        assert user is not None
        user.is_active = False
        await db_session.commit()
        response = await client.post(
            "/api/auth/login",
            json={"email": "disabled@example.com", "password": "correct-horse-battery"},
        )
        assert response.status_code == 401


async def test_cross_user_investigation_is_hidden(db_session) -> None:
    await _clear_rate_limits()
    async with await _client() as owner, await _client() as other:
        await _register(owner, "owner@example.com")
        created = await owner.post(
            "/api/investigations", json={"title": "Private", "original_query": "private query"}
        )
        assert created.status_code == 201, created.text
        investigation_id = UUID(created.json()["id"])
        await _register(other, "other@example.com")
        hidden = await other.get(f"/api/investigations/{investigation_id}")
        assert hidden.status_code == 404
        listing = await other.get("/api/investigations")
        assert listing.status_code == 200
        assert listing.json() == []
        owner_id = await db_session.scalar(
            select(Investigation.user_id).where(Investigation.id == investigation_id)
        )
        assert owner_id is not None


async def test_refresh_token_is_stored_only_as_hash(db_session) -> None:
    await _clear_rate_limits()
    async with await _client() as client:
        await _register(client, "hash@example.com")
        raw = client.cookies.get("tracelink_refresh")
        stored = await db_session.scalar(select(AuthSession.token_hash))
        assert raw is not None and stored is not None
        assert raw != stored
        assert len(stored) == 64


async def test_concurrent_refresh_never_leaves_two_valid_tokens(db_session) -> None:
    await _clear_rate_limits()
    async with await _client() as client:
        await _register(client, "concurrent@example.com")
        original = client.cookies.get("tracelink_refresh")
        assert original is not None

    async with await _client() as first, await _client() as second:
        responses = await asyncio.gather(
            first.post("/api/auth/refresh", cookies={"tracelink_refresh": original}),
            second.post("/api/auth/refresh", cookies={"tracelink_refresh": original}),
        )
        assert sorted(response.status_code for response in responses) == [200, 401]
        winner = next(response for response in responses if response.status_code == 200)
        rotated = winner.cookies.get("tracelink_refresh")
        assert rotated is not None
        rejected = await first.post("/api/auth/refresh", cookies={"tracelink_refresh": rotated})
        assert rejected.status_code == 401


async def test_login_rate_limit_returns_retry_after(db_session) -> None:
    await _clear_rate_limits()
    async with await _client() as client:
        responses = [
            await client.post(
                "/api/auth/login",
                json={"email": "missing@example.com", "password": "incorrect-password"},
            )
            for _ in range(6)
        ]
    assert [response.status_code for response in responses[:5]] == [401] * 5
    assert responses[5].status_code == 429
    assert int(responses[5].headers["retry-after"]) >= 1


async def test_logout_revokes_an_active_session(db_session) -> None:
    await _clear_rate_limits()
    async with await _client() as client:
        await _register(client, "logout@example.com")
        access = client.cookies.get("tracelink_access")
        assert access is not None
        assert (await client.get("/api/auth/me")).status_code == 200
        assert (await client.post("/api/auth/logout")).status_code == 204
        revoked = await client.get("/api/auth/me", headers={"Cookie": f"tracelink_access={access}"})
        assert revoked.status_code == 401


async def test_cors_allows_only_configured_exact_origin(db_session) -> None:
    async with await _client() as client:
        allowed_origin = get_settings().cors_origin_list[0]
        allowed = await client.options(
            "/api/auth/login",
            headers={"Origin": allowed_origin, "Access-Control-Request-Method": "POST"},
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == allowed_origin
        rejected = await client.options(
            "/api/auth/login",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in rejected.headers


async def test_cross_user_matrix_hides_all_investigation_resources(db_session) -> None:
    await _clear_rate_limits()
    async with await _client() as owner, await _client() as other:
        await _register(owner, "matrix-owner@example.com")
        created = await owner.post(
            "/api/investigations",
            json={"title": "Tenant matrix", "original_query": "private matrix subject"},
        )
        investigation_id = UUID(created.json()["id"])
        assert (
            await owner.post(f"/api/investigations/{investigation_id}/start")
        ).status_code == 202
        tasks = (await owner.get(f"/api/investigations/{investigation_id}/tasks")).json()
        task_id = tasks[0]["id"]

        text = "Private Person directs Private Company."
        _, document_id = await add_document(
            db_session, text, investigation_id=investigation_id, suffix="tenant-matrix"
        )
        document = await db_session.get(Document, document_id)
        assert document is not None
        entities = EntityService(EntityRepository(db_session))
        person = await entities.create(
            entity_type=EntityType.PERSON, canonical_name="Private Person"
        )
        company = await entities.create(
            entity_type=EntityType.COMPANY, canonical_name="Private Company"
        )
        mention_id, _ = await add_resolved_mention(
            db_session,
            investigation_id,
            document_id,
            EntityType.PERSON,
            "Private Person",
            0,
            entity_id=person.id,
        )
        await EntityResolutionCandidateRepository(db_session).upsert(
            investigation_id=investigation_id,
            mention_id=mention_id,
            candidate_entity_id=company.id,
            score=0.7,
            status=EntityResolutionCandidateStatus.PENDING,
            signals={},
        )
        await db_session.flush()
        entity_candidate = await db_session.scalar(
            select(EntityResolutionCandidate).where(
                EntityResolutionCandidate.mention_id == mention_id,
                EntityResolutionCandidate.candidate_entity_id == company.id,
            )
        )
        assert entity_candidate is not None
        relationship = await RelationshipRepository(db_session).create(
            source_entity_id=person.id,
            target_entity_id=company.id,
            relationship_type=RelationshipType.DIRECTOR_OF,
            confidence=0.8,
            status=AssertionStatus.CONFIRMED,
            metadata={},
        )
        evidence = await EvidenceRepository(db_session).create(
            investigation_id=investigation_id,
            source_id=document.source_id,
            document_id=document_id,
            relationship_id=relationship.id,
            excerpt=text,
            start_offset=0,
            end_offset=len(text),
            evidence_type=EvidenceType.SUPPORTING,
            confidence=0.8,
            metadata={},
        )
        relationship_candidate = await RelationshipCandidateRepository(db_session).upsert(
            investigation_id=investigation_id,
            document_id=document_id,
            source_entity_id=person.id,
            target_entity_id=company.id,
            relationship_type=RelationshipType.DIRECTOR_OF,
            claim_kind=RelationshipClaimKind.AFFIRMS,
            confidence=0.7,
            score=0.7,
            extraction_method="fixture",
            supporting_text=text,
            start_offset=0,
            end_offset=len(text),
            temporal_start=None,
            temporal_end=None,
            metadata={},
            signals={},
            status=RelationshipCandidateStatus.PENDING,
            fingerprint="c" * 64,
        )
        report = await InvestigationReportRepository(db_session).get_or_create(
            investigation_id=investigation_id,
            report_type=InvestigationReportType.EXECUTIVE_SUMMARY,
            subject_entity_id=None,
            fingerprint="d" * 64,
            provider="fake",
            model="fixture",
            prompt_version="fixture",
            parameters={},
        )
        await db_session.commit()

        await _register(other, "matrix-other@example.com")
        direct_paths = [
            f"/api/research-tasks/{task_id}",
            f"/api/entities/{person.id}",
            f"/api/relationships/{relationship.id}",
            f"/api/relationships/{relationship.id}/evidence",
            f"/api/sources/{document.source_id}",
            f"/api/documents/{document_id}",
            f"/api/evidence/{evidence.id}",
            f"/api/reports/{report.id}",
        ]
        for path in direct_paths:
            response = await other.get(path)
            assert response.status_code == 404, (path, response.text)

        investigation_paths = [
            "",
            "/tasks",
            "/entities",
            "/entity-mentions",
            "/relationships",
            "/resolution-candidates",
            "/relationship-candidates",
            "/sources",
            "/documents",
            "/graph",
            "/reports",
        ]
        for suffix in investigation_paths:
            path = f"/api/investigations/{investigation_id}{suffix}"
            response = await other.get(path)
            assert response.status_code == 404, (path, response.text)

        unsafe = [
            (
                f"/api/investigations/{investigation_id}/search",
                {"query": "private", "filters": {}},
            ),
            (f"/api/investigations/{investigation_id}/ask", {"question": "What is private?"}),
            (f"/api/entity-resolution-candidates/{entity_candidate.id}/accept", None),
            (f"/api/relationship-candidates/{relationship_candidate.id}/reject", None),
        ]
        for path, payload in unsafe:
            response = await other.post(path, json=payload) if payload else await other.post(path)
            assert response.status_code == 404, (path, response.text)
