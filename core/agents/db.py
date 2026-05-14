"""Phase 6C — risk agent용 asyncpg connection pool 싱글톤."""

from __future__ import annotations

import asyncio
import os
import asyncpg

_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None


async def get_pool() -> asyncpg.Pool:
    """프로세스 단위 풀. 이벤트 루프가 바뀌면(테스트마다 새 루프 등) 자동 재생성한다."""
    global _pool, _pool_loop
    loop = asyncio.get_running_loop()
    if _pool is None or _pool._closed or _pool_loop is not loop:
        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql://playground:playground@localhost:5432/playground",
        )
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
        _pool_loop = loop
    return _pool


async def close_pool() -> None:
    global _pool, _pool_loop
    if _pool is not None and not _pool._closed:
        await _pool.close()
    _pool = None
    _pool_loop = None
