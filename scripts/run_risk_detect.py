"""Phase 6A — ERP 리스크 탐지 에이전트 실행.

사용법:
  python scripts/run_risk_detect.py              # 샘플 픽스처, RAG 포함
  python scripts/run_risk_detect.py --no-rag     # 룰 탐지만 (RAG 서비스 불필요)
  python scripts/run_risk_detect.py --dry-run    # 픽스처 목록만 출력
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_args():
    p = argparse.ArgumentParser(description="ERP 리스크 탐지 에이전트")
    p.add_argument("--no-rag",   action="store_true", help="RAG 검색 건너뜀 (서비스 불필요)")
    p.add_argument("--dry-run",  action="store_true", help="픽스처 목록만 출력")
    return p.parse_args()


def main():
    args = parse_args()

    from data.fixtures.erp_transactions import SAMPLE_TRANSACTIONS

    if args.dry_run:
        print(f"\n샘플 거래 픽스처 ({len(SAMPLE_TRANSACTIONS)}건)")
        print("=" * 55)
        for t in SAMPLE_TRANSACTIONS:
            print(f"  [{t.txn_id}] {t.txn_datetime.strftime('%m/%d %H:%M')} "
                  f"{int(t.amount):>12,}원  {t.description[:25]}")
        print("=" * 55)
        return

    print(f"\n리스크 탐지 실행 중 ({len(SAMPLE_TRANSACTIONS)}건 거래)…")
    if args.no_rag:
        print("  (RAG 건너뜀 — 룰 탐지만)\n")

    from core.agents.risk_graph import run_risk_detect

    txn_dicts = [t.model_dump(mode="json") for t in SAMPLE_TRANSACTIONS]
    result = run_risk_detect(txn_dicts, skip_rag=args.no_rag)

    print()
    print(result["risk_report"])
    print()

    if result.get("rag_context") and not args.no_rag:
        print("─" * 55)
        print("법령 컨텍스트 (상위 500자):")
        print(result["rag_context"][:500])
        print()


if __name__ == "__main__":
    main()
