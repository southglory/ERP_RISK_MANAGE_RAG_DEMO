"""저장된 RAG 결과로 Ragas 메트릭만 재실행.

인수 없이 실행하면 results/ 에서 가장 최근 ragas_eval_*.json 자동 선택.
사용: python scripts/_run_ragas_only.py [결과파일.json]
"""
import sys, json, warnings, glob, os
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

os.environ.setdefault("VLLM_BASE_URL", "http://localhost:8000/v1")
os.environ.setdefault("VLLM_MODEL",    "solar-10.7b-instruct")
os.environ.setdefault("EMBED_BASE_URL", "http://localhost:8001")
os.environ.setdefault("EMBED_MODEL",    "BAAI/bge-m3")

from scripts.eval_ragas import build_ragas_config, print_summary, run_keyword_eval, ragas_result_to_dict

# 파일 선택 — 인수 또는 최신 자동 감지
if len(sys.argv) > 1:
    result_file = sys.argv[1]
else:
    files = sorted(glob.glob("results/ragas_eval_*.json"))
    if not files:
        print("results/ragas_eval_*.json 파일 없음")
        sys.exit(1)
    result_file = files[-1]

print(f"로드: {result_file}")
with open(result_file, encoding="utf-8") as f:
    saved = json.load(f)

rows = saved["rows"]
print(f"rows: {len(rows)}")

# 컨텍스트 잘라내기 — Solar 4096 토큰 제한 대응
MAX_CTX_CHARS = 300
for r in rows:
    r["contexts"] = [c[:MAX_CTX_CHARS] for c in r["contexts"]]
print(f"context truncated to {MAX_CTX_CHARS} chars\n")

kw_results = run_keyword_eval(rows)

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import Faithfulness, ContextPrecision, ContextRecall

ragas_llm, _ragas_emb = build_ragas_config()
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

print("Ragas 평가 중 (Faithfulness / ContextPrecision / ContextRecall)...")
try:
    result = evaluate(dataset, metrics=metrics, raise_exceptions=False)
except TypeError:
    result = evaluate(dataset, metrics=metrics)

scores = ragas_result_to_dict(result)
print_summary(rows, scores if scores else None, kw_results)

print("\n[scores]")
print(json.dumps({k: round(float(v), 4) for k, v in scores.items()}, ensure_ascii=False, indent=2))
