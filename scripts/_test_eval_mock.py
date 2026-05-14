"""eval_ragas 파이프라인 목 테스트 — RAG/LLM 없이 keyword 평가 전체 플로우 검증."""
import sys
sys.path.insert(0, ".")

from data.golden_qa import GOLDEN_QA
from scripts.eval_ragas import run_keyword_eval, print_summary, save_results

# ground_truth를 answer로 사용 (상한선 baseline)
rows = [
    {
        "id": q["id"], "domain": q["domain"], "question": q["question"],
        "answer": q["ground_truth"], "contexts": ["mock context"],
        "ground_truth": q["ground_truth"], "keywords": q.get("keywords", []),
    }
    for q in GOLDEN_QA
]

kw_results = run_keyword_eval(rows)
print_summary(rows, ragas_result=None, keyword_results=kw_results)

out = save_results(rows, None)
print(f"저장: {out}")
