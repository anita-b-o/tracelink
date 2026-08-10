from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from tracelink.domain.enums import EntityType
from tracelink.domain.models import Entity
from tracelink.repositories.entities import EntityRepository
from tracelink.services.entities import EntityService
from tracelink.services.errors import DomainConflictError


@pytest.mark.asyncio
async def test_entity_service_rejects_alias_matching_canonical_name() -> None:
    repository = Mock(spec=EntityRepository)
    repository.create = AsyncMock(
        return_value=Entity(
            id=uuid4(),
            type=EntityType.COMPANY,
            canonical_name="ACME",
            normalized_name="acme",
            metadata_={},
        )
    )
    service = EntityService(repository)

    with pytest.raises(DomainConflictError, match="duplicates"):
        await service.create(
            entity_type=EntityType.COMPANY,
            canonical_name="ACME",
            aliases=["  acme  "],
        )


@pytest.mark.asyncio
async def test_entity_service_rejects_duplicate_normalized_aliases() -> None:
    repository = Mock(spec=EntityRepository)
    repository.create = AsyncMock(
        return_value=Entity(
            id=uuid4(),
            type=EntityType.COMPANY,
            canonical_name="ACME",
            normalized_name="acme",
            metadata_={},
        )
    )
    repository.add_alias = AsyncMock()
    service = EntityService(repository)

    with pytest.raises(DomainConflictError, match="duplicates"):
        await service.create(
            entity_type=EntityType.COMPANY,
            canonical_name="ACME",
            aliases=["Acme Corp", "ＡＣＭＥ ＣＯＲＰ"],
        )
