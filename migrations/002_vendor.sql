-- migrations/002_vendor.sql — Phase 6C: 거래처 마스터 테이블

CREATE TABLE IF NOT EXISTS vendor (
  vendor_id   TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  vendor_type TEXT NOT NULL CHECK (vendor_type IN ('domestic','overseas','unregistered')),
  country     TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vendor_type ON vendor(vendor_type);
