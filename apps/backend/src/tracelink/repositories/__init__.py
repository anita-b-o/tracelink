"""Small persistence repositories for the core domain."""

from tracelink.repositories.documents import DocumentRepository
from tracelink.repositories.entities import EntityRepository
from tracelink.repositories.evidence import EvidenceRepository
from tracelink.repositories.findings import FindingRepository
from tracelink.repositories.investigations import InvestigationRepository
from tracelink.repositories.relationships import RelationshipRepository
from tracelink.repositories.sources import SourceRepository

__all__ = [
    "DocumentRepository",
    "EntityRepository",
    "EvidenceRepository",
    "FindingRepository",
    "InvestigationRepository",
    "RelationshipRepository",
    "SourceRepository",
]
