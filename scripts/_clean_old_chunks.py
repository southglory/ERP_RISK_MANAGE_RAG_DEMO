"""구버전 청크 제거 — 제27조·B34-B38 업데이트 후 old 청크 삭제."""
import asyncio
import asyncpg
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main():
    dsn = os.environ.get(
        "DATABASE_URL", "postgresql://playground:playground@localhost:5432/playground"
    )
    conn = await asyncpg.connect(dsn)

    old_titles = [
        "K-IFRS 제1115호 제27조 — 수행의무 구별 기준",
        "K-IFRS 제1115호 B34-B38 — 본인-대리인 구별",
    ]

    for title in old_titles:
        result = await conn.execute(
            "DELETE FROM document_chunk WHERE document_title = $1", title
        )
        print(f"삭제 [{title[:40]}]: {result}")

    # 잔존 확인
    rows = await conn.fetch(
        "SELECT document_title, COUNT(*) AS cnt FROM document_chunk "
        "WHERE document_title LIKE '%27%' OR document_title LIKE '%B34%' "
        "GROUP BY document_title"
    )
    print("\n남은 관련 청크:")
    for row in rows:
        print(f"  {row['document_title'][:60]}  {row['cnt']}개")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
