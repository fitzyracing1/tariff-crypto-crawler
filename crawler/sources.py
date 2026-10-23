"""Public, no-auth sources. Each returns a list of raw items:
{url, title, body, date, source}."""
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlsplit, parse_qs, unquote

QUERIES = [
    "pay customs duty crypto",
    "customs broker USDC",
    "pay tariff bitcoin",
    "pay import duties stablecoin",
    "customs broker accepts cryptocurrency",
    "freight forwarder accepts bitcoin",
    "CBP stablecoin payment",
    "tariff payment crypto",
]
SUBREDDITS = ["ImportExport", "FulfillmentByAmazon", "logistics", "CryptoCurrency",
              "smallbusiness", "AmazonSeller", "stablecoin", "Bitcoin", "ecommerce"]

TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(s: str) -> str:
    return html.unescape(TAG_RE.sub(" ", s or ""))


def _iso(ts) -> str:
    if ts is None:
        return ""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
    return str(ts)[:10]


async def reddit(f, queries=QUERIES):
    out = []
    for sub in SUBREDDITS:
        for q in queries[:3]:
            url = (f"https://www.reddit.com/r/{sub}/search.json?q={quote_plus(q)}"
                   "&restrict_sr=1&sort=new&limit=25")
            body = await f.get(url)
            if not body:
                continue
            try:
                kids = json.loads(body)["data"]["children"]
            except (ValueError, KeyError, TypeError):
                continue
            for k in kids:
                d = k.get("data", {})
                out.append({"url": "https://www.reddit.com" + d.get("permalink", ""),
                            "title": d.get("title", ""), "body": d.get("selftext", ""),
                            "date": _iso(d.get("created_utc")), "source": "reddit"})
    return out


async def hackernews(f, queries=QUERIES):
    out = []
    for q in queries:
        url = f"https://hn.algolia.com/api/v1/search?query={quote_plus(q)}&hitsPerPage=30"
        body = await f.get(url, check_robots=False)  # documented public API
        if not body:
            continue
        for h in json.loads(body).get("hits", []):
            oid = h.get("objectID")
            out.append({
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                "title": h.get("title") or h.get("story_title") or "",
                "body": strip_tags(h.get("story_text") or h.get("comment_text") or ""),
                "date": _iso(h.get("created_at")), "source": "hackernews",
                "discussion": f"https://news.ycombinator.com/item?id={oid}"})
    return out


async def federal_register(f, queries=("cryptocurrency customs duties", "stablecoin customs",
                                       "digital assets tariff payment", "customs duties electronic payment")):
    out = []
    for q in queries:
        url = ("https://www.federalregister.gov/api/v1/documents.json?per_page=20&order=relevance"
               f"&conditions[term]={quote_plus(q)}")
        body = await f.get(url, check_robots=False)  # documented public API
        if not body:
            continue
        for d in json.loads(body).get("results", []):
            out.append({"url": d.get("html_url", ""), "title": d.get("title", ""),
                        "body": d.get("abstract") or "", "date": d.get("publication_date", ""),
                        "source": "federalregister"})
    return out


async def google_news(f, queries=QUERIES):
    out = []
    for q in queries:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
        body = await f.get(url, check_robots=False)  # public RSS feed endpoint
        if not body:
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            continue
        for it in root.iter("item"):
            pub = it.findtext("pubDate") or ""
            try:
                pub = parsedate_to_datetime(pub).date().isoformat()
            except (TypeError, ValueError):
                pub = ""
            out.append({"url": it.findtext("link") or "", "title": it.findtext("title") or "",
                        "body": strip_tags(it.findtext("description") or ""), "date": pub,
                        "source": "googlenews"})
    return out


DDG_RESULT = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                        r'class="result__snippet"[^>]*>(.*?)</a>', re.S)


async def duckduckgo(f, queries=QUERIES):
    """DuckDuckGo HTML results; skipped automatically if robots.txt disallows."""
    out = []
    for q in queries:
        body = await f.get(f"https://html.duckduckgo.com/html/?q={quote_plus(q)}")
        if not body:
            continue
        for href, title, snip in DDG_RESULT.findall(body):
            if "uddg=" in href:
                href = unquote(parse_qs(urlsplit(href).query).get("uddg", [href])[0])
            out.append({"url": html.unescape(href), "title": strip_tags(title),
                        "body": strip_tags(snip), "date": "", "source": "duckduckgo"})
    return out


async def x_recent(f, queries=QUERIES):
    """Optional: needs X_BEARER_TOKEN. Skipped gracefully when absent (e.g. CI)."""
    tok = os.environ.get("X_BEARER_TOKEN")
    if not tok:
        return []
    out = []
    for q in queries[:3]:
        try:
            r = await f.client.get("https://api.x.com/2/tweets/search/recent",
                                   params={"query": q, "max_results": 25, "tweet.fields": "created_at"},
                                   headers={"Authorization": f"Bearer {tok}"})
            data = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            data = []
        for t in data:
            out.append({"url": f"https://x.com/i/status/{t['id']}", "title": t["text"][:100],
                        "body": t["text"], "date": _iso(t.get("created_at")), "source": "x"})
    return out


SOURCES = {"reddit": reddit, "hackernews": hackernews, "federalregister": federal_register,
           "googlenews": google_news, "duckduckgo": duckduckgo, "x": x_recent}
