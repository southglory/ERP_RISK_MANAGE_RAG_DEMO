-- 문서 원본 메타데이터 테이블 (MinIO 경로 추적)
CREATE TABLE IF NOT EXISTS documents (
  doc_id          TEXT PRIMARY KEY,
  title           TEXT NOT NULL,
  source_type     TEXT NOT NULL,
  origin          TEXT NOT NULL DEFAULT 'synthetic'
                  CHECK (origin IN ('synthetic', 'law_api', 'upload')),
  file_format     TEXT NOT NULL DEFAULT 'txt'
                  CHECK (file_format IN ('txt', 'pdf', 'xml', 'docx')),
  storage_path    TEXT NOT NULL,        -- MinIO: laws/{source_type}/{filename}
  file_size_bytes BIGINT,
  chunk_count     INT NOT NULL DEFAULT 0,
  ingested_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_type);
CREATE INDEX IF NOT EXISTS idx_documents_origin ON documents(origin);
