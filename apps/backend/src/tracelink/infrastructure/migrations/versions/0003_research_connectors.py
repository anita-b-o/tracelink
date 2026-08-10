"""Add normalized source URL identity for research connectors.

Revision ID: 0003_research_connectors
Revises: 0002_investigation_workflow
Create Date: 2026-08-10
"""

import hashlib
import ipaddress
from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
from alembic import op

revision: str = "0003_research_connectors"
down_revision: str | Sequence[str] | None = "0002_investigation_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalize_legacy_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return value.strip()
        host_value = parsed.hostname.rstrip(".")
        try:
            ip = ipaddress.ip_address(host_value)
        except ValueError:
            host = host_value.encode("idna").decode("ascii").lower()
        else:
            host = ip.compressed
            if ip.version == 6:
                host = f"[{host}]"
        port = parsed.port
        default = (parsed.scheme.lower() == "http" and port == 80) or (
            parsed.scheme.lower() == "https" and port == 443
        )
        netloc = host if port is None or default else f"{host}:{port}"
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))
    except (UnicodeError, ValueError):
        return value.strip()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("sources", sa.Column("normalized_url", sa.Text(), nullable=True))
    rows = bind.execute(sa.text("SELECT id, url FROM sources")).mappings()
    for row in rows:
        normalized = _normalize_legacy_url(str(row["url"]))
        bind.execute(
            sa.text(
                "UPDATE sources SET normalized_url = :normalized, url_hash = :url_hash "
                "WHERE id = :source_id"
            ),
            {"normalized": normalized, "url_hash": _hash(normalized), "source_id": row["id"]},
        )
    op.alter_column("sources", "normalized_url", nullable=False)
    op.create_index(
        "ix_sources_url_identity", "sources", ["url_hash", "normalized_url"], unique=False
    )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, url FROM sources")).mappings()
    for row in rows:
        raw_url = str(row["url"])
        bind.execute(
            sa.text("UPDATE sources SET url_hash = :url_hash WHERE id = :source_id"),
            {"url_hash": _hash(raw_url), "source_id": row["id"]},
        )
    op.drop_index("ix_sources_url_identity", table_name="sources")
    op.drop_column("sources", "normalized_url")
