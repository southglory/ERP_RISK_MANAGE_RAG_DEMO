"""explanation DTO sanity check."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg

from core.agents.explanation import load_case_explanation


async def main():
    dsn = os.environ.get("DATABASE_URL", "postgresql://playground:playground@localhost:5432/playground")
    conn = await asyncpg.connect(dsn)
    row = await conn.fetchrow("SELECT case_id::text AS cid FROM audit_case ORDER BY created_at DESC LIMIT 1")
    await conn.close()
    if not row:
        print("no case found"); return
    exp = await load_case_explanation(row["cid"])
    print(f"case_id={exp.case_id}")
    print(f"decision={exp.decision} confidence={exp.confidence:.2f}")
    print(f"rules={len(exp.rules)}  (sample weights: {[round(r.weight, 2) for r in exp.rules[:3]]})")
    print(f"txns={len(exp.txns)}   (sample ids: {[t.erp_row_pk for t in exp.txns[:5]]})")


if __name__ == "__main__":
    asyncio.run(main())
