"""data/fixtures/vendor_master.py 의 VENDOR_MASTER 를 vendor 테이블에 INSERT한다."""

import asyncio
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import asyncpg

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.fixtures.vendor_master import VENDOR_MASTER


async def main() -> None:
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://playground:playground@localhost:5432/playground",
    )
    conn = await asyncpg.connect(dsn)
    inserted = 0
    for vendor_id, info in VENDOR_MASTER.items():
        await conn.execute(
            """
            INSERT INTO vendor (vendor_id, name, vendor_type, country)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (vendor_id) DO UPDATE
              SET name = EXCLUDED.name,
                  vendor_type = EXCLUDED.vendor_type,
                  country = EXCLUDED.country
            """,
            vendor_id,
            info.get("name", vendor_id),
            info["type"],
            info.get("country"),
        )
        inserted += 1
    rows = await conn.fetch("SELECT COUNT(*) FROM vendor")
    print(f"upserted={inserted}, total_rows={rows[0][0]}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
