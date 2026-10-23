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
