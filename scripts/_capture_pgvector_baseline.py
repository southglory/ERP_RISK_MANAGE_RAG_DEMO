"""현재 HybridRetriever 의 top-5 chunk_id 를 골든 쿼리 5개로 캡처해 frozen dict 출력.

리팩터 후의 결과를 frozen baseline 으로 잡아 회귀 가드로 쓴다.
"""

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=False)

from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider
from core.providers.reranker.infinity_reranker import InfinityRerankerProvider
from core.providers.vectorstore.pgvector_store import PgVectorStore
from core.rag.models import RAGMode, RAGQuery
from core.rag.retriever import HybridRetriever

QUERIES = [
    "부가가치세 신고기한은 언제인가",
    "원천징수 영수증 발급 의무",
    "법인세 중간예납 기한",
    "전자세금계산서 미발급 가산세",
    "해외법인 배당소득 원천징수 세율",
]


async def main() -> None:
    store = PgVectorStore()
    r = HybridRetriever(
        embedding=InfinityEmbeddingProvider(),
        reranker=InfinityRerankerProvider(),
        store=store,
    )
    try:
        baseline: dict[str, list[str]] = {}
        for q in QUERIES:
            out = await r.retrieve(RAGQuery(query=q, top_k=5, mode=RAGMode.HYBRID))
            baseline[q] = [c.chunk_id for c in out]
        out_path = _ROOT / "tests" / "providers" / "_pgvector_baseline.json"
        out_path.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"baseline written to {out_path}")
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
