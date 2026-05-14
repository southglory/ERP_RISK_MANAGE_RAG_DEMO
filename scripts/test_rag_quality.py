"""RAG 품질 점검 — 입력/출력 쌍으로 한국어 여부·잘림·근거 인용 확인.

실행:
    python scripts/test_rag_quality.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass

_ROOT = __import__("pathlib").Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)


# ── 테스트 케이스 정의 ────────────────────────────────────────────────────────

@dataclass
class QACase:
    query: str
    source_types: list[str]
    must_contain: list[str]          # 답변에 반드시 포함돼야 할 키워드
    must_not_english: bool = True    # 영문 답변 금지 여부


CASES: list[QACase] = [
    QACase(
        query="SaaS 구독 서비스의 부가가치세 공급 시기는 언제인가요?",
        source_types=["tax_law", "ruling"],
        must_contain=["공급", "세금계산서"],
    ),
    QACase(
        query="미국 법인에 소프트웨어 라이선스 대가를 지급할 때 원천징수세율은?",
        source_types=["tax_law"],
        must_contain=["원천", "%"],
    ),
    QACase(
        query="소프트웨어 유지보수 계약에서 SLA 위반 시 위약금 감액 기준은?",
        source_types=["court", "contract"],
        must_contain=["위약금"],
    ),
    QACase(
        query="하도급 대금 지연이자율은 몇 퍼센트인가요?",
        source_types=["court", "contract"],
        must_contain=["15", "하도급"],
    ),
    QACase(
        query="K-IFRS 1115호 수익 인식 5단계를 설명해주세요.",
        source_types=["tax_law"],
        must_contain=["계약", "수행의무", "거래가격"],
    ),
    QACase(
        query="법인세법상 외국법인의 사용료 소득 원천징수세율은?",
        source_types=["tax_law"],
        must_contain=["20%", "사용료"],
    ),
    QACase(
        query="국세기본법상 납부지연 가산세 계산 방법은?",
        source_types=["tax_law"],
        must_contain=["가산세", "0.022"],
    ),
]


# ── 평가 함수 ─────────────────────────────────────────────────────────────────

def _is_korean(text: str) -> bool:
    korean_chars = len(re.findall(r"[가-힣]", text))
    total_alpha  = len(re.findall(r"[a-zA-Z가-힣]", text))
    if total_alpha == 0:
        return True
    return korean_chars / total_alpha > 0.5


def _is_cut_off(text: str) -> bool:
    text = text.strip()
    if not text:
        return True
    # 마침표·물음표·느낌표·괄호 닫기로 끝나지 않으면 잘린 것으로 간주
    return not re.search(r"[.!?\]）)。]\s*$", text)


def _has_citation(text: str) -> bool:
    return bool(re.search(r"\[\d+\]|각주|출처|참고", text))


def _evaluate(case: QACase, answer: str, latency_ms: int) -> dict:
    results = {
        "한국어 답변": _is_korean(answer) if case.must_not_english else True,
        "답변 잘림 없음": not _is_cut_off(answer),
        "근거 인용 존재": _has_citation(answer),
    }
    for kw in case.must_contain:
        results[f"키워드 '{kw}'"] = kw in answer
    return results


# ── 메인 ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    from core.rag.models import RAGQuery, RAGMode, SourceType
    from core.rag.pipeline import build_pipeline

    SOURCE_MAP = {
        "tax_law":  SourceType.TAX_LAW,
        "contract": SourceType.CONTRACT,
        "court":    SourceType.COURT,
        "ruling":   SourceType.RULING,
    }

    pipeline = build_pipeline()

    print("=" * 70)
    print("  RAG 품질 점검")
    print("=" * 70)

    total_checks = 0
    passed_checks = 0

    for i, case in enumerate(CASES, 1):
        print(f"\n[{i}/{len(CASES)}] {case.query}")
        print("-" * 60)

        try:
            source_types = [SOURCE_MAP[s] for s in case.source_types if s in SOURCE_MAP]
            query = RAGQuery(
                query=case.query,
                top_k=5,
                mode=RAGMode.RERANK,
                source_types=source_types or None,
            )
            result = await pipeline.run(query)
            answer = result.answer
            latency = result.latency_ms

            print(f"답변 ({latency}ms):")
            print(f"  {answer[:300].replace(chr(10), chr(10)+'  ')}")
            if len(answer) > 300:
                print("  ...")

            evals = _evaluate(case, answer, latency)
            print("\n평가:")
            for check, ok in evals.items():
                icon = "✅" if ok else "❌"
                print(f"  {icon} {check}")
                total_checks += 1
                if ok:
                    passed_checks += 1

        except Exception as e:
            print(f"  ❌ 오류: {e}")
            total_checks += 1

    print("\n" + "=" * 70)
    print(f"  결과: {passed_checks}/{total_checks} 통과")
    score = passed_checks / total_checks * 100 if total_checks else 0
    grade = "🟢 양호" if score >= 80 else "🟡 보통" if score >= 60 else "🔴 개선 필요"
    print(f"  점수: {score:.0f}%  {grade}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
