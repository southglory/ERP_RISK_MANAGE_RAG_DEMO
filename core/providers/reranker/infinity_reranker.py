from __future__ import annotations
import os
import httpx
from core.providers.base import RerankerProvider, RankedDoc


class InfinityRerankerProvider(RerankerProvider):
    """bge-reranker-v2-m3 via infinity-emb server.

    Swap target: INFINITY_BASE_URL → Upstage Reranker API.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("INFINITY_BASE_URL", "http://localhost:8001")).rstrip("/")
        self.model = model or os.environ.get("RERANKER_MODEL", "bge-reranker-v2-m3")

    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[RankedDoc]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/rerank",
                json={"model": self.model, "query": query, "documents": documents,
                      "top_n": top_k, "return_documents": False},
            )
            resp.raise_for_status()
            results = resp.json()["results"]
            return [RankedDoc(index=r["index"], score=r["relevance_score"]) for r in results]
