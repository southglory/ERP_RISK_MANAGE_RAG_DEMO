"""각 backend 로 동일 시뮬레이션 돌리고 결과 diff 출력.

사용:
    python scripts/compare_backends.py --n 20 --seed 42
"""

import argparse
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=False)

from core.agents.risk_graph import run_risk_detect
from core.agents.tracing import get_metrics, reset_metrics
from data.fixtures.erp_generator import generate


def _backend_run(backend: str, txns) -> dict:
    os.environ["RAG_VECTOR_BACKEND"] = backend
    reset_metrics()
    t0 = time.time()
    result = run_risk_detect(txns, skip_rag=False)
    elapsed = time.time() - t0
    return {
        "backend":   backend,
        "elapsed_s": round(elapsed, 2),
        "fraud":     len(result.get("fraud_alerts", [])),
        "tax":       len(result.get("tax_flags", [])),
        "metrics":   get_metrics(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    txns = generate(args.n, seed=args.seed)
    print(f"=== {args.n}건 생성, 두 backend 비교 (seed={args.seed}) ===")

    pg = _backend_run("pgvector", txns)
    mv = _backend_run("milvus",   txns)

    print()
    print(f"  metric           pgvector       milvus")
    print(f"  elapsed_s        {pg['elapsed_s']:>8}     {mv['elapsed_s']:>8}")
    print(f"  fraud_alerts     {pg['fraud']:>8}     {mv['fraud']:>8}")
    print(f"  tax_flags        {pg['tax']:>8}     {mv['tax']:>8}")

    pg_rag = pg["metrics"].get("node_rag", {}).get("avg_ms", 0)
    mv_rag = mv["metrics"].get("node_rag", {}).get("avg_ms", 0)
    pg_agg = pg["metrics"].get("node_aggregate", {}).get("avg_ms", 0)
    mv_agg = mv["metrics"].get("node_aggregate", {}).get("avg_ms", 0)
    print(f"  node_rag avg(ms) {pg_rag:>8.1f}     {mv_rag:>8.1f}")
    print(f"  node_agg avg(ms) {pg_agg:>8.1f}     {mv_agg:>8.1f}")

    same_rules = pg["fraud"] == mv["fraud"] and pg["tax"] == mv["tax"]
    print(f"\n  rule equivalence (fraud + tax counts): {'OK' if same_rules else 'DIFF'}")


if __name__ == "__main__":
    main()
