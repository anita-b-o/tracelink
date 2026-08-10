from __future__ import annotations

import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tracelink.core.config import Settings
from tracelink.domain.enums import (
    EntityResolutionCandidateStatus,
    EntityResolutionDecision,
    EntityType,
)
from tracelink.domain.models import Entity, EntityAlias, EntityMention, JsonObject
from tracelink.domain.normalization import NormalizedEntityName, normalize_entity_name
from tracelink.repositories.entities import EntityRepository
from tracelink.repositories.entity_mentions import EntityResolutionCandidateRepository


class ResolutionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: EntityResolutionDecision
    entity_id: UUID | None = None
    score: float = Field(ge=0, le=1)
    signals: dict[str, JsonValue] = Field(default_factory=dict)
    reason_code: str


@dataclass(frozen=True, slots=True)
class GeneratedEntityCandidate:
    entity: Entity
    textual_similarity: float
    exact_alias: bool


def _tokens(value: str) -> set[str]:
    return {token for token in value.replace("-", " ").split() if token}


def _token_similarity(left: str, right: str) -> float:
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _context(attributes: dict[str, JsonValue]) -> dict[str, str]:
    allowed = {
        "company",
        "organization",
        "role",
        "location",
        "public_identifier",
        "registration_number",
        "jurisdiction",
        "domain",
    }
    return {
        key: " ".join(value.split()).casefold()
        for key, value in attributes.items()
        if key in allowed and isinstance(value, str) and value.strip()
    }


class EntityCandidateGenerator:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def generate(
        self, entity_type: EntityType, comparison_key: str, *, limit: int = 25
    ) -> list[GeneratedEntityCandidate]:
        threshold = 0.30
        entity_similarity = func.similarity(Entity.comparison_key, comparison_key)
        entity_rows = await self.session.execute(
            select(Entity, entity_similarity.label("similarity"))
            .options(selectinload(Entity.aliases))
            .where(
                Entity.type == entity_type,
                or_(
                    Entity.comparison_key == comparison_key,
                    entity_similarity >= threshold,
                ),
            )
            .order_by(entity_similarity.desc(), Entity.created_at, Entity.id)
            .limit(limit)
        )
        candidates: dict[UUID, GeneratedEntityCandidate] = {
            entity.id: GeneratedEntityCandidate(entity, float(similarity), False)
            for entity, similarity in entity_rows
        }

        alias_similarity = func.similarity(EntityAlias.comparison_key, comparison_key)
        alias_rows = await self.session.execute(
            select(Entity, EntityAlias.comparison_key, alias_similarity.label("similarity"))
            .join(EntityAlias, EntityAlias.entity_id == Entity.id)
            .options(selectinload(Entity.aliases))
            .where(
                Entity.type == entity_type,
                or_(
                    EntityAlias.comparison_key == comparison_key,
                    alias_similarity >= threshold,
                ),
            )
            .order_by(alias_similarity.desc(), Entity.created_at, Entity.id)
            .limit(limit)
        )
        for entity, alias_key, similarity in alias_rows:
            previous = candidates.get(entity.id)
            exact_alias = alias_key == comparison_key
            score = float(similarity)
            if previous is None or score > previous.textual_similarity or exact_alias:
                candidates[entity.id] = GeneratedEntityCandidate(
                    entity,
                    max(score, previous.textual_similarity if previous else 0.0),
                    exact_alias or (previous.exact_alias if previous else False),
                )
        return sorted(
            candidates.values(),
            key=lambda item: (-item.textual_similarity, item.entity.created_at, item.entity.id),
        )[:limit]


class EntityResolutionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.entities = EntityRepository(session)
        self.candidates = EntityResolutionCandidateRepository(session)
        self.generator = EntityCandidateGenerator(session)

    @staticmethod
    def _lock_key(entity_type: EntityType, comparison_key: str) -> int:
        digest = hashlib.sha256(f"{entity_type.value}:{comparison_key}".encode()).digest()
        return int.from_bytes(digest[:8], signed=True)

    @staticmethod
    def _score(
        generated: GeneratedEntityCandidate,
        normalized: NormalizedEntityName,
        attributes: dict[str, JsonValue],
    ) -> tuple[float, JsonObject, bool]:
        entity = generated.entity
        exact_name = entity.comparison_key == normalized.comparison_key
        exact_alias = generated.exact_alias
        text_score = max(
            generated.textual_similarity,
            SequenceMatcher(None, normalized.comparison_key, entity.comparison_key).ratio(),
        )
        token_score = _token_similarity(normalized.comparison_key, entity.comparison_key)
        if exact_alias:
            score = 0.93
        elif exact_name:
            score = 0.90
        else:
            score = 0.55 * text_score + 0.15 * token_score

        incoming_context = _context(attributes)
        stored_value = entity.metadata_.get("resolution_context", {})
        stored_context = (
            {str(key): str(value) for key, value in stored_value.items()}
            if isinstance(stored_value, dict)
            else {}
        )
        agreements = {
            key: incoming_context[key] == stored_context[key]
            for key in incoming_context.keys() & stored_context.keys()
        }
        conflicts = {key: matches for key, matches in agreements.items() if not matches}
        for key, matches in agreements.items():
            if matches:
                score += 0.25 if key in {"public_identifier", "registration_number"} else 0.08
            else:
                score -= 0.12
        same_company = agreements.get("company", False) or agreements.get("organization", False)
        same_role = agreements.get("role", False)
        same_location = agreements.get("location", False)
        strong_person_context = (
            agreements.get("public_identifier", False)
            or (same_company and same_role)
            or (same_location and same_role)
        )
        if strong_person_context:
            score += 0.12
        score = min(1.0, max(0.0, score))
        signals: JsonObject = {
            "exact_normalized_name": exact_name,
            "exact_alias": exact_alias,
            "same_type": True,
            "textual_similarity": round(text_score, 4),
            "token_similarity": round(token_score, 4),
            "context_agreement": sorted(key for key, matches in agreements.items() if matches),
            "context_conflicts": sorted(conflicts),
            "strong_person_context": strong_person_context,
        }
        return score, signals, strong_person_context

    async def _create_entity(
        self,
        entity_type: EntityType,
        normalized: NormalizedEntityName,
        attributes: dict[str, JsonValue],
        *,
        provisional: bool,
    ) -> Entity:
        metadata: JsonObject = {
            "resolution_context": _context(attributes),
            **({"resolution_provisional": True} if provisional else {}),
        }
        return await self.entities.create(
            entity_type=entity_type,
            canonical_name=normalized.canonical,
            normalized_name=normalized.normalized,
            comparison_key=normalized.comparison_key,
            metadata=metadata,
        )

    async def resolve(
        self,
        mention: EntityMention,
        *,
        canonical_name_candidate: str,
        attributes: dict[str, JsonValue],
    ) -> ResolutionDecision:
        normalized = normalize_entity_name(mention.entity_type, canonical_name_candidate)
        await self.session.execute(
            select(
                func.pg_advisory_xact_lock(
                    self._lock_key(mention.entity_type, normalized.comparison_key)
                )
            )
        )
        generated = await self.generator.generate(mention.entity_type, normalized.comparison_key)
        scored = [
            (candidate, *self._score(candidate, normalized, attributes)) for candidate in generated
        ]
        scored.sort(key=lambda item: (-item[1], item[0].entity.created_at, item[0].entity.id))
        top = scored[0] if scored else None

        if top is None:
            entity = await self._create_entity(
                mention.entity_type, normalized, attributes, provisional=False
            )
            mention.entity_id = entity.id
            return ResolutionDecision(
                decision=EntityResolutionDecision.CREATE_NEW,
                entity_id=entity.id,
                score=0,
                reason_code="NO_PLAUSIBLE_CANDIDATE",
            )

        _, top_score, top_signals, strong_person_context = top
        person_gate = mention.entity_type is not EntityType.PERSON or strong_person_context
        if top_score >= self.settings.entity_resolution_auto_match_threshold and person_gate:
            matched = top[0].entity
            mention.entity_id = matched.id
            decision = EntityResolutionDecision.MATCH_EXISTING
            reason_code = "AUTO_MATCH_THRESHOLD_MET"
            resolved_entity = matched
        elif top_score >= self.settings.entity_resolution_possible_match_threshold:
            resolved_entity = await self._create_entity(
                mention.entity_type, normalized, attributes, provisional=True
            )
            mention.entity_id = resolved_entity.id
            decision = EntityResolutionDecision.POSSIBLE_MATCH
            reason_code = (
                "PERSON_REQUIRES_STRONG_CONTEXT"
                if mention.entity_type is EntityType.PERSON and not strong_person_context
                else "POSSIBLE_MATCH_THRESHOLD_MET"
            )
        else:
            resolved_entity = await self._create_entity(
                mention.entity_type, normalized, attributes, provisional=False
            )
            mention.entity_id = resolved_entity.id
            decision = EntityResolutionDecision.CREATE_NEW
            reason_code = "BELOW_POSSIBLE_MATCH_THRESHOLD"

        for candidate, score, signals, _ in scored:
            if score < self.settings.entity_resolution_possible_match_threshold:
                continue
            status = (
                EntityResolutionCandidateStatus.AUTO_MATCHED
                if decision is EntityResolutionDecision.MATCH_EXISTING
                and candidate.entity.id == resolved_entity.id
                else EntityResolutionCandidateStatus.PENDING
            )
            await self.candidates.upsert(
                investigation_id=mention.investigation_id,
                mention_id=mention.id,
                candidate_entity_id=candidate.entity.id,
                score=score,
                status=status,
                signals=signals,
            )

        if decision is EntityResolutionDecision.MATCH_EXISTING:
            surface_parts = normalize_entity_name(mention.entity_type, mention.surface_form)
            if surface_parts.comparison_key != resolved_entity.comparison_key:
                existing_alias = await self.entities.get_alias(
                    resolved_entity.id, surface_parts.comparison_key
                )
                if existing_alias is None:
                    await self.entities.add_alias(
                        resolved_entity,
                        surface_parts.canonical,
                        surface_parts.normalized,
                        surface_parts.comparison_key,
                    )
        return ResolutionDecision(
            decision=decision,
            entity_id=resolved_entity.id,
            score=top_score,
            signals=top_signals,
            reason_code=reason_code,
        )
