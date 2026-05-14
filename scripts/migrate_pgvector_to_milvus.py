"""pgvector document_chunk → Milvus erp_risk_chunks 일괄 이주.

사용:
    python scripts/migrate_pgvector_to_milvus.py
환경:
    DATABASE_URL  (pgvector 출처)
    MILVUS_HOST   (기본 localhost)
"""

from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=False)

import asyncpg

from core.providers.base import Document
from core.providers.vectorstore.milvus_store import MilvusVectorStore


async def main() -> None:
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://playground:playground@localhost:5432/playground",
    )
    pg = await asyncpg.connect(dsn)
    try:
        rows = await pg.fetch("""
            SELECT chunk_id, source_type, source_doc_id, document_title, content,
                   span_start, span_end, dense_vec::text AS vec_text, metadata
            FROM document_chunk
            WHERE dense_vec IS NOT NULL
        """)
    finally:
        await pg.close()

    print(f"[migrate] pgvector 청크 {len(rows)}건 로드")

    store = MilvusVectorStore()
    await store.ensure_collection()
    try:
        ok = 0
        for r in rows:
            vec = [float(x) for x in r["vec_text"].strip("[]").split(",")]
            md_raw = r["metadata"]
            md = md_raw if isinstance(md_raw, dict) else json.loads(md_raw or "{}")
            await store.upsert(Document(
                chunk_id=r["chunk_id"],
                source_type=r["source_type"],
                source_doc_id=r["source_doc_id"],
                document_title=r["document_title"] or "",
                content=r["content"],
                dense_vec=vec,
                sparse_tokens={},
                metadata=md,
                span_start=r["span_start"],
                span_end=r["span_end"],
            ))
            ok += 1
            if ok % 25 == 0:
                print(f"  {ok}/{len(rows)}")
        await store.flush()
        print(f"[migrate] 완료: {ok}건 Milvus 이주")
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
