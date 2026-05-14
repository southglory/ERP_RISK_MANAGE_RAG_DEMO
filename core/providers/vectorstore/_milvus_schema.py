"""ERP_RISK collection schema — pgvector document_chunk 와 매핑."""

from pymilvus import CollectionSchema, DataType, FieldSchema

COLLECTION_NAME = "erp_risk_chunks"
DIM = 1024   # BGE-M3


def build_schema() -> CollectionSchema:
    fields = [
        FieldSchema(name="chunk_id",       dtype=DataType.VARCHAR, is_primary=True, max_length=128),
        FieldSchema(name="source_type",    dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="source_doc_id",  dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="document_title", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="content",        dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="span_start",     dtype=DataType.INT64),
        FieldSchema(name="span_end",       dtype=DataType.INT64),
        FieldSchema(name="dense_vec",      dtype=DataType.FLOAT_VECTOR, dim=DIM),
    ]
    return CollectionSchema(fields=fields, description="ERP risk RAG chunks (1024-d BGE-M3)")


def index_params() -> dict:
    """HNSW + cosine — pgvector 와 동일 metric."""
    return {
        "index_type":  "HNSW",
        "metric_type": "COSINE",
        "params":      {"M": 16, "efConstruction": 64},
    }
