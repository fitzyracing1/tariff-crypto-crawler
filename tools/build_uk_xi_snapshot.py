"""Build compact UK (UK Global Tariff) and XI (EU CET as applied in Northern Ireland) snapshots.

Source: UK Online Trade Tariff public API (HMRC / Department for Business and Trade),
https://www.trade-tariff.service.gov.uk/{uk,xi}/api/ - documented public API
(https://api.trade-tariff.service.gov.uk/reference.html), no auth, Open Government Licence v3.0.
Polite: 1 GET per 1.2 s, identified User-Agent, seed headings only. Run manually; CI never hits the network.

Usage: python tools/build_uk_xi_snapshot.py 6109 6110 ...
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "https://www.trade-tariff.service.gov.uk"
UA = "tariff-crypto-crawler/0.1 (+https://github.com/fitzyracing1/tariff-crypto-crawler; read-only research)"
OUT = Path(__file__).resolve().parent.parent / "data" / "landed"
KEEP = ("Third country duty", "Tariff preference", "Preferential tariff quota", "Customs Union Duty",
        "Value added tax", "Additional duties", "anti-dumping", "countervailing", "Low-value consignment",
        "Restriction", "Import control", "prohibition", "Entry into free circulation")
DELAY = 1.2
_last = [0.0]


def get(client, path):
    wait = DELAY - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()
    r = client.get(BASE + path)
    r.raise_for_status()
    return r.json()


def parse_commodity(d):
    inc = {(i["type"], i["id"]): i for i in d.get("included", [])}
    areas = {}
    for (t, i), v in inc.items():
        if t == "geographical_area":
            kids = [c["id"] for c in v.get("relationships", {}).get("children_geographical_areas", {}).get("data", [])]
            areas[i] = {"name": v["attributes"].get("description"), "members": kids}
    measures = []
    for ref in d["data"]["relationships"].get("import_measures", {}).get("data", []):
        m = inc.get(("measure", ref["id"]))
        if not m:
            continue
        r = m["relationships"]
        mtype = inc.get(("measure_type", r["measure_type"]["data"]["id"]), {}).get("attributes", {}).get("description", "")
        if not any(k.lower() in mtype.lower() for k in KEEP):
            continue
        de = r.get("duty_expression", {}).get("data")
        duty = inc.get(("duty_expression", de["id"]), {}).get("attributes", {}).get("base", "") if de else ""
        geo = r["geographical_area"]["data"]["id"]
        measures.append({
            "type": mtype,
            "type_id": r["measure_type"]["data"]["id"],
            "area": geo,
            "excluded": [x["id"] for x in r.get("excluded_countries", {}).get("data", [])],
            "duty": (duty or "").strip(),
            "quota": (r.get("order_number", {}).get("data") or {}).get("id"),
            "conditions": len(r.get("measure_conditions", {}).get("data", [])),
            "footnotes": [f["id"] for f in r.get("footnotes", {}).get("data", [])],
            "start": (m["attributes"].get("effective_start_date") or "")[:10],
        })
    used = {m["area"] for m in measures}
    return {
        "code": d["data"]["attributes"]["goods_nomenclature_item_id"],
        "description": d["data"]["attributes"].get("formatted_description") or d["data"]["attributes"].get("description"),
        "measures": measures,
        "areas": {k: v for k, v in areas.items() if k in used and v["members"]},
    }


def build(tariff, headings, client):
    for h in headings:
        hd = get(client, f"/{tariff}/api/headings/{h}")
        leaves = [i["attributes"] for i in hd.get("included", [])
                  if i["type"] == "commodity" and i["attributes"].get("leaf")]
        if not leaves:  # heading itself is a declarable commodity
            leaves = [{"goods_nomenclature_item_id": f"{h}000000"}]
        out = {"tariff": tariff, "heading": h, "source": f"{BASE}/{tariff}/api/headings/{h}",
               "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "commodities": {}}
        for leaf in leaves:
            code = leaf["goods_nomenclature_item_id"]
            try:
                cd = get(client, f"/{tariff}/api/commodities/{code}")
            except httpx.HTTPStatusError as e:
                print("skip", tariff, code, e.response.status_code, file=sys.stderr)
                continue
            out["commodities"][code] = parse_commodity(cd)
        (OUT / tariff).mkdir(parents=True, exist_ok=True)
        (OUT / tariff / f"{h}.json").write_text(json.dumps(out, separators=(",", ":"), sort_keys=True))
        print(tariff, h, len(out["commodities"]))


if __name__ == "__main__":
    hs = sys.argv[1:] or ["6109"]
    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30) as c:
        for t in (os.environ.get("TARIFFS", "uk,xi").split(",")):
            build(t, hs, c)
