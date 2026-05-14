-- Migration: document_chunk 에 document_title 컬럼 추가
-- init-scripts 는 최초 컨테이너 기동 시에만 실행됨.
-- 이미 DB가 기동된 상태라면 아래 명령을 직접 실행:
--   docker exec -it <playground-db-container> psql -U playground -d playground -c \
--   "ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS document_title TEXT NOT NULL DEFAULT '';"

ALTER TABLE document_chunk
  ADD COLUMN IF NOT EXISTS document_title TEXT NOT NULL DEFAULT '';
