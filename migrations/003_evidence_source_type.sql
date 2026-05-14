-- migrations/003_evidence_source_type.sql
-- evidence_chunk.source_type CHECK 를 document_chunk.source_type 의 실제 값과 일치하도록 확장
-- 기존: 'kifrs_standard','court_precedent','tax_law','internal_contract'
-- 추가: 'court','ruling','contract','internal' (document_chunk 에 실제로 들어있는 값)

ALTER TABLE evidence_chunk DROP CONSTRAINT IF EXISTS evidence_chunk_source_type_check;
ALTER TABLE evidence_chunk
  ADD CONSTRAINT evidence_chunk_source_type_check
  CHECK (source_type IN (
    'kifrs_standard', 'court_precedent', 'tax_law', 'internal_contract',
    'court', 'ruling', 'contract', 'internal'
  ));
