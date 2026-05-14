"""Phase 5 — Ragas 평가 파이프라인.

사용법:
  python scripts/eval_ragas.py --dry-run        # 서비스 없이 골든셋 구조만 출력
  python scripts/eval_ragas.py                  # 전체 실행 (vLLM + infinity-emb + pgvector 필요)
  python scripts/eval_ragas.py --domain tax_risk  # 특정 도메인만 평가

메트릭:
  faithfulness       : 답변이 검색된 컨텍스트에만 근거하는가 (0~1)
  answer_relevancy   : 답변이 질문에 얼마나 관련 있는가 (0~1)
  context_precision  : 검색된 컨텍스트가 정답에 관련 있는가 (0~1)
  context_recall     : ground_truth를 커버하는 컨텍스트 비율 (0~1)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── 상수 ──────────────────────────────────────────────────────────────────────

VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
VLLM_MODEL    = os.environ.get("VLLM_MODEL",    "solar-10.7b-instruct")
EMBED_BASE_URL= os.environ.get("EMBED_BASE_URL", "http://localhost:8001")
EMBED_MODEL   = os.environ.get("EMBED_MODEL",    "BAAI/bge-m3")


# ── 골든셋 로드 ───────────────────────────────────────────────────────────────

def load_golden_qa(domain: str | None = None) -> list[dict]:
    from data.golden_qa import GOLDEN_QA
    if domain:
        return [q for q in GOLDEN_QA if q["domain"] == domain]
    return GOLDEN_QA


# ── RAG 파이프라인 실행 ───────────────────────────────────────────────────────

async def run_rag_on_question(question: str, pipeline) -> tuple[str, list[str]]:
    """질문에 대해 RAG 파이프라인을 실행하고 (answer, contexts) 반환."""
    from core.rag.models import RAGQuery, RAGMode
    result = await pipeline.run(RAGQuery(query=question, top_k=5, mode=RAGMode.RERANK))
    contexts = [c.content for c in result.chunks]
    return result.answer, contexts


async def collect_rag_results(golden_qa: list[dict]) -> list[dict]:
    """골든셋 전체에 대해 RAG를 실행해 answer + contexts를 수집한다."""
    from core.rag.pipeline import build_pipeline
    pipeline = build_pipeline()

    rows: list[dict] = []
    total = len(golden_qa)
    for i, item in enumerate(golden_qa, 1):
        print(f"  [{i:2d}/{total}] {item['id']} - {item['question'][:45]}...", end=" ", flush=True)
        t0 = time.time()
        try:
            answer, contexts = await run_rag_on_question(item["question"], pipeline)
            elapsed = time.time() - t0
            print(f"({elapsed:.1f}s) OK")
        except Exception as e:
            print(f"오류: {e}")
            answer  = ""
            contexts = []
        rows.append({
            "id":           item["id"],
            "domain":       item["domain"],
            "question":     item["question"],
            "answer":       answer,
            "contexts":     contexts,
            "ground_truth": item["ground_truth"],
            "keywords":     item.get("keywords", []),
        })
    return rows


# ── Ragas 평가 ────────────────────────────────────────────────────────────────

def build_ragas_config():
    """Ragas용 LLM / Embeddings 설정 (Solar vLLM 로컬)."""
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper

    llm = ChatOpenAI(
        base_url=VLLM_BASE_URL,
        api_key="local",
        model=VLLM_MODEL,
        temperature=0,
        max_tokens=512,
    )
    # OpenAI 클라이언트가 base_url에 /v1을 자동 추가 → base_url은 호스트만
    emb = OpenAIEmbeddings(
        base_url=EMBED_BASE_URL,
        api_key="local",
        model=EMBED_MODEL,
    )
    return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(emb)


def ragas_result_to_dict(result) -> dict:
    """EvaluationResult → 메트릭 평균 dict 변환 (ragas 버전 무관)."""
    try:
        import pandas as pd
        df = result.to_pandas()
        # 수치형 컬럼만 — ragas 버전마다 비수치 컬럼 이름이 다름
        metric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        return {c: float(df[c].mean(skipna=True)) for c in metric_cols}
    except Exception:
        pass
    # fallback: ragas 0.1.x
    try:
        return dict(result)
    except Exception:
        pass
    return {}


def run_ragas_eval(rows: list[dict]) -> dict:
    """Ragas evaluate() 실행 → 메트릭 dict 반환."""
    import warnings
    warnings.filterwarnings("ignore")

    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import Faithfulness, ContextPrecision, ContextRecall

    ragas_llm, ragas_emb = build_ragas_config()

    # AnswerRelevancy 제외 — Solar vLLM + infinity-emb 조합에서 token-ID 버그 발생
    metrics = [
        Faithfulness(llm=ragas_llm),
        ContextPrecision(llm=ragas_llm),
        ContextRecall(llm=ragas_llm),
    ]

    dataset = Dataset.from_dict({
        "question":     [r["question"]     for r in rows],
        "answer":       [r["answer"]       for r in rows],
        "contexts":     [r["contexts"]     for r in rows],
        "ground_truth": [r["ground_truth"] for r in rows],
    })

    try:
        result = evaluate(dataset, metrics=metrics, raise_exceptions=False)
    except TypeError:
        result = evaluate(dataset, metrics=metrics)
    return ragas_result_to_dict(result)


# ── 키워드 기반 폴백 평가 ─────────────────────────────────────────────────────

def keyword_score(answer: str, keywords: list[str]) -> float:
    """answer에 keywords가 몇 개 포함됐는지 비율로 반환 (0~1).

    공백 정규화: "주된 책임" == "주된책임" 처럼 공백 유무 차이를 측정 버그로 보고 무시.
    """
    if not keywords:
        return 1.0
    a_lower = answer.lower()
    a_nospace = a_lower.replace(" ", "")

    def _match(kw: str) -> bool:
        kw_lower = kw.lower()
        return kw_lower in a_lower or kw_lower.replace(" ", "") in a_nospace

    hit = sum(1 for kw in keywords if _match(kw))
    return hit / len(keywords)


def run_keyword_eval(rows: list[dict]) -> list[dict]:
    """Ragas 없이 키워드 매칭 기반 간이 평가."""
    results = []
    for r in rows:
        score = keyword_score(r["answer"], r["keywords"])
        results.append({
            "id":       r["id"],
            "domain":   r["domain"],
            "score":    score,
            "hit":      int(score * len(r["keywords"])),
            "total":    len(r["keywords"]),
            "keywords": r["keywords"],
            "answer_preview": r["answer"][:120],
        })
    return results


# ── 결과 저장 ─────────────────────────────────────────────────────────────────

def save_results(rows: list[dict], ragas_result, out_dir: str = "results") -> str:
    Path(out_dir).mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"{out_dir}/ragas_eval_{ts}.json"

    payload = {
        "timestamp": ts,
        "n_samples": len(rows),
        "ragas_scores": dict(ragas_result) if ragas_result else None,
        "rows": rows,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


# ── 출력 ─────────────────────────────────────────────────────────────────────

def print_summary(rows: list[dict], ragas_result=None, keyword_results=None) -> None:
    domains = ["revenue_recognition", "tax_risk", "fraud_detection", "contract_review"]
    domain_labels = {
        "revenue_recognition": "수익인식",
        "tax_risk":            "세무 리스크",
        "fraud_detection":     "부정 탐지",
        "contract_review":     "계약/판례",
    }

    print("\n" + "=" * 65)
    print("  Ragas 평가 결과")
    print("=" * 65)

    if ragas_result:
        # ragas_result is either a plain dict (from run_ragas_eval) or raw EvaluationResult
        if not isinstance(ragas_result, dict):
            from scripts.eval_ragas import ragas_result_to_dict
            scores = ragas_result_to_dict(ragas_result)
        else:
            scores = ragas_result
        for key in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
            if key in scores:
                print(f"  {key:<22}: {scores[key]:.3f}")
        valid = [v for v in scores.values() if v == v]  # filter NaN
        if valid:
            avg = sum(valid) / len(valid)
            print(f"  ---------------------------------")
            print(f"  평균               : {avg:.3f}")
    else:
        print("  (Ragas 평가 미실행 - 키워드 폴백 결과)")

    if keyword_results:
        print("\n  도메인별 키워드 매칭:")
        for d in domains:
            d_rows = [r for r in keyword_results if r["domain"] == d]
            if not d_rows:
                continue
            avg_score = sum(r["score"] for r in d_rows) / len(d_rows)
            label = domain_labels.get(d, d)
            bar_fill = int(avg_score * 20)
            bar = "#" * bar_fill + "." * (20 - bar_fill)
            print(f"  {label:<12} [{bar}] {avg_score:.0%}  ({len(d_rows)})")

        # 개별 실패 항목
        fails = [r for r in keyword_results if r["score"] < 0.5]
        if fails:
            print(f"\n  키워드 매칭 < 50% 항목 ({len(fails)}개):")
            for r in fails:
                print(f"    [{r['id']}] score={r['score']:.0%}  미포함={[kw for kw in r['keywords'] if kw.lower() not in r['answer_preview'].lower()]}")

    print("=" * 65)


def print_dry_run(golden_qa: list[dict]) -> None:
    from data.golden_qa import DOMAIN_COUNTS
    print("\n골든셋 구조 (dry-run)")
    print("=" * 55)
    print(f"  전체 QA 수: {len(golden_qa)}")
    for d, cnt in DOMAIN_COUNTS.items():
        print(f"  {d:<25}: {cnt}개")
    print()
    for item in golden_qa:
        print(f"  [{item['id']}] {item['question'][:55]}")
        print(f"        키워드: {item['keywords']}")
    print("=" * 55)
    print("  실제 평가를 실행하려면: python scripts/eval_ragas.py")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Ragas 평가 파이프라인")
    p.add_argument("--dry-run",  action="store_true", help="RAG/LLM 없이 골든셋 구조만 출력")
    p.add_argument("--keyword",  action="store_true", help="키워드 매칭 폴백 평가만 실행 (서비스 불필요)")
    p.add_argument("--no-ragas", action="store_true", help="RAG 실행은 하되 Ragas 메트릭 건너뜀")
    p.add_argument("--domain",   type=str, default=None,
                   help="평가 도메인 (revenue_recognition|tax_risk|fraud_detection|contract_review)")
    p.add_argument("--limit",    type=int, default=None, help="평가 샘플 수 제한")
    return p.parse_args()


async def main():
    args = parse_args()
    golden_qa = load_golden_qa(args.domain)
    if args.limit:
        golden_qa = golden_qa[:args.limit]

    if args.dry_run:
        print_dry_run(golden_qa)
        return

    print(f"\nRAG 파이프라인 실행 중 ({len(golden_qa)}개 질문)…\n")
    rows = await collect_rag_results(golden_qa)

    # 키워드 폴백 (항상 계산)
    kw_results = run_keyword_eval(rows)

    ragas_result = None
    if not args.no_ragas and not args.keyword:
        print("\nRagas 메트릭 계산 중…")
        try:
            ragas_result = run_ragas_eval(rows)
        except Exception as e:
            print(f"  Ragas 오류: {e}\n  → 키워드 폴백으로 전환")

    print_summary(rows, ragas_result, kw_results)

    out_path = save_results(rows, ragas_result)
    print(f"\n  결과 저장: {out_path}\n")


if __name__ == "__main__":
    asyncio.run(main())
