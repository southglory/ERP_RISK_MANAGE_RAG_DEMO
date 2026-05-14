"""VectorStore ABC 의 메서드 시그니처가 backend 가 따라야 할 계약을 정의한다."""

import inspect

from core.providers.base import Document, VectorStore


def test_document_required_fields():
    doc = Document(
        chunk_id="x_0001_abcd",
        source_type="tax_law",
        source_doc_id="x",
        document_title="t",
        content="c",
        dense_vec=[0.0] * 1024,
        sparse_tokens={},
        metadata={},
        span_start=0,
        span_end=10,
    )
    assert doc.chunk_id == "x_0001_abcd"
    assert len(doc.dense_vec) == 1024


def test_vector_store_is_abstract():
    assert inspect.isabstract(VectorStore)
    methods = {n for n, _ in inspect.getmembers(VectorStore, predicate=inspect.isfunction)}
    assert {"upsert", "search_dense", "search_sparse", "close"} <= methods
