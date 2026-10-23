"""Polite async fetcher: robots.txt, per-host rate limiting, on-disk cache."""
import asyncio
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = (
    "tariff-crypto-crawler/0.1 (+https://github.com/fitzyracing1/tariff-crypto-crawler; "
    "read-only research bot)"
)
# Never touch CBP / ACE systems.
BLOCKED_HOSTS = ("cbp.gov", "ace.cbp.dhs.gov", "cbp.dhs.gov")


def url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()[:24]


class Fetcher:
    def __init__(self, cache_dir="cache", delay=2.0, transport=None, ttl=20 * 3600):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.ttl = ttl
        self.client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            timeout=20, follow_redirects=True, transport=transport,
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.stats: dict[str, dict[str, int]] = {}

    def _stat(self, host, key):
        self.stats.setdefault(host, {}).setdefault(key, 0)
        self.stats[host][key] += 1

    async def aclose(self):
        await self.client.aclose()

    async def _wait(self, host):
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            gap = time.monotonic() - self._last.get(host, 0)
            if gap < self.delay:
                await asyncio.sleep(self.delay - gap)
            self._last[host] = time.monotonic()

    async def allowed(self, url: str) -> bool:
        p = urlsplit(url)
        host = p.netloc.lower()
        if any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS):
            return False
        if host not in self._robots:
            rp = RobotFileParser()
            try:
                await self._wait(host)
                r = await self.client.get(f"{p.scheme}://{host}/robots.txt")
                if r.status_code in (401, 403):
                    rp = None  # treat as disallow-all
                elif r.status_code >= 400:
                    rp.parse([])
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp.parse([])
            self._robots[host] = rp
        rp = self._robots[host]
        return bool(rp and rp.can_fetch(USER_AGENT, url))

    async def get(self, url: str, check_robots=True) -> str | None:
        host = urlsplit(url).netloc.lower()
        cf = self.cache / f"{url_hash(url)}.json"
        if cf.exists():
            d = json.loads(cf.read_text())
            if time.time() - d["t"] < self.ttl and "complete the following challenge" not in d["body"]:
                self._stat(host, "cached")
                return d["body"]
        if check_robots and not await self.allowed(url):
            self._stat(host, "robots_blocked")
            return None
        await self._wait(host)
        try:
            r = await self.client.get(url)
        except httpx.HTTPError:
            self._stat(host, "error")
            return None
        if r.status_code == 429:
            self._stat(host, "rate_limited")
            return None
        if r.status_code >= 400:
            self._stat(host, f"http_{r.status_code}")
            return None
        if "complete the following challenge" in r.text or "captcha" in r.text[:3000].lower():
            self._stat(host, "challenge_blocked")  # never attempt to solve or bypass
            return None
        self._stat(host, "ok")
        cf.write_text(json.dumps({"t": time.time(), "url": url, "body": r.text}))
        return r.text
