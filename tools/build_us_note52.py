"""Extract US Chapter 99 U.S. note 52 (Section 301 country duties, effective 2026-07-24) from the
official USITC HTS export (2026 HTS Revision 21). Source:
https://hts.usitc.gov/reststop/exportList?from=9903.01&to=9903.99&format=JSON&styles=false
Exceptions referenced in each heading (e.g. 9903.05.85-.92, country subdivisions (j)) are NOT
modelled: they are listed so the tool can say 'check source'."""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

URL = "https://hts.usitc.gov/reststop/exportList?from=9903.05&to=9903.07&format=JSON&styles=false"
OUT = Path(__file__).resolve().parent.parent / "data" / "landed" / "us" / "note52.json"
NAMES = {"Algeria": "DZ", "Angola": "AO", "Argentina": "AR", "Australia": "AU", "the Bahamas": "BS",
         "Bahrain": "BH", "Bangladesh": "BD", "Brazil": "BR", "Cambodia": "KH", "Canada": "CA", "Chile": "CL",
         "China": "CN", "Colombia": "CO", "Costa Rica": "CR", "Dominican Republic": "DO", "Ecuador": "EC",
         "Egypt": "EG", "El Salvador": "SV", "a member state of the European Union": "EU", "Guatemala": "GT",
         "Guyana": "GY", "Honduras": "HN", "Hong Kong, China": "HK", "India": "IN", "Indonesia": "ID",
         "Iraq": "IQ", "Israel": "IL", "Japan": "JP", "Jordan": "JO", "Kazakhstan": "KZ", "Kuwait": "KW",
         "Libya": "LY", "Malaysia": "MY", "Mexico": "MX", "Morocco": "MA", "New Zealand": "NZ",
         "Nicaragua": "NI", "Nigeria": "NG", "Norway": "NO", "Oman": "OM", "Pakistan": "PK", "Peru": "PE",
         "Philippines": "PH", "the Philippines": "PH", "Qatar": "QA", "Russia": "RU", "Saudi Arabia": "SA", "Singapore": "SG",
         "South Africa": "ZA", "South Korea": "KR", "Sri Lanka": "LK", "Switzerland": "CH", "Taiwan": "TW",
         "Thailand": "TH", "Trinidad and Tobago": "TT", "Türkiye": "TR", "the United Arab Emirates": "AE",
         "the United Kingdom": "GB", "Uruguay": "UY", "Venezuela": "VE", "Vietnam": "VN", "Laos": "LA",
         "Myanmar": "MM", "Burma": "MM", "Tunisia": "TN", "Ghana": "GH", "Kenya": "KE"}


def build(rows):
    out = {}
    unmapped = []
    for r in rows:
        h, desc, gen = r.get("htsno", ""), r.get("description") or "", (r.get("general") or "").strip()
        if "note 52" not in desc or "subdivision" in desc:
            continue
        m = re.search(r"articles the product of (.+?)(?:, with an ad valorem|, as provided for)", desc)
        if not m:
            continue
        iso = NAMES.get(m.group(1).strip())
        if not iso:
            unmapped.append(m.group(1))
            continue
        exc = re.search(r"Except for products described in headings (.+?), articles", desc)
        e = out.setdefault(iso, {"country": m.group(1).strip(), "headings": [], "exceptions": exc.group(1) if exc else ""})
        add = re.search(r"\+\s*([\d.]+)%", gen)
        floor = re.search(r"(equal to or greater than|less than) ([\d.]+) percent", desc)
        if add:
            e.update(kind="additive", add_pct=float(add.group(1)))
        elif floor:
            e.update(kind="floor", floor_pct=float(floor.group(2)))
        e["headings"].append(h)
    return out, unmapped


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else None
    rows = json.load(open(src)) if src else httpx.get(URL, timeout=60, headers={"User-Agent": "tariff-crypto-crawler/0.1"}).json()
    data, unmapped = build(rows)
    OUT.write_text(json.dumps({
        "source": "USITC HTS 2026 Revision 21, Chapter 99 subchapter III U.S. note 52 (headings 9903.05.20-9903.06.21)",
        "url": URL, "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Country-specific Section 301 duties in force from 2026-07-24. Exceptions not modelled; check source.",
        "countries": data, "unmapped": unmapped}, indent=1, sort_keys=True, ensure_ascii=False))
    print(len(data), "countries; unmapped:", unmapped)
