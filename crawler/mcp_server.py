"""MCP server (stdio) exposing the read-only tariff-crypto crawler.

All tools are read-only: GET requests to public endpoints only, robots.txt honored
(except documented public APIs), 2s per host, CBP/ACE hosts blocked, captchas/challenges
are never solved, nothing is written to data/ or digests/, and nobody is contacted.
"""
import asyncio
import json
import os
import re
from datetime import date
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .crawl import MIN_SCORE, make_lead
from .fetch import Fetcher, url_hash
from .sources import federal_register, google_news, hackernews

# Only no-auth public APIs/feeds are allowed for on-demand scans.
SCAN_SOURCES = {"hackernews": hackernews, "federalregister": federal_register, "googlenews": google_news}
MAX_ITEMS_CAP = 50
MAX_QUERY_LEN = 200
HTS_URL = "https://hts.usitc.gov/"
COMPLIANCE_CAVEAT = (
    "Compliance: preferential treatment requires GENUINE origin under the program's rules of "
    "origin (tariff shift / regional value content / substantial transformation) with supporting "
    "records. Relabeling or routing goods through a third country to change apparent origin "
    "(transshipment) is customs fraud (19 U.S.C. 1592) and can bring penalties, seizure and "
    "criminal liability. Confirm with a licensed customs broker; this is not legal advice."
)
RO = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
RO_NET = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True)


def data_root() -> Path:
    return Path(os.environ.get("TARIFF_CRYPTO_DATA_DIR", ".")).expanduser()


def scan_cache_dir() -> Path:
    return Path(os.environ.get("TARIFF_CRYPTO_CACHE_DIR",
                               Path.home() / ".cache" / "tariff-crypto-mcp")).expanduser()


async def do_scan(query=None, sources=None, max_items=20, fetcher=None, today=None):
    names = sources or list(SCAN_SOURCES)
    bad = [s for s in names if s not in SCAN_SOURCES]
    if bad:
        return {"error": f"unsupported source(s) {bad}; allowed: {sorted(SCAN_SOURCES)}"}
    max_items = max(1, min(int(max_items or 20), MAX_ITEMS_CAP))
    queries = None
    if query:
        q = " ".join(str(query).split())[:MAX_QUERY_LEN]
        queries = [q]
    today = today or date.today().isoformat()
    f = fetcher or Fetcher(cache_dir=scan_cache_dir())
    report, items = {}, []
    try:
        for n in names:
            fn = SCAN_SOURCES[n]
            try:
                got = await (fn(f, queries) if queries else fn(f))
            except Exception as e:  # noqa: BLE001
                got, report[n + "_error"] = [], repr(e)[:200]
            report[n] = len(got)
            items += got
    finally:
        if fetcher is None:
            await f.aclose()
    leads, seen = [], set()
    for it in items:
        if not it.get("url"):
            continue
        lead = make_lead(it, today)
        if lead["score"] < MIN_SCORE or lead["id"] in seen:
            continue
        seen.add(lead["id"])
        leads.append(lead)
    leads.sort(key=lambda l: -l["score"])
    return {"leads": leads[:max_items], "report": report, "stats": f.stats,
            "note": "On-demand scan; results are not persisted."}


def read_digest(date_str=None, root=None):
    d = (root or data_root()) / "digests"
    if date_str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
            return "Invalid date; use YYYY-MM-DD."
        p = d / f"{date_str}.md"
    else:
        files = sorted(d.glob("*.md")) if d.exists() else []
        if not files:
            return f"No digests found in {d}."
        p = files[-1]
    return p.read_text() if p.exists() else f"No digest for {date_str}."


def read_leads(min_score=0, limit=50, root=None):
    p = (root or data_root()) / "data" / "leads.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            l = json.loads(line)
        except ValueError:
            continue
        if l.get("score", 0) >= (min_score or 0):
            out.append(l)
    out.sort(key=lambda l: -l.get("score", 0))
    return out[: max(1, min(int(limit or 50), 500))]


PROGRAMS = [
    {"program": "USMCA (United States-Mexico-Canada Agreement)", "partners": ["Mexico", "Canada"],
     "type": "free trade agreement", "hts_indicator": "S / S+",
     "notes": "Goods must meet product-specific rules of origin (General Note 11); certification of origin required."},
    {"program": "Other US FTAs", "partners": ["Australia", "Bahrain", "Chile", "Colombia", "Costa Rica",
                                               "Dominican Republic", "El Salvador", "Guatemala", "Honduras",
                                               "Nicaragua", "Israel", "Jordan", "Korea", "Morocco", "Oman",
                                               "Panama", "Peru", "Singapore"],
     "type": "free trade agreements", "hts_indicator": "AU, BH, CL, CO, P/P+ (CAFTA-DR), IL, JO, KR, MA, OM, PA, PE, SG",
     "notes": "Each FTA has its own rules of origin in the HTS General Notes."},
    {"program": "AGOA (African Growth and Opportunity Act)", "partners": ["eligible sub-Saharan African countries"],
     "type": "unilateral preference", "hts_indicator": "D",
     "notes": "Country eligibility changes and the program requires reauthorization; verify current status."},
    {"program": "Foreign-Trade Zones (FTZ)", "partners": ["any origin"], "type": "duty deferral/reduction",
     "hts_indicator": "n/a",
     "notes": "Duty deferred until entry into US commerce; possible inverted tariff benefit; no duty on re-exports. Requires FTZ Board/CBP-approved zone. Does NOT exempt Section 232/301 or other trade-remedy duties automatically."},
    {"program": "Duty drawback (19 U.S.C. 1313)", "partners": ["any origin"], "type": "refund",
     "hts_indicator": "n/a",
     "notes": "Refund of up to 99% of duties on goods (or substitutes) later exported or destroyed; strict documentation and time limits."},
]


def supplier_programs(hts_code: str):
    digits = re.sub(r"\D", "", hts_code or "")
    if len(digits) < 4 or len(digits) > 10:
        return {"error": "Provide an HTS code with 4-10 digits, e.g. 8471.30.01."}
    return {
        "hts_code": hts_code,
        "hts_lookup": f"{HTS_URL}search?query={digits}",
        "rate_info": "check HTS: this server has no verified USITC HTS rate data, so no duty rates "
                     "are quoted. Look up general/special columns at hts.usitc.gov.",
        "programs": PROGRAMS,
        "compliance_caveat": COMPLIANCE_CAVEAT,
    }


mcp = MCPServer("tariff-crypto-mcp", instructions=(
    "Read-only research tools for public evidence of paying US customs duties in crypto, "
    "plus legal duty-reduction program info. Never contacts anyone."))


@mcp.tool(annotations=RO_NET)
async def scan_leads(query: str | None = None, sources: list[str] | None = None, max_items: int = 20) -> dict:
    """Run a bounded, read-only scan of public sources (hackernews, federalregister, googlenews).
    Honors robots.txt, 2s/host delay, blocks CBP/ACE hosts, never solves captchas, GET only.
    max_items is capped at 50. Results are returned, not persisted."""
    return await do_scan(query, sources, max_items)


@mcp.tool(annotations=RO)
def get_digest(date: str | None = None) -> str:
    """Return the markdown digest for YYYY-MM-DD (default: latest)."""
    return read_digest(date)


@mcp.tool(annotations=RO)
def list_leads(min_score: int = 0, limit: int = 50) -> list[dict]:
    """List stored leads from data/leads.jsonl, highest score first."""
    return read_leads(min_score, limit)


@mcp.tool(annotations=RO)
def match_suppliers(hts_code: str) -> dict:
    """Legal zero/low-duty program info (USMCA, other US FTAs, AGOA, FTZ, drawback) for an HTS code.
    Rates are never guessed: check the USITC HTS. Includes a compliance caveat."""
    return supplier_programs(hts_code)


def main():
    mcp.run("stdio")


if __name__ == "__main__":
    main()
