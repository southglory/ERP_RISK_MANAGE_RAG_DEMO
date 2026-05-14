from __future__ import annotations
import os
import httpx
from core.providers.base import EmbeddingProvider


class InfinityEmbeddingProvider(EmbeddingProvider):
    """BGE-M3 via infinity-emb server. Dense + Sparse output.

    Swap target: INFINITY_BASE_URL → Upstage Embedding API base_url.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("INFINITY_BASE_URL", "http://localhost:8001")).rstrip("/")
        self.model = model or os.environ.get("EMBEDDING_MODEL", "bge-m3")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            data.sort(key=lambda x: x["index"])
            return [d["embedding"] for d in data]

    async def embed_sparse(self, texts: list[str]) -> list[dict[str, float]]:
        """BGE-M3 sparse output (SPLADE-style token weights)."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts, "encoding_format": "float",
                      "modality": "text", "extra_body": {"return_sparse": True}},
            )
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data", [])
            data.sort(key=lambda x: x["index"])
            return [d.get("sparse_embedding", {}) for d in data]
