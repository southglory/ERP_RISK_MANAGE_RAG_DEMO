"""재무 부정탐지 공통 모델."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW    = "low"      # 정상
    MEDIUM = "medium"   # 주의
    HIGH   = "high"     # 경고
    CRITICAL = "critical"  # 즉시 검토


class FraudFlag(str, Enum):
    BENFORD_DEVIATION    = "benford_deviation"     # 벤포드 법칙 이탈
    ROUND_NUMBER_BIAS    = "round_number_bias"      # 라운드 넘버 편향
    DUPLICATE_TXN        = "duplicate_txn"          # 중복 거래
    VELOCITY_SPIKE       = "velocity_spike"         # 단기 과다 발생
    OFF_HOURS            = "off_hours"              # 비업무 시간대
    JUST_BELOW_THRESHOLD = "just_below_threshold"   # 한도 직하 분할
    SPLIT_PAYMENT        = "split_payment"          # 분산 결제
    UNUSUAL_AMOUNT       = "unusual_amount"         # 이상 금액 패턴


class Transaction(BaseModel):
    """분석 대상 거래 레코드."""
    txn_id: str
    txn_datetime: datetime
    amount: Decimal = Field(gt=0)
    vendor_id: str = ""
    account_code: str = ""
    posted_by: str = ""
    description: str = ""
    approver: str = ""


class FraudAlert(BaseModel):
    """단일 이상 탐지 결과."""
    flag: FraudFlag
    risk_level: RiskLevel
    txn_ids: list[str]           # 관련 거래 ID
    score: float = Field(ge=0.0, le=1.0)  # 0~1 위험도 점수
    detail: str = ""             # 사람이 읽을 수 있는 설명
    evidence: dict = Field(default_factory=dict)  # 수치 근거


class FraudReport(BaseModel):
    """전체 분석 보고서."""
    total_txns: int
    alerts: list[FraudAlert] = Field(default_factory=list)
    overall_risk: RiskLevel = RiskLevel.LOW
    summary: str = ""

    def compute_overall_risk(self) -> None:
        if not self.alerts:
            self.overall_risk = RiskLevel.LOW
            return
        max_score = max(a.score for a in self.alerts)
        if max_score >= 0.8:
            self.overall_risk = RiskLevel.CRITICAL
        elif max_score >= 0.6:
            self.overall_risk = RiskLevel.HIGH
        elif max_score >= 0.35:
            self.overall_risk = RiskLevel.MEDIUM
        else:
            self.overall_risk = RiskLevel.LOW
