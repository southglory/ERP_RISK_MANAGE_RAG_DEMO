"""골든셋 키워드 자기참조 검증 스크립트."""
import sys
sys.path.insert(0, ".")
from data.golden_qa import GOLDEN_QA
from scripts.eval_ragas import run_keyword_eval

rows = [
    {
        "id": q["id"], "domain": q["domain"], "question": q["question"],
        "answer": q["ground_truth"], "contexts": [],
        "ground_truth": q["ground_truth"], "keywords": q.get("keywords", []),
    }
    for q in GOLDEN_QA
]
results = run_keyword_eval(rows)
scores = [r["score"] for r in results]
print(f"ground_truth 자기참조 점수: avg={sum(scores)/len(scores):.2%} min={min(scores):.2%}")

fails = [r for r in results if r["score"] < 1.0]
if fails:
    print("키워드 미포함 항목:")
    for f in fails:
        missing = [kw for kw in f["keywords"] if kw.lower() not in f["answer_preview"].lower()]
        print(f"  [{f['id']}] score={f['score']:.0%} missing={missing}")
else:
    print("모든 ground_truth 키워드 자기 포함 확인 OK")
