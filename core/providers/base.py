from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class RankedDoc:
    index: int
    score: float


@dataclass
class SearchResult:
    chunk_id: str
    content: str
    score: float
    metadata: dict


@dataclass
class Document:
    chunk_id: str
    source_type: str          # tax_law | court | ruling | contract | internal
    source_doc_id: str
    document_title: str
    content: str
    dense_vec: list[float]
    sparse_tokens: dict       # {token: weight} — backend 가 무시할 수도 있음
    metadata: dict
    span_start: int | None = None
    span_end: int | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[ChatMessage], **kwargs) -> str: ...

    @abstractmethod
    def chat_stream(self, messages: list[ChatMessage], **kwargs) -> AsyncIterator[str]: ...


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Dense embeddings (1024-dim for BGE-M3)."""
        ...

    async def embed_sparse(self, texts: list[str]) -> list[dict[str, float]]:
        """Sparse (SPLADE-like) token weights. Override if supported."""
        return [{} for _ in texts]


class RerankerProvider(ABC):
    @abstractmethod
    async def rerank(self, query: str, documents: list[str], top_k: int) -> list[RankedDoc]: ...


class VectorStore(ABC):
    """Backend-agnostic storage gateway.

    구현체는 dense/sparse 중 하나만 실제로 지원해도 된다.
    sparse 미지원이면 search_sparse 가 빈 리스트를 반환하도록 한다 (RRF 가 graceful 하게 dense 만 사용).
    """

    @abstractmethod
    async def upsert(self, doc: Document) -> None: ...

    @abstractmethod
    async def search_dense(
        self,
        query_vec: list[float],
        top_k: int,
        source_types: list[str] | None = None,
    ) -> list[SearchResult]: ...

    @abstractmethod
    async def search_sparse(
        self,
        query_text: str,
        top_k: int,
        source_types: list[str] | None = None,
    ) -> list[SearchResult]: ...

    @abstractmethod
    async def close(self) -> None: ...


class ERPProvider(ABC):
    @abstractmethod
    async def get_journal_entries(self, from_date: str, to_date: str) -> list[dict]: ...

    @abstractmethod
    async def get_sales_invoices(self, from_date: str, to_date: str) -> list[dict]: ...

    @abstractmethod
    async def get_purchase_invoices(self, from_date: str, to_date: str) -> list[dict]: ...

    @abstractmethod
    async def get_gl_entries(self, account: str, from_date: str, to_date: str) -> list[dict]: ...


class OCRProvider(ABC):
    @abstractmethod
    async def extract_text(self, image_bytes: bytes, mime_type: str = "image/png") -> str: ...
