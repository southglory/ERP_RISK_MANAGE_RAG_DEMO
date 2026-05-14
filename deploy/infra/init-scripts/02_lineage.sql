-- 6-table lineage schema: audit_case → answer → rule_invocation → evidence_chunk → source_transaction → decision_attribution

CREATE TABLE IF NOT EXISTS audit_case (
  case_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trace_id         TEXT NOT NULL,
  user_id          TEXT NOT NULL DEFAULT 'system',
  case_type        TEXT NOT NULL CHECK (case_type IN ('revenue_recognition','tax_risk','fraud_detection','contract_review')),
  question         TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS answer (
  answer_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id          UUID NOT NULL REFERENCES audit_case(case_id) ON DELETE CASCADE,
  text             TEXT NOT NULL,
  decision         TEXT CHECK (decision IN ('approve','reject','escalate')),
  confidence       NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
  decided_by       TEXT NOT NULL CHECK (decided_by IN ('rule_engine','llm','hybrid')),
  human_override   BOOLEAN NOT NULL DEFAULT FALSE,
  human_reviewer   TEXT,
  human_note       TEXT,
  model_id         TEXT NOT NULL,
  prompt_hash      TEXT NOT NULL,
  prompt_version   TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rule_invocation (
  invocation_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_id        UUID NOT NULL REFERENCES answer(answer_id) ON DELETE CASCADE,
  rule_set         TEXT NOT NULL CHECK (rule_set IN ('kifrs_1115','vat_korea','fraud_redflag','contract_clauses')),
  rule_id          TEXT NOT NULL,
  rule_version     TEXT NOT NULL DEFAULT '1.0',
  kifrs_step       SMALLINT CHECK (kifrs_step BETWEEN 1 AND 5),
  fired            BOOLEAN NOT NULL,
  matched_inputs   JSONB NOT NULL DEFAULT '{}',
  output           JSONB NOT NULL DEFAULT '{}',
  weight_in_decision NUMERIC(4,3) CHECK (weight_in_decision BETWEEN 0 AND 1),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence_chunk (
  evidence_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_id        UUID NOT NULL REFERENCES answer(answer_id) ON DELETE CASCADE,
  source_type      TEXT NOT NULL CHECK (source_type IN ('kifrs_standard','court_precedent','tax_law','internal_contract')),
  source_doc_id    TEXT NOT NULL,
  chunk_id         TEXT NOT NULL,
  span_start       INT,
  span_end         INT,
  retrieval_score  NUMERIC(6,4),
  rerank_score     NUMERIC(6,4),
  rank             SMALLINT NOT NULL,
  used_in_prompt   BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS source_transaction (
  link_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_id        UUID NOT NULL REFERENCES answer(answer_id) ON DELETE CASCADE,
  erp_table        TEXT NOT NULL CHECK (erp_table IN ('gl_journal','ar_invoice','tax_invoice','purchase_invoice','stock_entry')),
  erp_row_pk       TEXT NOT NULL,
  fiscal_period    TEXT NOT NULL,
  amount           NUMERIC(18,2),
  account_code     TEXT,
  contribution     TEXT CHECK (contribution IN ('evidence','flagged','baseline'))
);

CREATE TABLE IF NOT EXISTS decision_attribution (
  attribution_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_id        UUID NOT NULL REFERENCES answer(answer_id) ON DELETE CASCADE UNIQUE,
  rule_weight      NUMERIC(4,3) NOT NULL CHECK (rule_weight BETWEEN 0 AND 1),
  llm_weight       NUMERIC(4,3) NOT NULL CHECK (llm_weight BETWEEN 0 AND 1),
  rationale        TEXT,
  conflict_flag    BOOLEAN NOT NULL DEFAULT FALSE,
  CONSTRAINT weights_sum CHECK (ABS(rule_weight + llm_weight - 1.0) < 0.001)
);

-- Vector chunks table (for pgvector hybrid search)
CREATE TABLE IF NOT EXISTS document_chunk (
  chunk_id         TEXT PRIMARY KEY,
  source_type      TEXT NOT NULL,
  source_doc_id    TEXT NOT NULL,
  document_title   TEXT NOT NULL DEFAULT '',
  content          TEXT NOT NULL,
  span_start       INT,
  span_end         INT,
  dense_vec        vector(1024),
  sparse_tokens    JSONB,
  metadata         JSONB NOT NULL DEFAULT '{}',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_answer_case ON answer(case_id);
CREATE INDEX IF NOT EXISTS idx_rule_answer ON rule_invocation(answer_id, fired);
CREATE INDEX IF NOT EXISTS idx_evidence_answer ON evidence_chunk(answer_id, rank);
CREATE INDEX IF NOT EXISTS idx_source_answer ON source_transaction(answer_id);
CREATE INDEX IF NOT EXISTS idx_case_trace ON audit_case(trace_id);
CREATE INDEX IF NOT EXISTS idx_chunk_source ON document_chunk(source_type, source_doc_id);
CREATE INDEX IF NOT EXISTS idx_chunk_dense ON document_chunk USING hnsw (dense_vec vector_cosine_ops) WITH (m = 16, ef_construction = 64);
