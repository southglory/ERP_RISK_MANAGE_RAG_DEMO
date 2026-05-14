"""새 청크가 올바르게 인제스트됐는지 확인."""
import asyncio
import asyncpg
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main():
    dsn = os.environ.get("DATABASE_URL", "postgresql://playground:playground@localhost:5432/playground")
    conn = await asyncpg.connect(dsn)

    for kw in ["비업무시간대", "전자상거래"]:
        rows = await conn.fetch(
            "SELECT document_title, content FROM document_chunk "
            "WHERE document_title LIKE $1 ORDER BY chunk_id",
            f"%{kw}%",
        )
        print(f"\n=== {kw} ({len(rows)}청크) ===")
        for r in rows:
            title = r["document_title"]
            content = r["content"]
            print(f"  [{title[:55]}]")
            print(f"  {content[:250]}")
            print()

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
