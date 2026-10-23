import gzip
import json
from pathlib import Path

import pytest

from crawler import landed_cost as lc
from crawler import mcp_server as ms

FIX = Path(__file__).parent / "fixtures" / "landed"


@pytest.fixture(autouse=True)
def fixture_data(monkeypatch):
    monkeypatch.setattr(lc, "DATA", FIX)
    for f in (lc.meta, lc.origins, lc.us_lines, lc.us_additional, lc.us_note52, lc.tariff_snapshot, lc.launch_prices):
        f.cache_clear()
    yield
    for f in (lc.meta, lc.origins, lc.us_lines, lc.us_additional, lc.us_note52, lc.tariff_snapshot, lc.launch_prices):
        f.cache_clear()


def route(r, o):
    return next(x for x in r["routes"] if x["origin"] == o)


def test_us_tshirts_ranking():
    r = lc.landed_cost("6109.10", "any", "US")
    mx, vn, bd, pt, cn = (route(r, o) for o in ("MX", "VN", "BD", "PT", "CN"))
    assert mx["best_line"]["program"].startswith("USMCA") and mx["best_line"]["duty_pct"] == 0
    assert mx["best_line"]["additional_pct"] == 10  # note 52 Mexico, exceptions flagged
    assert any("check source" in a for a in mx["best_line"]["additional"])
    assert vn["best_line"]["duty_pct"] == 16.5 and vn["best_line"]["additional_pct"] == 12.5
    assert bd["landed_min"] == 126.5
    assert pt["best_line"]["additional_pct"] == 0 and pt["landed_min"] == 116.5  # EU floor: 16.5 >= 10
    assert cn["best_line"]["additional_pct"] == 20  # 301 List 4A 7.5 + note 52 12.5, no double count
    totals = [x["landed_min"] for x in r["routes"]]
    assert totals == sorted(totals)
    assert route(r, "US")["domestic"]


def test_pt_and_uk_preferences_and_vat():
    pt = lc.landed_cost("6109100010", "VN", "PT")["routes"][0]
    assert pt["best_line"]["duty_pct"] == 0 and pt["best_line"]["vat_pct"] == 23.0 and pt["landed_min"] == 123.0
    cn = lc.landed_cost("6109100010", "CN", "PT")["routes"][0]
    assert cn["best_line"]["duty_pct"] == 12.0 and cn["landed_min"] == pytest.approx(137.76)
    dom = lc.landed_cost("6109", "PT", "PT")["routes"][0]
    assert dom["domestic"] and dom["best_line"]["import_duty"] == 0
    uk = lc.landed_cost("6109100010", "BD", "UK")["routes"][0]
    assert uk["best_line"]["duty_pct"] == 0 and "DCTS" in uk["best_line"]["program"]
    assert uk["best_line"]["vat_pct"] == 20.0 and "0%" in uk["best_line"]["vat_note"]
    us = lc.landed_cost("6109100010", "US", "UK")["routes"][0]
    assert us["best_line"]["duty_pct"] == 12.0


def test_cif_valuation_and_freight():
    r = lc.landed_cost("6109100010", "CN", "UK", value=100, freight=10, insurance=1)["routes"][0]
    b = r["best_line"]
    assert b["import_duty"] == round(111 * 0.12, 2)
    assert b["import_vat"] == round((111 + 13.32) * 0.20, 2)
    us = lc.landed_cost("6109.10", "VN", "US", value=100, freight=10)["routes"][0]["best_line"]
    assert us["import_duty"] == 29.0  # US duty on FOB value only


def test_unknowns_are_check_source_not_guessed():
    r = lc.landed_cost("6109.10", "ZZ", "US")["routes"][0]
    assert r["complete"] is False and "origin export duty" in r["best_line"]["missing"]
    eu = lc.landed_cost("6109100010", "VN", "EU")["routes"][0]["best_line"]
    assert eu["vat_pct"] == "check source" and eu["import_vat"] == "check source"
    missing = lc.landed_cost("9999", "VN", "UK")["routes"][0]
    assert "check source" in missing["status"]
    vn = lc.landed_cost("6109.10", "VN", "US")["routes"][0]
    assert vn["best_line"]["export_duty"] == "check source"


def test_section_232_not_stacked_with_note52():
    b = lc.landed_cost("7208.10.15", "VN", "US")["routes"][0]["best_line"]
    assert b["additional_pct"] == 50
    assert any("note 52 duty not applied" in a for a in b["additional"])
    gb = lc.landed_cost("7208.10.15", "GB", "US")["routes"][0]["best_line"]
    assert gb["additional_pct"] == 25  # UK-specific 232 rate replaces the ANY rate


def test_keyword_crypto_compliance_and_errors():
    m = lc.landed_cost("cotton t-shirts", "any", "UK")
    assert m["matches"][0]["hs6"] == "610910"
    r = lc.landed_cost("6109", "MX", "US", seller_accepts_crypto=True)
    assert r["crypto_filter"]["requested"] and "does not change duty" in r["crypto_filter"]["note"]
    assert any("Transshipment" in c for c in r["compliance"])
    assert any("Not legal" in c for c in r["compliance"])
    assert "error" in lc.landed_cost("6109", "VN", "JP")
    assert "error" in lc.landed_cost("61", "VN", "US")


def test_mcp_tool_registered():
    assert ms.landed_cost("6109.10", "VN", "GB")["destination"] == "UK"


def test_snapshot_parser_on_raw_api_fixture():
    import importlib.util
    spec = importlib.util.spec_from_file_location("b", Path(__file__).parent.parent / "tools" / "build_uk_xi_snapshot.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    raw = json.loads(gzip.decompress((FIX / "uk_6109100010_raw.json.gz").read_bytes()))
    c = b.parse_commodity(raw)
    assert c["code"] == "6109100010"
    assert any(m["type"] == "Third country duty" and m["duty"] == "12.00 %" for m in c["measures"])
    assert "PT" in c["areas"]["1013"]["members"]


def test_compare_plan_savings():
    r = lc.compare_plan("6109.10", "VN", "US", value=1000, qty=500, weight_kg=100)
    assert r["plan"]["origin"] == "VN" and r["plan"]["landed"] == 1290.0
    mx = next(a for a in r["alternatives"] if a["origin"] == "MX")
    assert mx["savings"] == 190.0 and mx["savings_pct"] == round(100 * 190 / 1290, 2)
    assert all("VN" != a["origin"] for a in r["alternatives"])
    assert "transshipment" in r["note"]


def test_space_route_published_prices_only():
    s = lc.space_route(100)
    sx = s["launch_options"][0]
    assert sx["provider"] == "SpaceX" and sx["launch_price_usd"] == 350000 + 50 * 7000
    assert sx["sources"] and sx["as_of"]
    assert any(o["launch_price_usd"] == "check source" for o in s["launch_options"])
    assert s["tariff"] == "none in orbit"
    assert any("ITAR" in n for n in s["notes"])
    assert lc.space_route(10)["launch_options"][0]["launch_price_usd"] == 350000  # 50 kg minimum block
    assert "check source" in lc.space_route(900)["launch_options"][0]["launch_price_usd"]
    assert lc.compare_plan("6109", "VN", "space", weight_kg=60)["destination"] == "SPACE"
