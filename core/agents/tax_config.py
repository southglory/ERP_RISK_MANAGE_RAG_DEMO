"""Phase 6C — config/tax_rules.yaml 로더.

위치는 ERP_RISK_MANAGE/config/tax_rules.yaml (프로젝트 루트 기준).
환경변수 TAX_RULES_PATH 로 override 가능.
"""

from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class AccountRule(BaseModel):
    rule_id: str
    account_prefixes: set[str]
    min_amount: Decimal
    severity: str
    detail: str


class CutoffRule(BaseModel):
    rule_id: str = "CUT-001"
    day_threshold: int
    account_prefixes: set[str]
    severity: str


class VendorRule(BaseModel):
    rule_id: str
    vendor_type: str
    severity: str
    detail: str


class TaxConfig(BaseModel):
    account_rules: list[AccountRule]
    cutoff: CutoffRule
    vendor_rules: list[VendorRule]
    flag_to_query: dict[str, str] = Field(default_factory=dict)


def _default_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "tax_rules.yaml"


@lru_cache(maxsize=4)
def load_tax_config(path: str | None = None) -> TaxConfig:
    p = Path(path) if path else Path(os.environ.get("TAX_RULES_PATH") or _default_path())
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return TaxConfig(**raw)
