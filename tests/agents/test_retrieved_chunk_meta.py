from core.rag.models import RetrievedChunk, SourceType


def test_retrieved_chunk_has_source_doc_id():
    c = RetrievedChunk(
        chunk_id="c1",
        source_type=SourceType.TAX_LAW,
        source_doc_id="부가가치세법",
        document_title="t",
        content="x",
    )
    assert c.source_doc_id == "부가가치세법"


def test_retrieved_chunk_source_doc_id_default_empty():
    c = RetrievedChunk(
        chunk_id="c1",
        source_type=SourceType.TAX_LAW,
        document_title="t",
        content="x",
    )
    assert c.source_doc_id == ""
