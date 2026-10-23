"""Orchestrates sources, depth-2 follow, scoring, dedupe, outputs."""
import argparse
import asyncio
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .fetch import Fetcher, url_hash
from .score import best_snippet, entity_type, score_text
from .sources import SOURCES, strip_tags

HREF_RE = re.compile(r'href="([^"#]+)"', re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
FOLLOW_HINT = re.compile(r"(pay|crypto|bitcoin|usdc|stablecoin|customs|dut|broker|tariff|faq|billing)", re.I)
SKIP_FOLLOW = ("reddit.com", "ycombinator.com", "news.google.com", "federalregister.gov",
               "x.com", "twitter.com", "youtube.com", "facebook.com", "linkedin.com")
MIN_SCORE = 30


def page_text(body: str) -> tuple[str, str]:
    t = TITLE_RE.search(body)
    return (strip_tags(t.group(1)).strip() if t else ""), " ".join(strip_tags(SCRIPT_RE.sub(" ", body)).split())


async def follow(f, start_url, max_depth=2, max_pages=8):
    """BFS within start domain up to depth 2, honoring robots.txt."""
    host = urlsplit(start_url).netloc
    seen, out, frontier = {start_url}, [], [(start_url, 0)]
    while frontier and len(out) < max_pages:
        url, d = frontier.pop(0)
        body = await f.get(url)
        if not body or "<" not in body[:2000]:
            continue
        title, text = page_text(body)
        out.append({"url": url, "title": title, "body": text[:20000], "date": "", "depth": d})
        if d >= max_depth:
            continue
        for h in HREF_RE.findall(body):
            nu = urljoin(url, h).split("#")[0]
            if urlsplit(nu).netloc == host and nu not in seen and FOLLOW_HINT.search(nu):
                seen.add(nu)
                frontier.append((nu, d + 1))
    return out


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(l)["id"] for l in path.read_text().splitlines() if l.strip()}


def make_lead(item, today):
    score, why = score_text(item.get("title", ""), item.get("body", ""))
    text = f"{item.get('title','')} {item.get('body','')}"
    return {"id": url_hash(item["url"]), "title": item.get("title", "").strip()[:200],
            "url": item["url"], "source": item["source"], "date": item.get("date") or "",
            "snippet": best_snippet(item.get("body") or item.get("title", "")),
            "entity_type": entity_type(item["source"], item["url"], text),
            "score": score, "why": why, "found": today}


async def run(sources, out_dir=".", fetcher=None, follow_links=True, today=None):
    today = today or date.today().isoformat()
    root = Path(out_dir)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "digests").mkdir(parents=True, exist_ok=True)
    leads_path = root / "data" / "leads.jsonl"
    seen = load_seen(leads_path)
    f = fetcher or Fetcher(cache_dir=root / "cache")
    report = {}
    items = []
    try:
        for name in sources:
            try:
                got = await SOURCES[name](f)
            except Exception as e:  # noqa: BLE001
                got, report[name + "_error"] = [], repr(e)[:200]
            report[name] = len(got)
            items += got
        # Depth-2 follow on web results (broker / forwarder sites found via search).
        if follow_links:
            web = [i for i in items if i["source"] in ("duckduckgo", "hackernews")
                   and not any(s in i["url"] for s in SKIP_FOLLOW)
                   and score_text(i["title"], i["body"])[0] >= MIN_SCORE]
            for i in web[:15]:
                for p in await follow(f, i["url"]):
                    p["source"] = "web"
                    items.append(p)
    finally:
        if fetcher is None:
            await f.aclose()
    new, batch = [], set()
    for it in items:
        if not it.get("url"):
            continue
        lead = make_lead(it, today)
        if lead["score"] < MIN_SCORE or lead["id"] in seen or lead["id"] in batch:
            continue
        batch.add(lead["id"])
        new.append(lead)
    new.sort(key=lambda l: -l["score"])
    with leads_path.open("a") as fh:
        for l in new:
            fh.write(json.dumps(l) + "\n")
    digest = root / "digests" / f"{today}.md"
    digest.write_text(render_digest(new, today, report, f.stats))
    return new, report, f.stats, digest


def render_digest(leads, today, report, stats):
    lines = [f"# Tariff-in-crypto leads — {today}", "",
             f"{len(leads)} new lead(s), sorted by score. Read-only crawl; see README for scope.", ""]
    for i, l in enumerate(leads, 1):
        lines += [f"## {i}. {l['title'] or l['url']}", "",
                  f"- **Score:** {l['score']} | **Type:** {l['entity_type']} | **Source:** {l['source']} | **Date:** {l['date'] or 'n/a'}",
                  f"- **URL:** <{l['url']}>",
                  f"- **Why:** {'; '.join(l['why'])}",
                  f"- > {l['snippet']}", ""]
    lines += ["## Source report", "", "| source | items |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in report.items()]
    lines += ["", "| host | fetch outcomes |", "|---|---|"]
    lines += [f"| {h} | {', '.join(f'{k}={v}' for k, v in s.items())} |" for h, s in sorted(stats.items())]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=",".join(SOURCES))
    ap.add_argument("--out", default=".")
    ap.add_argument("--no-follow", action="store_true")
    a = ap.parse_args()
    new, report, stats, digest = asyncio.run(run(a.sources.split(","), a.out, follow_links=not a.no_follow))
    print(json.dumps({"new": len(new), "report": report, "stats": stats, "digest": str(digest)}, indent=1))


if __name__ == "__main__":
    main()
