# tariff-crypto-crawler

A small, polite, **read-only** async Python crawler that looks for *public* evidence of
people or companies trying to pay US customs duties / tariffs in crypto (stablecoins, USDC,
USDT, BTC…). Leads feed the on-chain tariff feed project
[fitzyracing1/space-money](https://github.com/fitzyracing1/space-money).

## Sources
| source | endpoint | notes |
|---|---|---|
| Hacker News | `hn.algolia.com/api/v1/search` | public API |
| Federal Register | `federalregister.gov/api/v1/documents.json` | public API |
| Google News | `news.google.com/rss/search` | public RSS |
| Reddit | `reddit.com/r/<sub>/search.json` | honors robots.txt — currently disallowed for generic bots, so skipped |
| DuckDuckGo HTML | `html.duckduckgo.com/html/` | skipped when a bot challenge is returned (never solved) |
| Web follow | broker/forwarder sites from search results | depth ≤ 2, same domain, robots.txt honored |
| X (optional) | `api.x.com/2/tweets/search/recent` | only if `X_BEARER_TOKEN` is set; skipped otherwise |

## Usage
```bash
pip install -r requirements.txt
python -m crawler.crawl            # all sources
python -m crawler.crawl --sources hackernews,federalregister --no-follow
```
Outputs: `data/leads.jsonl` (append-only, deduped by SHA-256 URL hash) and
`digests/YYYY-MM-DD.md` (new leads only, sorted by score). Responses are cached in `cache/`.

Each lead: `title, url, source, date, snippet, entity_type (individual|broker|forwarder|news|gov), score, why`.
Scoring (`crawler/score.py`) rewards customs/duty/tariff/broker/CBP terms near crypto terms
and explicit "pay … duty … in USDC"-style phrasing, caps items with no payment wording,
and penalizes pure market/price coverage ("bitcoin falls on tariffs").

## Ethics and scope
- **Strictly read-only.** GET requests only; never posts, messages, signs up, or submits forms.
- **Never touches CBP/ACE systems** — those hosts are hard-blocked in code.
- **robots.txt is honored** for every crawled site; 401/403 on robots.txt = disallow all.
- **Rate limited**: ≥ 2 s between requests per host, sequential per host; 429 = back off.
- **Identifies itself**: `User-Agent: tariff-crypto-crawler/0.1 (+https://github.com/fitzyracing1/tariff-crypto-crawler; read-only research bot)`.
- **No login-walled content**, no CAPTCHA solving, no proxy rotation or evasion.
- Collects only public titles/snippets/links; leads are pointers for manual review, not accusations.

## CI
- `ci.yml` runs tests against recorded fixtures (no live network). A passing run is **lit**, a failing one **dark**.
- `daily-crawl.yml` runs the crawl daily on public endpoints (no secrets) and commits the new digest.

## License
MIT © 2026 Joshua Almeida

## MCP server

A stdio [MCP](https://modelcontextprotocol.io) server (official `mcp` Python SDK) that reuses the crawler code. Every tool is read-only and contacts no one.

| tool | what it does |
|---|---|
| `scan_leads(query?, sources?, max_items?)` | On-demand bounded scan of `hackernews`, `federalregister` and `googlenews` (no-auth public APIs/feeds) with the crawler's safety rules: GET only, robots.txt honored, 2s per host, CBP/ACE hosts blocked, captchas never solved. `max_items` is capped at 50. Results are returned but **not** written to `data/` or `digests/`. |
| `get_digest(date?)` | Returns `digests/YYYY-MM-DD.md` (default: the latest one). |
| `list_leads(min_score?, limit?)` | Reads `data/leads.jsonl`, highest score first. |
| `match_suppliers(hts_code)` | Info on legal zero/low-duty programs (USMCA, other US FTAs, AGOA, FTZ, duty drawback), plus a compliance caveat: origin must be genuine, and transshipment is fraud. It never quotes a duty rate. It says "check HTS" and links to the [USITC HTS](https://hts.usitc.gov/). |

### Install (not on PyPI)

```bash
pip install "git+https://github.com/fitzyracing1/tariff-crypto-crawler.git"
# or from a clone: pip install -e .
```

This installs the `tariff-crypto-mcp` console script. Environment variables:
- `TARIFF_CRYPTO_DATA_DIR`: the folder that holds `data/` and `digests/` (default: the current directory).
- `TARIFF_CRYPTO_CACHE_DIR`: the scan cache (default: `~/.cache/tariff-crypto-mcp`).

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "tariff-crypto": {
      "command": "tariff-crypto-mcp",
      "env": { "TARIFF_CRYPTO_DATA_DIR": "/path/to/tariff-crypto-crawler" }
    }
  }
}
```

### Cursor (`~/.cursor/mcp.json` or `.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "tariff-crypto": {
      "command": "tariff-crypto-mcp",
      "env": { "TARIFF_CRYPTO_DATA_DIR": "/path/to/tariff-crypto-crawler" }
    }
  }
}
```

If the script isn't on your PATH, set `command` to the full path, for example `/path/to/.venv/bin/tariff-crypto-mcp`.

## Landed-cost route search (`landed_cost` MCP tool)

`landed_cost(hs, origin="any", destination="US"|"PT"|"EU"|"UK", value=100, freight=0, insurance=0, seller_accepts_crypto=False)`
ranks the cheapest **legal** origin routes for an HS code (or keyword) by:

- origin side: export VAT/GST treatment (zero-rating / refund), export duties, notable export zones (`data/landed/origin/origins.json`, statutory bases + official links);
- import duty: MFN and preferential (trade agreements / GSP-type schemes) plus additional duties (US Section 301 incl. U.S. note 52, Section 232; UK/EU additional duties);
- import VAT/GST: UK from tariff measures, Portugal CIVA art. 18 (23% / 13% / 6%), US none federally.

Valuation: US duty on transaction (FOB) value; EU/UK duty on CIF; VAT on CIF + duty. Rates not in the
snapshots are returned as `"check source"` and are never guessed; such routes are marked incomplete.
The crypto filter is a placeholder (no seller data yet) and paying in crypto never changes duty: customs
value is the transaction value converted to local currency.

Data (`data/landed/meta.json` has coverage, sources and dates):

| Destination | Source | Notes |
|---|---|---|
| US | USITC HTS 2026 Rev 21 (from `fitzyracing1/space-money` `data/hts`), Ch.99 U.S. note 52 (`tools/build_us_note52.py`) | full HTS |
| PT / EU | EU CET via UK Online Trade Tariff `xi` API (Northern Ireland applies the EU tariff), Portugal CIVA | seeded headings |
| UK | UK Global Tariff + preferences + VAT via UK Online Trade Tariff `uk` API | seeded headings |

Refresh (manual, polite: 1 request / 1.2 s, identified User-Agent; CI never fetches):

```bash
python tools/build_uk_xi_snapshot.py 6109 6110 ...   # UK + XI
python tools/build_us_note52.py                       # US note 52
python tools/build_meta.py
python tools/export_landed_page.py ../space-money/data/landed/landed.json
```

Compliance: preference needs genuine origin under the agreement's rules of origin and proof
(certificate / statement on origin, REX, USMCA certification). Transshipment or relabeling to change
origin is customs fraud. Not legal or tax advice.
