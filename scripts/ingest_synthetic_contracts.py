"""Phase 3-1-5 — 합성 계약 100건을 BGE-M3 임베딩 후 pgvector 에 적재.

source_type='contract' 로 인제스트.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=False)

from core.providers.base import Document
from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider
from core.providers.vectorstore.factory import get_vector_store
from data.fixtures.synthetic_contracts import generate

BATCH = 16


def _chunk_id(contract_id: str, content: str) -> str:
    h = hashlib.md5(content.encode("utf-8")).hexdigest()[:8]
    return f"synth_contract_{contract_id}_{h}"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    contracts = generate(args.n, seed=args.seed)
    print(f"[contracts] {len(contracts)} 합성 계약 생성")

    # 임베딩 (batch)
    emb = InfinityEmbeddingProvider()
    texts = [c.text for c in contracts]
    all_vecs: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i: i + BATCH]
        vecs = await emb.embed(batch)
        all_vecs.extend(vecs)
        print(f"  embed {min(i + BATCH, len(texts))}/{len(texts)}")

    # 적재
    store = get_vector_store()
    try:
        for c, vec in zip(contracts, all_vecs):
            cid = _chunk_id(c.contract_id, c.text)
            metadata = {
                "contract_type":   c.contract_type,
                "revenue_basis":   c.revenue_basis,
                "recognition":     c.recognition,
                "party_a":         c.party_a,
                "party_b":         c.party_b,
                "amount":          c.amount,
                "contract_date":   c.contract_date,
            }
            await store.upsert(Document(
                chunk_id=cid,
                source_type="contract",
                source_doc_id=f"synth_contract_{c.contract_id}",
                document_title=f"합성 계약 {c.contract_id} ({c.contract_type})",
                content=c.text,
                dense_vec=vec,
                sparse_tokens={},
                metadata=metadata,
                span_start=0,
                span_end=len(c.text),
            ))
        print(f"[contracts] {len(contracts)} 청크 적재 완료 (source_type='contract')")
    finally:
        await store.close()

    # 라벨 분포 출력
    from collections import Counter
    type_counter = Counter(c.contract_type for c in contracts)
    basis_counter = Counter(c.revenue_basis for c in contracts)
    print(f"\n  contract_type 분포: {dict(type_counter)}")
    print(f"  revenue_basis 분포: {dict(basis_counter)}")


if __name__ == "__main__":
    asyncio.run(main())
