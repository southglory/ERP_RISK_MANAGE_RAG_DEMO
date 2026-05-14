"""Phase 6D — 합성 거래 N건으로 risk_graph 회차 실행하고 결과 요약."""

import argparse
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# .env 자동 로딩
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"), override=False)
except Exception:
    pass

from data.fixtures.erp_generator import generate
from core.agents.risk_graph import run_risk_detect
from core.agents.tracing import flush_traces, get_metrics, langfuse_enabled, reset_metrics
from core.agents.vendor_repo import reset_cache


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-rag", action="store_true")
    args = ap.parse_args()

    reset_cache()
    reset_metrics()
    txns = generate(args.n, seed=args.seed)
    print(f"=== 합성 거래 {args.n}건 생성 (seed={args.seed}) ===")

    t0 = time.time()
    result = run_risk_detect(txns, skip_rag=args.no_rag)
    dt = time.time() - t0

    print(f"\n=== 결과 ===")
    print(f"  소요 시간: {dt:.2f}s ({args.n/dt:.1f} txn/s)")
    print(f"  통합 리스크: {result['overall_risk'].upper()}")
    print(f"  부정 경보: {len(result.get('fraud_alerts', []))}")
    print(f"  세무 플래그: {len(result.get('tax_flags', []))}")

    # 룰별 빈도
    from collections import Counter
    tax_counter = Counter(f["rule"] for f in result.get("tax_flags", []))
    print(f"\n  세무 룰별 빈도:")
    for rule, n in tax_counter.most_common():
        print(f"    {rule}: {n}건")

    print(f"\n  리포트 head:")
    for line in result.get('risk_report', '').split('\n')[:6]:
        print(f"    {line}")

    # 노드별 latency 표 — Langfuse 안 닿아도 우리 timer 가 측정해둠
    metrics = get_metrics()
    if metrics:
        print(f"\n  노드별 latency (timer 측정):")
        print(f"    {'노드':<18} {'avg(ms)':>10} {'total(ms)':>12} {'호출':>6}")
        for name, m in sorted(metrics.items(), key=lambda kv: -kv[1]["total_ms"]):
            print(f"    {name:<18} {m['avg_ms']:>10.2f} {m['total_ms']:>12.1f} {m['count']:>6}")

    if langfuse_enabled():
        print(f"\n  Langfuse trace flush (v4 OTLP timeout 가능)…")
        flush_traces()
        print(f"  -> http://localhost:3000 (trace_id={result.get('trace_id', '?')})")


if __name__ == "__main__":
    main()
