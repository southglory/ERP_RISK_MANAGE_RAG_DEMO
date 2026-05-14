"""Phase 6C — vendor DB 조회 + 인메모리 캐시.

부정탐지 그래프 한 회차당 같은 vendor를 여러 번 조회하므로 캐시가 효과적이다.
캐시는 프로세스 단위이고, 갱신은 reset_cache()로 명시적으로 한다.
"""

from __future__ import annotations

from .db import get_pool

_cache: dict[str, dict | None] = {}


def reset_cache() -> None:
    _cache.clear()


async def lookup_vendor(vendor_id: str) -> dict | None:
    if vendor_id in _cache:
        return _cache[vendor_id]
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT vendor_id, name, vendor_type, country FROM vendor WHERE vendor_id = $1",
            vendor_id,
        )
    info = None if row is None else {
        "vendor_id": row["vendor_id"],
        "name":      row["name"],
        "type":      row["vendor_type"],
        "country":   row["country"],
    }
    _cache[vendor_id] = info
    return info
