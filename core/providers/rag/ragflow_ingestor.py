"""RAGflow document ingestor — parsing/chunking layer only.

Flow:
  1. create_dataset(name)  → dataset_id
  2. upload_document(dataset_id, file_bytes, filename)  → doc_id
  3. parse_document(dataset_id, doc_id)  → waits until done
  4. get_chunks(dataset_id, doc_id)  → list of parsed text chunks

We take these chunks → embed with BGE-M3 → store in pgvector.
RAGflow's internal vector search is NOT used.
"""
from __future__ import annotations
import asyncio
import os
import httpx


class RAGflowIngestor:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or os.environ["RAGFLOW_BASE_URL"]).rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key or os.environ['RAGFLOW_API_KEY']}",
            "Content-Type": "application/json",
        }

    async def create_dataset(self, name: str, chunk_method: str = "general") -> str:
        """Create a knowledge-base dataset. Returns dataset_id."""
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{self.base_url}/api/v1/datasets",
                headers=self._headers,
                json={
                    "name": name,
                    "chunk_method": chunk_method,  # "general"|"naive"|"paper"|"book"|"laws"|"qa"
                    "embedding_model": "",  # we supply embeddings externally
                    "permission": "me",
                },
            )
            r.raise_for_status()
            return r.json()["data"]["id"]

    async def upload_document(self, dataset_id: str, file_bytes: bytes,
                              filename: str) -> str:
        """Upload a file to a dataset. Returns document_id."""
        upload_headers = {k: v for k, v in self._headers.items()
                         if k != "Content-Type"}
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
                headers=upload_headers,
                files={"file": (filename, file_bytes)},
            )
            r.raise_for_status()
            return r.json()["data"][0]["id"]

    async def parse_document(self, dataset_id: str, doc_id: str,
                             poll_interval: float = 3.0, timeout: float = 300.0) -> None:
        """Trigger parsing and wait until status is 'done'."""
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
                headers=self._headers,
                json={"document_ids": [doc_id]},
            )
            r.raise_for_status()

        elapsed = 0.0
        async with httpx.AsyncClient(timeout=30.0) as c:
            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                r = await c.get(
                    f"{self.base_url}/api/v1/datasets/{dataset_id}/documents",
                    headers=self._headers,
                    params={"id": doc_id},
                )
                r.raise_for_status()
                docs = r.json()["data"]["docs"]
                if docs and docs[0].get("run") in ("DONE", "done", 3):
                    return
                if docs and docs[0].get("run") in ("FAIL", "fail", 2):
                    raise RuntimeError(f"RAGflow parsing failed for doc {doc_id}")
        raise TimeoutError(f"RAGflow parsing timed out after {timeout}s")

    async def get_chunks(self, dataset_id: str, doc_id: str) -> list[dict]:
        """Fetch parsed chunks. Returns list of {chunk_id, content, metadata}."""
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(
                f"{self.base_url}/api/v1/datasets/{dataset_id}/chunks",
                headers=self._headers,
                params={"document_id": doc_id, "page_size": 1000},
            )
            r.raise_for_status()
            raw = r.json()["data"]["chunks"]
        return [
            {
                "chunk_id": ch["id"],
                "content": ch.get("content_with_weight") or ch.get("content", ""),
                "metadata": {
                    "doc_id": doc_id,
                    "dataset_id": dataset_id,
                    "positions": ch.get("positions", []),
                    "image_id": ch.get("img_id"),
                },
            }
            for ch in raw
        ]

    async def ingest(self, file_bytes: bytes, filename: str,
                     dataset_name: str, chunk_method: str = "laws") -> list[dict]:
        """One-shot: create dataset → upload → parse → return chunks."""
        dataset_id = await self.create_dataset(dataset_name, chunk_method)
        doc_id = await self.upload_document(dataset_id, file_bytes, filename)
        await self.parse_document(dataset_id, doc_id)
        return await self.get_chunks(dataset_id, doc_id)
