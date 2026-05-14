"""비업무시간대 구 청크 제거 — '탐지 기준 (핵심)' 추가 전 버전 삭제."""
import asyncio
import asyncpg
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main():
    dsn = os.environ.get("DATABASE_URL", "postgresql://playground:playground@localhost:5432/playground")
    conn = await asyncpg.connect(dsn)

    # 새 내용에는 '탐지 기준 (핵심)'이 있고, 구 내용에는 없음
    result = await conn.execute(
        "DELETE FROM document_chunk "
        "WHERE document_title = $1 AND content NOT LIKE $2",
        "내부감사 부정탐지 — 비업무시간대 거래",
        "%탐지 기준%",
    )
    print(f"삭제: {result}")

    rows = await conn.fetch(
        "SELECT content FROM document_chunk WHERE document_title = $1",
        "내부감사 부정탐지 — 비업무시간대 거래",
    )
    print(f"남은 청크: {len(rows)}개")
    for r in rows:
        print(f"  {r['content'][:80]}…")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
