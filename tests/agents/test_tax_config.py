from decimal import Decimal
from core.agents.tax_config import load_tax_config


def test_load_returns_account_rules():
    cfg = load_tax_config()
    wh001 = next(r for r in cfg.account_rules if r.rule_id == "WH-001")
    assert wh001.account_prefixes == {"521", "522", "523"}
    assert wh001.min_amount == Decimal("330000")
    assert wh001.severity == "medium"


def test_load_returns_cutoff():
    cfg = load_tax_config()
    assert cfg.cutoff.day_threshold == 25
    assert "521" in cfg.cutoff.account_prefixes


def test_load_returns_vendor_rules():
    cfg = load_tax_config()
    overseas = next(r for r in cfg.vendor_rules if r.vendor_type == "overseas")
    assert overseas.rule_id == "VEN-001"
    assert overseas.severity == "high"


def test_flag_to_query_has_all_rules():
    cfg = load_tax_config()
    for k in ["WH-001", "WH-002", "VAT-001", "CUT-001", "VEN-001", "VEN-002"]:
        assert k in cfg.flag_to_query
