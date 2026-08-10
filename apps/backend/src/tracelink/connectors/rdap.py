from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from tracelink.connectors.errors import ConnectorFetchError, InvalidConnectorInputError
from tracelink.connectors.http import ResearchHttpClient
from tracelink.connectors.models import (
    ConnectorContext,
    ConnectorOutput,
    DocumentArtifact,
    SourceArtifact,
)
from tracelink.connectors.url_safety import normalize_url
from tracelink.domain.enums import ResearchTaskType

IANA_RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
RDAP_CONTENT_TYPES = frozenset({"application/json", "application/rdap+json"})


def normalize_domain(value: str) -> str:
    candidate = value.strip().rstrip(".")
    if "://" in candidate or any(character.isspace() for character in candidate):
        raise InvalidConnectorInputError("a bare domain is required")
    try:
        domain = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise InvalidConnectorInputError("a valid domain is required") from exc
    labels = domain.split(".")
    if len(labels) < 2 or len(domain) > 253:
        raise InvalidConnectorInputError("a valid domain is required")
    for label in labels:
        if (
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(character.isalnum() or character == "-" for character in label)
        ):
            raise InvalidConnectorInputError("a valid domain is required")
    return domain


def select_rdap_base_url(bootstrap: dict[str, Any], domain: str) -> str:
    best_match = ""
    best_urls: list[str] = []
    for service in bootstrap.get("services", []):
        if not isinstance(service, list) or len(service) != 2:
            continue
        entries, urls = service
        if not isinstance(entries, list) or not isinstance(urls, list):
            continue
        for entry in entries:
            if not isinstance(entry, str):
                continue
            normalized_entry = entry.lower()
            if (domain == normalized_entry or domain.endswith(f".{normalized_entry}")) and len(
                normalized_entry
            ) > len(best_match):
                best_match = normalized_entry
                best_urls = [url for url in urls if isinstance(url, str)]
    secure = next((url for url in best_urls if url.lower().startswith("https://")), None)
    if secure is None:
        raise InvalidConnectorInputError("no secure RDAP service is registered for the domain")
    return normalize_url(secure)


def _registrar(entities: list[Any]) -> str | None:
    for entity in entities:
        if not isinstance(entity, dict) or "registrar" not in entity.get("roles", []):
            continue
        vcard = entity.get("vcardArray")
        if not isinstance(vcard, list) or len(vcard) != 2 or not isinstance(vcard[1], list):
            continue
        for item in vcard[1]:
            if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
                return str(item[3])
    return None


def _json_object(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConnectorFetchError("the RDAP service returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ConnectorFetchError("the RDAP service returned an invalid object")
    return payload


def _entity_references(entities: list[Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for entity in entities[:50]:
        if not isinstance(entity, dict):
            continue
        raw_roles = entity.get("roles")
        roles: list[Any] = raw_roles if isinstance(raw_roles, list) else []
        references.append(
            {
                "handle": entity.get("handle"),
                "roles": [str(role) for role in roles[:10]],
            }
        )
    return references


def _event_references(events: list[Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for event in events[:100]:
        if not isinstance(event, dict):
            continue
        references.append(
            {
                "action": event.get("eventAction"),
                "date": event.get("eventDate"),
            }
        )
    return references


class RDAPConnector:
    name = "rdap"
    supported_task_types = frozenset({ResearchTaskType.DOMAIN_LOOKUP})
    requests_per_second: int | None = 1

    def __init__(self, http: ResearchHttpClient) -> None:
        self.http = http

    def normalize(self, value: str) -> str:
        return normalize_domain(value)

    async def execute(self, value: str, context: ConnectorContext) -> ConnectorOutput:
        _ = context
        domain = self.normalize(value)
        bootstrap_fetch = await self.http.fetch(
            IANA_RDAP_BOOTSTRAP_URL,
            connector="rdap_bootstrap",
            allowed_content_types=RDAP_CONTENT_TYPES,
            requests_per_second=self.requests_per_second,
        )
        bootstrap = _json_object(bootstrap_fetch.text)
        base_url = select_rdap_base_url(bootstrap, domain)
        endpoint = urljoin(f"{base_url.rstrip('/')}/", f"domain/{quote(domain, safe='.-')}")
        fetch = await self.http.fetch(
            endpoint,
            connector=self.name,
            allowed_content_types=RDAP_CONTENT_TYPES,
            requests_per_second=self.requests_per_second,
        )
        payload = _json_object(fetch.text)
        normalized_endpoint = normalize_url(fetch.url)
        entities: list[Any] = (
            payload["entities"] if isinstance(payload.get("entities"), list) else []
        )
        events: list[Any] = payload["events"] if isinstance(payload.get("events"), list) else []
        nameservers = payload.get("nameservers")
        nameserver_names = (
            [
                item.get("ldhName")
                for item in nameservers[:100]
                if isinstance(item, dict) and isinstance(item.get("ldhName"), str)
            ]
            if isinstance(nameservers, list)
            else []
        )
        raw_status = payload.get("status")
        statuses: list[Any] = raw_status if isinstance(raw_status, list) else []
        structured = {
            "domain_name": payload.get("ldhName") or payload.get("unicodeName") or domain,
            "handle": payload.get("handle"),
            "status": [str(item) for item in statuses[:50]],
            "nameservers": nameserver_names,
            "events": _event_references(events),
            "registrar": _registrar(entities),
            "entities": _entity_references(entities),
        }
        metadata = {
            "status_code": fetch.status_code,
            "final_url": normalized_endpoint,
            "content_length": fetch.metadata.get("content_length"),
            "connector_name": self.name,
            **structured,
        }
        for key in ("etag", "last_modified"):
            if header := fetch.metadata.get(key):
                metadata[key] = header
        raw_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return ConnectorOutput(
            connector=self.name,
            sources=[
                SourceArtifact(
                    source_type="rdap",
                    url=fetch.url,
                    normalized_url=normalized_endpoint,
                    publisher=urlsplit(normalized_endpoint).hostname,
                    title=str(structured["domain_name"]),
                    retrieved_at=fetch.retrieved_at,
                    metadata=metadata,
                )
            ],
            documents=[
                DocumentArtifact(
                    source_normalized_url=normalized_endpoint,
                    mime_type=fetch.content_type,
                    raw_text=raw_text,
                    metadata={
                        "status_code": fetch.status_code,
                        "final_url": normalized_endpoint,
                        "content_length": len(raw_text.encode()),
                        "connector_name": self.name,
                    },
                )
            ],
            result_count=1,
            metadata={
                **structured,
                "cache_hit": fetch.cache_hit,
                "bootstrap_cache_hit": bootstrap_fetch.cache_hit,
                "retry_count": fetch.retry_count + bootstrap_fetch.retry_count,
            },
        )
