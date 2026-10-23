"""Write data/landed/meta.json: coverage + sources + dates per destination (offline, from snapshots)."""
import csv
import json
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "data" / "landed"


def snap(t):
    files = sorted((D / t).glob("*.json"))
    codes, dates, heads = 0, set(), []
    for p in files:
        j = json.loads(p.read_text())
        codes += len(j["commodities"]); dates.add(j["fetched_at"][:10]); heads.append(j["heading"])
    return {"headings": heads, "commodity_lines": codes, "fetched": sorted(dates)}


us_lines = sum(1 for _ in csv.DictReader(open(D / "us" / "hts_base.csv")))
us_add = sum(1 for _ in csv.DictReader(open(D / "us" / "additional.csv")))
n52 = json.loads((D / "us" / "note52.json").read_text())
UKAPI = "UK Online Trade Tariff API (HMRC/DBT), documented public API, Open Government Licence v3.0: " \
        "https://www.trade-tariff.service.gov.uk/{uk|xi}/api/ (docs https://api.trade-tariff.service.gov.uk/reference.html)"
meta = {
    "built": "2026-10-23",
    "policy": "Official public data only; rates not in snapshots are 'check source'. CI never fetches.",
    "destinations": {
        "US": {"lines": us_lines, "additional_ch99_rows": us_add, "note52_countries": len(n52["countries"]),
               "sources": ["USITC HTS 2026 Revision 21 (revision date 2026-10-07, effective 2026-10-09) "
                           "https://hts.usitc.gov/reststop/exportList (copied from fitzyracing1/space-money data/hts)",
                           n52["source"] + " " + n52["url"]],
               "dates": {"hts_revision": "2026 Rev 21 (2026-10-07)", "note52_built": n52["built_at"]},
               "import_vat": "none federally; state sales/use tax not modelled",
               "gaps": ["specific/compound rates need quantity", "AD/CVD orders not modelled",
                        "note 52 exceptions and GSP/AGOA eligibility: check source", "MPF/HMF fees not included"]},
        "PT": {**snap("xi"), "sources": ["EU Common External Tariff via " + UKAPI.replace("{uk|xi}", "xi") +
                                         " (Northern Ireland applies the EU tariff; verify in EU TARIC "
                                         "https://ec.europa.eu/taxation_customs/dds2/taric/taric_consultation.jsp)",
                                         "Portugal VAT CIVA art. 18 https://info.portaldasfinancas.gov.pt/pt/informacao_fiscal/codigos_tributarios/civa_rep/Pages/iva18.aspx (checked 2026-10-23)"],
               "gaps": ["only seeded headings", "TARIC-only EU measures not mirrored in XI (e.g. some AD duties) may differ",
                        "Lista I/II reduced-rate goods not mapped (23% assumed for others)", "Azores/Madeira rates"]},
        "EU": {**snap("xi"), "sources": ["as PT (CET only)"], "gaps": ["member-state VAT not included: check source"]},
        "UK": {**snap("uk"), "sources": ["UK Global Tariff, preferences and import VAT via " + UKAPI.replace("{uk|xi}", "uk")],
               "gaps": ["only seeded headings", "quota status not live", "VAT reliefs by footnote not mapped"]},
    },
    "space": {"file": "space/launch_prices.json", "retrieved": "2026-10-23",
              "sources": ["https://www.spacex.com/rideshare", "https://rideshare.spacex.com/external-search",
                          "https://newspaceeconomy.ca/2026/02/27/spacex-rideshare-pricing-as-of-february-2026-what-it-costs-whats-included-and-how-buyers-budget-a-mission/",
                          "https://www.rideshareledger.space/prices.html"],
              "gaps": ["SpaceX price shown only in its JS calculator; figures via secondary sources citing spacex.com",
                       "other providers publish no per-kg price: check source", "ITAR/EAR not computed (text only)"]},
    "origin": {"file": "origin/origins.json", "verified_links_on": "2026-10-23"},
    "not_used_yet": ["WTO Tariff & Trade Data https://ttd.wto.org/en", "WITS https://wits.worldbank.org/"],
}
(D / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
print(json.dumps({k: {x: v[x] for x in v if x in ("lines", "commodity_lines", "headings")} for k, v in meta["destinations"].items()}))
