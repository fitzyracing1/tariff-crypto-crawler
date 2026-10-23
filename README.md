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
