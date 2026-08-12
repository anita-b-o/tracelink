from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.domain.rag import GroundedAnswerResult, RetrievalFilters
from tracelink.observability.metrics import LLM_CALLS
from tracelink.services.citations import CitationValidator
from tracelink.services.grounded_context import GroundedContextBuilder
from tracelink.services.hybrid_retrieval import HybridRetriever
from tracelink.services.llm_providers import LLMProvider

logger = logging.getLogger(__name__)

ABSTENTION_ANSWER = (
    "No hay evidencia suficiente en esta investigación para responder con confianza."
)


class GroundedAnswerService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        retriever: HybridRetriever,
        llm_provider: LLMProvider,
    ) -> None:
        self.session = session
        self.settings = settings
        self.retriever = retriever
        self.llm_provider = llm_provider

    async def answer(self, investigation_id: UUID, question: str) -> GroundedAnswerResult:
        hits = await self.retriever.search(
            investigation_id, question, filters=RetrievalFilters(), top_k=self.settings.rag_top_k
        )
        context = await GroundedContextBuilder(self.session, self.settings).build(
            investigation_id, hits
        )
        if (
            not hits
            or hits[0].combined_score < self.settings.rag_min_retrieval_score
            or context.evidence_count < self.settings.rag_min_evidence_count
        ):
            logger.info(
                "grounded answer abstained",
                extra={"investigation_id": str(investigation_id), "abstained": True},
            )
            return GroundedAnswerResult(
                answer=ABSTENTION_ANSWER,
                abstained=True,
                confidence=0.0,
                claims=[],
                citations=[],
                limitations=["La evidencia recuperada no supera los umbrales configurados."],
                contradictions=context.contradictions,
            )

        try:
            generated = await self.llm_provider.generate_answer(question, context)
        except Exception:
            LLM_CALLS.labels(self.llm_provider.provider_name, "failure").inc()
            raise
        LLM_CALLS.labels(self.llm_provider.provider_name, "success").inc()
        claims = await CitationValidator(self.session).validate_claims(context, generated.claims)
        capped_claims = []
        for claim in claims:
            support = max(
                float(context.allowed_citations[ref].get("confidence", hits[0].combined_score))
                for ref in claim.citation_ids
            )
            capped_claims.append(
                claim.model_copy(update={"confidence": min(claim.confidence, support)})
            )
        citations = []
        seen: set[str] = set()
        for claim in capped_claims:
            for ref in claim.citation_ids:
                if ref not in seen:
                    citations.append({"id": ref, **context.allowed_citations[ref]})
                    seen.add(ref)
        confidence = (
            sum(claim.confidence for claim in capped_claims) / len(capped_claims)
            if capped_claims
            else 0.0
        )
        return GroundedAnswerResult(
            answer=" ".join(claim.text for claim in capped_claims),
            abstained=False,
            confidence=confidence,
            claims=capped_claims,
            citations=citations,
            limitations=generated.limitations,
            contradictions=context.contradictions,
        )
