"""Phase 5-4 — 부정 탐지 confusion matrix.

합성 N건 (각 거래에 pattern 라벨) → FraudDetectionEngine 분석 → TP/FP/TN/FN + 패턴별 분해.
DoD: recall ≥ 0.9, precision ≥ 0.7.

사용:
    python scripts/fraud_confusion_matrix.py --n 1000
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from core.fraud.engine import FraudDetectionEngine
from core.fraud.models import FraudFlag, Transaction
from data.fixtures.erp_generator import FRAUD_POSITIVE_PATTERNS, generate

# Benford·Velocity 는 batch-level (그 batch 의 모든 거래에 라벨 박음) → 거래 단위 precision 측정 부적절.
# 거래 단위 precision 은 transaction-level flag 들만으로 계산.
TXN_LEVEL_FLAGS = {
    FraudFlag.ROUND_NUMBER_BIAS,
    FraudFlag.DUPLICATE_TXN,
    FraudFlag.OFF_HOURS,
    FraudFlag.JUST_BELOW_THRESHOLD,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    txns_raw = generate(args.n, seed=args.seed)
    txns = [Transaction(**{k: v for k, v in t.items() if k != "pattern"}) for t in txns_raw]
    patterns = {t["txn_id"]: t["pattern"] for t in txns_raw}

    engine = FraudDetectionEngine()
    report = engine.analyze(txns)
    flagged_ids = {
        tid for a in report.alerts if a.flag in TXN_LEVEL_FLAGS for tid in a.txn_ids
    }
    batch_level_alerts = [a.flag.value for a in report.alerts if a.flag not in TXN_LEVEL_FLAGS]

    tp = fp = tn = fn = 0
    by_pattern = defaultdict(lambda: {"tp": 0, "fn": 0, "total_actual_pos": 0,
                                       "fp": 0, "tn": 0, "total_actual_neg": 0})
    for tid, pattern in patterns.items():
        is_actual_pos = pattern in FRAUD_POSITIVE_PATTERNS
        is_predicted_pos = tid in flagged_ids
        if is_actual_pos:
            by_pattern[pattern]["total_actual_pos"] += 1
            if is_predicted_pos:
                tp += 1
                by_pattern[pattern]["tp"] += 1
            else:
                fn += 1
                by_pattern[pattern]["fn"] += 1
        else:
            by_pattern[pattern]["total_actual_neg"] += 1
            if is_predicted_pos:
                fp += 1
                by_pattern[pattern]["fp"] += 1
            else:
                tn += 1
                by_pattern[pattern]["tn"] += 1

    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    f1        = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0.0
    accuracy  = (tp + tn) / args.n

    print(f"=== 부정 탐지 confusion matrix (n={args.n}, seed={args.seed}) ===")
    print(f"  거래 단위 룰: {sorted(f.value for f in TXN_LEVEL_FLAGS)}")
    print(f"  batch 수준 alerts (precision 계산 제외): {batch_level_alerts}")
    print(f"  TP {tp:>5}   FP {fp:>5}   TN {tn:>5}   FN {fn:>5}")
    print(f"  recall    = TP/(TP+FN) = {recall:.3f}   (DoD ≥ 0.90)  {'PASS' if recall >= 0.9 else 'FAIL'}")
    print(f"  precision = TP/(TP+FP) = {precision:.3f}   (DoD ≥ 0.70)  {'PASS' if precision >= 0.7 else 'FAIL'}")
    print(f"  F1        = {f1:.3f}")
    print(f"  accuracy  = {accuracy:.3f}")

    print(f"\n  패턴별 분해 (positive 패턴):")
    print(f"    {'pattern':<22} {'TP':>5} {'FN':>5} {'recall':>8}")
    for p in sorted(FRAUD_POSITIVE_PATTERNS):
        c = by_pattern[p]
        r = c["tp"] / c["total_actual_pos"] if c["total_actual_pos"] > 0 else 0.0
        print(f"    {p:<22} {c['tp']:>5} {c['fn']:>5} {r:>8.3f}")

    print(f"\n  패턴별 분해 (negative 패턴):")
    print(f"    {'pattern':<22} {'TN':>5} {'FP':>5}")
    for p, c in sorted(by_pattern.items()):
        if p in FRAUD_POSITIVE_PATTERNS:
            continue
        print(f"    {p:<22} {c['tn']:>5} {c['fp']:>5}")

    out = {
        "n": args.n, "seed": args.seed,
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "recall": recall, "precision": precision, "f1": f1, "accuracy": accuracy,
        "by_pattern": {k: dict(v) for k, v in by_pattern.items()},
        "dod_recall_pass":    recall >= 0.9,
        "dod_precision_pass": precision >= 0.7,
    }
    Path("eval").mkdir(exist_ok=True)
    out_path = f"eval/fraud_confusion_matrix_{datetime.now().strftime('%Y%m%d')}.json"
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved -> {out_path}")


if __name__ == "__main__":
    main()
