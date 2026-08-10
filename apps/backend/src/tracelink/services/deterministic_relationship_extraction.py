from __future__ import annotations

import json
import re
from typing import Any

from tracelink.domain.enums import EntityType, RelationshipClaimKind, RelationshipType
from tracelink.domain.normalization import normalize_entity_name
from tracelink.domain.relationship_extraction import (
    ExtractedRelationshipCandidate,
    ResolvedRelationshipMention,
)

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_REDACTED = frozenset({"redacted", "private", "privacy", "proxy", "not disclosed"})


def _escaped(mention: ResolvedRelationshipMention) -> str:
    return re.escape(mention.surface_form)


def _candidate(
    source: ResolvedRelationshipMention,
    target: ResolvedRelationshipMention,
    relationship_type: RelationshipType,
    match: re.Match[str],
    *,
    claim_kind: RelationshipClaimKind = RelationshipClaimKind.AFFIRMS,
    confidence: float = 0.97,
    attributes: dict[str, Any] | None = None,
) -> ExtractedRelationshipCandidate:
    year_match = _YEAR.search(match.group())
    temporal_end = (
        year_match.group() if year_match and claim_kind is RelationshipClaimKind.ENDS else None
    )
    return ExtractedRelationshipCandidate(
        source_mention_id=source.mention_id,
        target_mention_id=target.mention_id,
        source_entity_id=source.entity_id,
        target_entity_id=target.entity_id,
        type=relationship_type,
        claim_kind=claim_kind,
        confidence=confidence,
        start_offset=match.start(),
        end_offset=match.end(),
        temporal_end=temporal_end,
        current_state=claim_kind is RelationshipClaimKind.AFFIRMS
        and " es " in match.group().casefold(),
        attributes=attributes or {},
    )


def _textual_candidates(
    text: str, mentions: list[ResolvedRelationshipMention]
) -> list[ExtractedRelationshipCandidate]:
    results: list[ExtractedRelationshipCandidate] = []
    people = [mention for mention in mentions if mention.entity_type is EntityType.PERSON]
    organizations = [
        mention
        for mention in mentions
        if mention.entity_type in {EntityType.COMPANY, EntityType.ORGANIZATION}
    ]
    for person in people:
        for organization in organizations:
            person_name, organization_name = _escaped(person), _escaped(organization)
            director_patterns = (
                rf"{person_name}.{{0,50}}(?:fue\s+designad[oa]|es|was\s+appointed|is)\s+"
                rf"(?:director(?:a)?|presidente|president).{{0,30}}(?:de|of)\s+{organization_name}",
            )
            end_patterns = (
                rf"{person_name}.{{0,40}}(?:dej[oó]\s+de\s+ser|ceased\s+to\s+be)\s+"
                rf"(?:director(?:a)?|presidente|president).{{0,30}}(?:de|of)\s+{organization_name}"
                rf"(?:.{{0,25}}(?:19|20)\d{{2}})?",
            )
            employee_patterns = (
                rf"{person_name}.{{0,35}}(?:es\s+emplead[oa]\s+de|trabaja\s+(?:para|en)|"
                rf"is\s+employed\s+by|works\s+for)\s+{organization_name}",
            )
            for pattern in director_patterns:
                if match := re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                    results.append(
                        _candidate(person, organization, RelationshipType.DIRECTOR_OF, match)
                    )
            for pattern in end_patterns:
                if match := re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                    results.append(
                        _candidate(
                            person,
                            organization,
                            RelationshipType.DIRECTOR_OF,
                            match,
                            claim_kind=RelationshipClaimKind.ENDS,
                            confidence=0.98,
                        )
                    )
            for pattern in employee_patterns:
                if match := re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                    results.append(
                        _candidate(person, organization, RelationshipType.EMPLOYEE_OF, match)
                    )

    owners = [
        mention
        for mention in mentions
        if mention.entity_type in {EntityType.PERSON, EntityType.COMPANY}
    ]
    owned = [
        mention
        for mention in mentions
        if mention.entity_type in {EntityType.COMPANY, EntityType.DOMAIN}
    ]
    for owner in owners:
        for target in owned:
            if owner.entity_id == target.entity_id:
                continue
            owner_name, target_name = _escaped(owner), _escaped(target)
            patterns = (
                rf"{owner_name}.{{0,35}}(?:es\s+(?:el\s+)?dueñ[oa]\s+de|owns)\s+{target_name}",
                rf"{target_name}.{{0,35}}(?:pertenece\s+a|is\s+owned\s+by)\s+{owner_name}",
            )
            for pattern in patterns:
                if match := re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                    results.append(_candidate(owner, target, RelationshipType.OWNER_OF, match))
                    break
    return results


def _vcard_names(entity: dict[str, Any]) -> list[str]:
    vcard = entity.get("vcardArray")
    if not isinstance(vcard, list) or len(vcard) != 2 or not isinstance(vcard[1], list):
        return []
    values: list[str] = []
    for item in vcard[1]:
        if (
            isinstance(item, list)
            and len(item) >= 4
            and item[0] in {"org", "fn"}
            and isinstance(item[3], str)
        ):
            value = item[3].strip()
            if value and not any(marker in value.casefold() for marker in _REDACTED):
                values.append(value)
    return values


def _rdap_candidates(
    text: str, mentions: list[ResolvedRelationshipMention]
) -> list[ExtractedRelationshipCandidate]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    domain_name = payload.get("ldhName") or payload.get("unicodeName")
    entities = payload.get("entities")
    if not isinstance(domain_name, str) or not isinstance(entities, list):
        return []
    domain_mentions = [
        mention
        for mention in mentions
        if mention.entity_type is EntityType.DOMAIN
        and mention.canonical_name.casefold().rstrip(".") == domain_name.casefold().rstrip(".")
    ]
    if not domain_mentions:
        return []
    candidates: list[ExtractedRelationshipCandidate] = []
    for item in entities:
        if not isinstance(item, dict) or "registrant" not in item.get("roles", []):
            continue
        for public_name in _vcard_names(item):
            matching = []
            for mention in mentions:
                if mention.entity_type not in {
                    EntityType.PERSON,
                    EntityType.COMPANY,
                    EntityType.ORGANIZATION,
                }:
                    continue
                normalized_public = normalize_entity_name(mention.entity_type, public_name)
                normalized_mention = normalize_entity_name(
                    mention.entity_type, mention.canonical_name
                )
                if normalized_public.comparison_key == normalized_mention.comparison_key:
                    matching.append(mention)
            for owner in matching:
                owner_position = text.find(public_name)
                domain_position = text.find(domain_name)
                positions = [
                    position for position in (owner_position, domain_position) if position >= 0
                ]
                start = min(positions) if positions else None
                end = (
                    max(owner_position + len(public_name), domain_position + len(domain_name))
                    if owner_position >= 0 and domain_position >= 0
                    else None
                )
                candidates.append(
                    ExtractedRelationshipCandidate(
                        source_mention_id=owner.mention_id,
                        target_mention_id=domain_mentions[0].mention_id,
                        source_entity_id=owner.entity_id,
                        target_entity_id=domain_mentions[0].entity_id,
                        type=RelationshipType.OWNS_DOMAIN,
                        confidence=0.99,
                        start_offset=start,
                        end_offset=end,
                        attributes={
                            "rdap_role": "registrant",
                            "structured_locator": "entities.vcardArray",
                        },
                    )
                )
    return candidates


def extract_deterministic_relationships(
    text: str, mentions: list[ResolvedRelationshipMention]
) -> list[ExtractedRelationshipCandidate]:
    return [*_textual_candidates(text, mentions), *_rdap_candidates(text, mentions)]
