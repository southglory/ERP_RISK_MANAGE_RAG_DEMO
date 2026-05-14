-- Phase 3-2: BM25 sparse 검색 컬럼 + GIN 인덱스 + 자동 갱신 트리거

ALTER TABLE document_chunk
  ADD COLUMN IF NOT EXISTS content_tsv tsvector;

-- 기존 행 백필
UPDATE document_chunk
  SET content_tsv = to_tsvector('simple', content)
  WHERE content_tsv IS NULL;

-- 새 행 자동 생성 트리거
CREATE OR REPLACE FUNCTION fn_chunk_tsv_update() RETURNS trigger AS $$
BEGIN
  NEW.content_tsv := to_tsvector('simple', NEW.content);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chunk_tsv ON document_chunk;
CREATE TRIGGER trg_chunk_tsv
  BEFORE INSERT OR UPDATE OF content ON document_chunk
  FOR EACH ROW EXECUTE FUNCTION fn_chunk_tsv_update();

-- GIN 인덱스 (전문 검색 최적화)
CREATE INDEX IF NOT EXISTS idx_chunk_tsv ON document_chunk USING gin(content_tsv);
