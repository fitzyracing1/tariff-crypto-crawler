"""Keyword / regex relevance scoring."""
import re

CUSTOMS = r"(customs|dut(?:y|ies)|tariffs?|import\s+tax|cbp|customs\s+broker|brokerage|freight\s+forwarder|forwarder|clearance|ace\s+portal|section\s+301|de\s+minimis)"
CRYPTO = r"(crypto(?:currency|currencies)?|stablecoins?|usdc|usdt|tether|bitcoin|btc|ethereum|eth\b|digital\s+assets?|on-?chain|blockchain)"
PAY = r"(pay(?:ing|ment|s|ed)?|accept(?:s|ed|ing)?|settle(?:ment|d)?|remit)"
CUSTOMS_RE = re.compile(CUSTOMS, re.I)
CRYPTO_RE = re.compile(CRYPTO, re.I)
PAY_RE = re.compile(PAY, re.I)
MARKET_RE = re.compile(r"(price|crash|plummet|rall(?:y|ies)|sell-?off|tumbles?|slumps?|surges?|rebounds?|markets? reel|shorting|miners?)", re.I)
NEAR_RE = re.compile(rf"{CUSTOMS}.{{0,120}}?{CRYPTO}|{CRYPTO}.{{0,120}}?{CUSTOMS}", re.I | re.S)
STRONG_RE = re.compile(
    rf"{PAY}\s.{{0,60}}?{CUSTOMS}.{{0,60}}?(?:in|with|using|via)\s.{{0,20}}?{CRYPTO}"
    rf"|{PAY}\s.{{0,40}}?{CRYPTO}.{{0,60}}?{CUSTOMS}"
    rf"|{CUSTOMS}.{{0,40}}?{PAY}.{{0,40}}?{CRYPTO}",
    re.I | re.S,
)


def score_text(title: str, body: str) -> tuple[int, list[str]]:
    """Return (score 0-100, reasons)."""
    text = f"{title}\n{body}"
    reasons: list[str] = []
    s = 0
    c1 = {m.lower() for m in CUSTOMS_RE.findall(text)}
    c2 = {m.lower() for m in CRYPTO_RE.findall(text)}
    if not c1 or not c2:
        return 0, []
    s += min(len(c1), 4) * 5 + min(len(c2), 4) * 5
    reasons.append(f"customs terms: {', '.join(sorted(c1))[:80]}")
    reasons.append(f"crypto terms: {', '.join(sorted(c2))[:80]}")
    if NEAR_RE.search(text):
        s += 20
        reasons.append("customs and crypto terms within 120 chars")
    if STRONG_RE.search(text):
        s += 25
        reasons.append("explicit pay-duty-in-crypto phrasing")
    if CUSTOMS_RE.search(title) and CRYPTO_RE.search(title):
        s += 15
        reasons.append("both topics in title")
    if not PAY_RE.search(text):
        s = min(s, 20)
        reasons.append("no payment wording (capped)")
    noise = MARKET_RE.findall(text)
    if noise and not STRONG_RE.search(text):
        s -= 15
        reasons.append("market/price coverage, not payment (penalty)")
    return max(0, min(s, 100)), reasons


def best_snippet(text: str, width: int = 280) -> str:
    m = NEAR_RE.search(text) or CRYPTO_RE.search(text) or CUSTOMS_RE.search(text)
    if not m:
        return " ".join(text.split())[:width]
    start = max(0, m.start() - width // 3)
    return " ".join(text[start:start + width].split())


def entity_type(source: str, url: str, text: str) -> str:
    u = url.lower()
    t = text.lower()
    if source == "federalregister" or ".gov" in u:
        return "gov"
    if source in ("googlenews",) or any(d in u for d in ("news", "reuters", "bloomberg", "coindesk", "cointelegraph", "theblock", "decrypt")):
        return "news"
    if source in ("reddit", "hackernews"):
        return "individual"
    if "forwarder" in t or "freight" in t or "shipping" in u:
        return "forwarder"
    if "broker" in t:
        return "broker"
    return "news"
