import asyncio
import json

import httpx

from crawler import mcp_server as ms
from crawler.fetch import Fetcher
from tests.test_crawler import handler


def scan(tmp_path, **kw):
    async def go():
        f = Fetcher(cache_dir=tmp_path / "c", delay=0, transport=httpx.MockTransport(handler))
        try:
            return await ms.do_scan(fetcher=f, today="2026-10-23", **kw)
        finally:
            await f.aclose()
    return asyncio.run(go())


def test_scan_bounded_and_not_persisted(tmp_path):
    r = scan(tmp_path, max_items=1000)
    assert len(r["leads"]) <= ms.MAX_ITEMS_CAP
    assert set(r["report"]) <= set(ms.SCAN_SOURCES)
    assert not (tmp_path / "data").exists()
    r2 = scan(tmp_path, query="pay tariff bitcoin", sources=["hackernews"], max_items=1)
    assert len(r2["leads"]) <= 1 and list(r2["report"]) == ["hackernews"]


def test_scan_rejects_unsafe_sources(tmp_path):
    assert "error" in scan(tmp_path, sources=["reddit"])
    assert "error" in scan(tmp_path, sources=["x"])


def test_digest_and_leads(tmp_path):
    (tmp_path / "digests").mkdir()
    (tmp_path / "digests" / "2026-10-22.md").write_text("old")
    (tmp_path / "digests" / "2026-10-23.md").write_text("new")
    assert ms.read_digest(root=tmp_path) == "new"
    assert ms.read_digest("2026-10-22", root=tmp_path) == "old"
    assert "Invalid" in ms.read_digest("../etc/passwd", root=tmp_path)
    (tmp_path / "data").mkdir()
    rows = [{"id": str(i), "score": s} for i, s in enumerate([10, 90, 50])]
    (tmp_path / "data" / "leads.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n")
    got = ms.read_leads(min_score=40, limit=1, root=tmp_path)
    assert [l["score"] for l in got] == [90]


def test_match_suppliers_never_quotes_rates():
    r = ms.supplier_programs("8471.30.0100")
    assert "check HTS" in r["rate_info"] and "hts.usitc.gov" in r["hts_lookup"]
    assert "transshipment" in r["compliance_caveat"] and "GENUINE" in r["compliance_caveat"]
    names = " ".join(p["program"] for p in r["programs"])
    for k in ("USMCA", "FTA", "AGOA", "Foreign-Trade Zones", "drawback"):
        assert k in names
    assert "%" not in json.dumps(r["programs"]).replace("99%", "")
    assert "error" in ms.supplier_programs("abc")


def test_tools_registered_read_only():
    tools = asyncio.run(ms.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {"scan_leads", "get_digest", "list_leads", "match_suppliers", "landed_cost", "compare_plan", "space_launch_cost"}
    assert all(t.annotations.read_only_hint for t in tools)
