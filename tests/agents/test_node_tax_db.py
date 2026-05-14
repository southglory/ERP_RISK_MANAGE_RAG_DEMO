"""Phase 6C node_tax(DB+YAML)가 Phase 6B 와 동일한 플래그를 내놓는지 확인."""

import pytest

from data.fixtures.erp_transactions import SAMPLE_TRANSACTIONS
from core.agents.risk_graph import node_tax_async
from core.agents.vendor_repo import reset_cache


EXPECTED_FLAG_SET = {
    ("WH-001", "T003"),
    ("WH-001", "T004"),
    ("VAT-001", "T005"),
    ("VAT-001", "T016"),
    ("WH-002", "T009"),
    ("CUT-001", "T016"),
    ("CUT-001", "T017"),
    ("CUT-001", "T018"),
    ("VEN-001", "T009"),
    ("VEN-002", "T010"),
}


@pytest.mark.asyncio
async def test_node_tax_matches_phase6b_baseline():
    reset_cache()
    state = {"transactions": [t.model_dump(mode="json") for t in SAMPLE_TRANSACTIONS]}
    out = await node_tax_async(state)
    pairs = {(f["rule"], f["txn_ids"][0]) for f in out["tax_flags"]}
    assert pairs == EXPECTED_FLAG_SET, f"diff: {pairs ^ EXPECTED_FLAG_SET}"


@pytest.mark.asyncio
async def test_summary_lists_all_rules():
    reset_cache()
    state = {"transactions": [t.model_dump(mode="json") for t in SAMPLE_TRANSACTIONS]}
    out = await node_tax_async(state)
    for rule in ["WH-001", "WH-002", "VAT-001", "CUT-001", "VEN-001", "VEN-002"]:
        assert rule in out["tax_summary"]
