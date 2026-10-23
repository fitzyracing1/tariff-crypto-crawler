import asyncio
import json
from pathlib import Path

import httpx

from crawler.crawl import run
from crawler.fetch import USER_AGENT, Fetcher
from crawler.score import score_text

FX = Path(__file__).parent / "fixtures"
SEEN_UA = []


def handler(req: httpx.Request) -> httpx.Response:
    SEEN_UA.append(req.headers["user-agent"])
    h, p = req.url.host, req.url.path
    if "cbp.gov" in h:
        raise AssertionError("must never contact CBP")
    if p == "/robots.txt":
        if h == "www.reddit.com":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(404)
    if h == "hn.algolia.com":
        return httpx.Response(200, text=(FX / "hn.json").read_text())
    if h == "www.federalregister.gov":
        return httpx.Response(200, text=(FX / "fr.json").read_text())
    if h == "news.google.com":
        return httpx.Response(200, text=(FX / "gnews.xml").read_text())
    if h == "html.duckduckgo.com":
        return httpx.Response(200, text=(FX / "ddg_challenge.html").read_text())
    raise AssertionError(f"unexpected network call {req.url}")


def crawl(tmp_path):
    async def go():
        f = Fetcher(cache_dir=tmp_path / "cache", delay=0, transport=httpx.MockTransport(handler))
        try:
            return await run(["reddit", "hackernews", "federalregister", "googlenews", "duckduckgo", "x"],
                             tmp_path, fetcher=f, today="2026-10-23")
        finally:
            await f.aclose()
    return asyncio.run(go())


def test_scoring_prefers_payment_over_market_news():
    good, _ = score_text("Importer pays tariff in bitcoin", "customs broker accepted BTC to pay the duty")
    noise, _ = score_text("Bitcoin price crashes after tariffs", "markets tumble")
    assert good >= 60 and noise < 30
    assert score_text("Show HN", "todo app")[0] == 0


def test_end_to_end_with_fixtures(tmp_path, monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    new, report, stats, digest = crawl(tmp_path)
    urls = [l["url"] for l in new]
    assert "https://news.example/b" in urls and "https://news.example/a" not in urls
    assert any("federalregister.gov" in u for u in urls)
    assert report["reddit"] == 0 and stats["www.reddit.com"]["robots_blocked"] > 0
    assert stats["html.duckduckgo.com"]["challenge_blocked"] > 0
    assert report["x"] == 0
    assert all(ua == USER_AGENT for ua in SEEN_UA)
    scores = [l["score"] for l in new]
    assert scores == sorted(scores, reverse=True)
    gov = [l for l in new if l["source"] == "federalregister"][0]
    assert gov["entity_type"] == "gov"
    md = digest.read_text()
    assert md.startswith("# Tariff-in-crypto leads — 2026-10-23")
    lines = (tmp_path / "data" / "leads.jsonl").read_text().splitlines()
    assert len(lines) == len(new) and len({json.loads(l)["id"] for l in lines}) == len(lines)


def test_dedupe_across_runs(tmp_path):
    first = crawl(tmp_path)[0]
    second = crawl(tmp_path)[0]
    assert first and second == []


def test_cbp_hosts_never_allowed(tmp_path):
    async def go():
        f = Fetcher(cache_dir=tmp_path, delay=0, transport=httpx.MockTransport(handler))
        try:
            return await f.allowed("https://ace.cbp.dhs.gov/x"), await f.get("https://www.cbp.gov/trade")
        finally:
            await f.aclose()
    assert asyncio.run(go()) == (False, None)
