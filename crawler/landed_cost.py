"""Landed-cost route search: rank the cheapest LEGAL origin routes for an HS code into US / EU (PT) / UK.

Data (all offline snapshots, sources in data/landed/meta.json):
  US  - USITC HTS 2026 Rev 21 (general + special columns, Ch.99 301/232 layer, U.S. note 52)
  EU  - EU Common External Tariff as published in the UK Online Trade Tariff 'xi' service (Northern
        Ireland applies the EU tariff); Portugal VAT from CIVA art. 18
  UK  - UK Global Tariff + preferences + import VAT from the UK Online Trade Tariff API
Rates that are not in the data are reported as 'check source' and never guessed.
"""
from __future__ import annotations

import csv
import functools
import json
import os
import re
from pathlib import Path

CHECK = "check source"
DATA = Path(os.environ.get("LANDED_DATA_DIR", Path(__file__).resolve().parent.parent / "data" / "landed"))

EU27 = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE", "IT", "LT",
        "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"]
DESTS = {"US": "United States", "PT": "Portugal (EU)", "EU": "European Union (CET only; VAT per member state)",
         "UK": "United Kingdom"}
ALIASES = {"GB": "UK", "USA": "US", "PORTUGAL": "PT", "UNITED KINGDOM": "UK"}

# Portugal mainland VAT, CIVA art. 18(1) (verified 2026-10-23 on Portal das Financas).
PT_VAT = {"standard": 23.0, "intermediate": 13.0, "reduced": 6.0,
          "source": "https://info.portaldasfinancas.gov.pt/pt/informacao_fiscal/codigos_tributarios/civa_rep/Pages/iva18.aspx",
          "note": "23% applies to goods not in Lista I (6%) or Lista II (13%) of CIVA; Azores/Madeira have own "
                  "reduced rates (check source)."}

# US HTS special-program indicators -> partner ISO codes (HTS General Note 3(c)(i)).
US_FTA = {"AU": ["AU"], "BH": ["BH"], "CL": ["CL"], "CO": ["CO"], "IL": ["IL"], "JO": ["JO"], "KR": ["KR"],
          "MA": ["MA"], "OM": ["OM"], "PA": ["PA"], "PE": ["PE"], "SG": ["SG"],
          "P": ["CR", "DO", "SV", "GT", "HN", "NI"], "P+": ["CR", "DO", "SV", "GT", "HN", "NI"],
          "S": ["MX", "CA"], "S+": ["MX", "CA"]}
US_UNILATERAL = {"A": "GSP", "A*": "GSP", "A+": "GSP (LDC)", "D": "AGOA", "E": "CBERA", "E*": "CBERA",
                 "R": "CBTPA", "J": "ATPA", "J*": "ATPA", "J+": "ATPA", "W": "Nepal preference"}
US_PROGRAM_NAME = {"S": "USMCA", "S+": "USMCA", "P": "CAFTA-DR", "P+": "CAFTA-DR"}

COMPLIANCE = [
    "Preferential rates require GENUINE origin under the agreement's rules of origin (product-specific "
    "rules, e.g. yarn-forward for apparel under USMCA/CAFTA-DR, double transformation under EU/UK GSP/EBA).",
    "Claim preference with the required proof: certificate of origin / statement on origin (REX number for "
    "EU/UK GSP), USMCA certification of origin; keep supplier declarations and production records.",
    "Transshipment or relabeling to change apparent origin is customs fraud (e.g. 19 U.S.C. 1592; EU OLAF / "
    "UK HMRC enforcement) with penalties, seizure and criminal liability.",
    "Paying the seller in crypto does NOT change duty or VAT: customs value is the transaction value "
    "converted to local currency at the official customs exchange rate.",
    "Not legal or tax advice; confirm with a licensed customs broker before importing.",
]
CRYPTO_NOTE = ("Seller-accepts-crypto filter is a placeholder: no seller data yet, so no route is excluded. "
               "Crypto payment does not change duty or VAT (customs value is converted to local currency).")


def _pct(s):
    m = re.fullmatch(r"\s*([\d.]+)\s*%\s*", s or "")
    return float(m.group(1)) if m else None


def digits(hs):
    return re.sub(r"\D", "", str(hs or ""))


@functools.lru_cache(maxsize=None)
def meta():
    return json.loads((DATA / "meta.json").read_text())


@functools.lru_cache(maxsize=None)
def origins():
    return json.loads((DATA / "origin" / "origins.json").read_text())["origins"]


@functools.lru_cache(maxsize=None)
def us_lines():
    with open(DATA / "us" / "hts_base.csv", newline="") as f:
        return list(csv.DictReader(f))


@functools.lru_cache(maxsize=None)
def us_additional():
    out = {}
    with open(DATA / "us" / "additional.csv", newline="") as f:
        for r in csv.DictReader(f):
            out.setdefault(digits(r["hts"]), []).append(r)
    return out


@functools.lru_cache(maxsize=None)
def us_note52():
    return json.loads((DATA / "us" / "note52.json").read_text())["countries"]


@functools.lru_cache(maxsize=None)
def tariff_snapshot(tariff):
    out = {}
    d = DATA / tariff
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        j = json.loads(p.read_text())
        for code, c in j["commodities"].items():
            c["fetched_at"], c["source"] = j["fetched_at"], j["source"]
            out[code] = c
    return out


def norm_dest(d):
    d = (d or "").strip().upper()
    return ALIASES.get(d, d)


def norm_origin(o):
    o = (o or "any").strip().upper()
    return {"UK": "GB", "USA": "US"}.get(o, o)


# ---------------------------------------------------------------- keyword search
def search(keyword, limit=20):
    kw = [w for w in re.findall(r"[a-z0-9][a-z0-9-]*", keyword.lower()) if len(w) > 1]
    if not kw:
        return []
    hits = {}
    for r in us_lines():
        text = (r["path"] or r["description"]).lower()
        if all(w in text for w in kw):
            h6 = digits(r["hts"])[:6]
            hits.setdefault(h6, r["path"][:160])
    for t in ("uk", "xi"):
        for code, c in tariff_snapshot(t).items():
            if all(w in re.sub("<[^>]+>", "", c["description"] or "").lower() for w in kw):
                hits.setdefault(code[:6], c["description"][:160])
    return [{"hs6": k, "description": v} for k, v in sorted(hits.items())[:limit]]


# ---------------------------------------------------------------- US
def _parse_special(raw):
    """'Free (AU,BH,...) 3.4% (KR)' -> {'AU': 'Free', ...}"""
    out = {}
    for rate, progs in re.findall(r"([^()]+?)\s*\(([^)]*)\)", raw or ""):
        for p in progs.split(","):
            out[p.strip()] = rate.strip()
    return out


def us_duty(hs, origin):
    d = digits(hs)
    lines = [r for r in us_lines() if digits(r["hts"]).startswith(d) and r["inherited"] == "False"]
    if not lines:
        return None
    out = []
    for r in lines:
        notes, srcs = [], ["https://hts.usitc.gov/search?query=" + digits(r["hts"])]
        if r["type"] == "free":
            mfn = 0.0
        elif r["type"] == "ad_valorem":
            mfn = int(r["bps"]) / 100
        else:
            mfn = None
            notes.append(f"general rate '{r['general']}' is specific/compound: {CHECK} (needs quantity)")
        rate, program = mfn, "MFN (column 1 general)"
        if origin in ("CU", "KP"):
            rate, program = None, "Column 2"
            notes.append(f"column 2 country: {CHECK}")
        special = _parse_special(r["specialRaw"])
        for code, srate in special.items():
            if origin in US_FTA.get(code, []):
                p = _pct(srate) if srate != "Free" else 0.0
                if p is not None and (rate is None or p < rate):
                    rate, program = p, f"{US_PROGRAM_NAME.get(code, code)} FTA (HTS special '{code}')"
            elif code in US_UNILATERAL:
                notes.append(f"{US_UNILATERAL[code]} ('{code}') listed: eligibility/program status {CHECK}")
        # Chapter 99 layers
        extra, extra_notes = 0.0, []
        keys = dict.fromkeys([digits(r["hts"]), digits(r["hts"])[:8]])
        for a in [a for k in keys for a in us_additional().get(k, [])]:
            if a["origin"] in (origin, "ANY") and a["type"] == "ad_valorem":
                if a["origin"] == "ANY" and origin in ("GB", "RU") and any(
                        b["program"] in (a["program"] + "-UK", a["program"] + "-Russia") and b["origin"] == origin
                        for b in us_additional().get(digits(r["hts"]), [])):
                    continue
                extra += int(a["bps"]) / 100
                extra_notes.append(f"{a['program']} {int(a['bps'])/100:g}% (HTS {a['heading']})")
        n52 = us_note52().get("EU" if origin in EU27 else origin)
        if n52 and any(x.startswith("232") for x in extra_notes):
            extra_notes.append("U.S. note 52 duty not applied: Section 232 articles excluded (9903.05.90); " + CHECK)
        elif n52 and rate is not None:
            if n52.get("kind") == "additive":
                extra += n52["add_pct"]
                extra_notes.append(f"Section 301 U.S. note 52 +{n52['add_pct']:g}% (HTS {n52['headings'][0]}); "
                                   f"exceptions {n52['exceptions']}: {CHECK}")
            elif n52.get("kind") == "floor" and rate < n52["floor_pct"]:
                extra += n52["floor_pct"] - rate
                extra_notes.append(f"U.S. note 52 floor: total {n52['floor_pct']:g}% (HTS {n52['headings'][-1]})")
            elif n52.get("kind") == "floor":
                extra_notes.append(f"U.S. note 52: column 1 rate >= {n52['floor_pct']:g}% so no extra duty")
        out.append({"line": r["hts"], "description": r["description"][:120], "program": program,
                    "duty_pct": rate, "additional_pct": extra, "additional": extra_notes,
                    "notes": notes, "sources": srcs})
    return out


# ---------------------------------------------------------------- UK / EU
def _measure_applies(m, origin, areas):
    if origin in m["excluded"]:
        return False
    if m["area"] == origin:
        return True
    return origin in areas.get(m["area"], {}).get("members", [])


def ukxi_duty(hs, origin, tariff):
    d = digits(hs)
    snap = tariff_snapshot(tariff)
    codes = [c for c in snap if c.startswith(d[:10])]
    if not codes:
        return None
    out = []
    for code in codes:
        c = snap[code]
        ms, areas = c["measures"], c["areas"]
        mfn = next((_pct(m["duty"]) for m in ms if m["type"] == "Third country duty" and m["area"] == "1011"), None)
        notes = []
        if mfn is None:
            notes.append(f"third-country duty not ad valorem: {CHECK}")
        rate, program = mfn, "MFN third-country duty"
        for m in ms:
            if m["type"] in ("Tariff preference", "Preferential tariff quota", "Customs Union Duty") \
                    and _measure_applies(m, origin, areas):
                p = _pct(m["duty"])
                label = areas.get(m["area"], {}).get("name") or m["area"]
                if p is None:
                    notes.append(f"{m['type']} '{m['duty']}' for {label}: {CHECK}")
                    continue
                if rate is None or p < rate:
                    rate = p
                    program = f"{m['type']} ({label})" + (f", quota {m['quota']}" if m["quota"] else "")
                    if m["type"] == "Preferential tariff quota":
                        notes.append("preferential quota: rate only while quota open; " + CHECK)
        extra, extra_notes = 0.0, []
        for m in ms:
            t = m["type"].lower()
            if ("additional duties" in t or "anti-dumping" in t or "countervailing" in t) \
                    and _measure_applies(m, origin, areas):
                p = _pct(m["duty"])
                if p is None or m["conditions"]:
                    extra_notes.append(f"{m['type']} '{m['duty']}': {CHECK}")
                else:
                    extra += p
                    extra_notes.append(f"{m['type']} {p:g}%")
            if ("restriction" in t or "prohibition" in t or "import control" in t) and _measure_applies(m, origin, areas):
                extra_notes.append(f"{m['type']} applies to origin {origin}: may be prohibited, {CHECK}")
            if "low-value consignment" in t:
                notes.append(f"{m['type']}: {m['duty']} per item on low-value e-commerce consignments ({CHECK})")
        vat = sorted({_pct(m["duty"]) for m in ms if m["type"] == "Value added tax" and _pct(m["duty"]) is not None})
        out.append({"line": code, "description": re.sub("<[^>]+>", "", c["description"] or "")[:120],
                    "program": program, "duty_pct": rate, "additional_pct": extra, "additional": extra_notes,
                    "vat_rates": vat, "notes": notes, "fetched_at": c["fetched_at"],
                    "sources": [f"https://www.trade-tariff.service.gov.uk/{'xi/' if tariff == 'xi' else ''}commodities/{code}"]})
    return out


# ---------------------------------------------------------------- origin side
def origin_side(origin, dest_iso):
    o = origins().get(origin)
    if not o:
        return {"export_vat": CHECK, "export_duty_pct": None, "export_duty": CHECK, "sources": [],
                "notes": [f"origin {origin} not in origin dataset: {CHECK}"]}
    ed = o["export_duty"]
    return {"export_vat": o["export_vat"].get("treatment", CHECK),
            "export_vat_basis": o["export_vat"].get("basis"),
            "export_duty_pct": ed.get("pct"), "export_duty": ed.get("status"),
            "zones": [z["name"] for z in o.get("zones", [])],
            "sources": o["export_vat"].get("sources", []) + ed.get("sources", []),
            "notes": [x for x in (ed.get("note"), o.get("rebate_note"), o.get("note")) if x]}


# ---------------------------------------------------------------- main entry
def _domestic(origin, dest):
    return (dest == "US" and origin == "US") or (dest == "UK" and origin == "GB") or \
           (dest in ("PT", "EU") and origin in EU27)


def route(hs, origin, dest, value=100.0, freight=0.0, insurance=0.0):
    lines = us_duty(hs, origin) if dest == "US" else ukxi_duty(hs, origin, "uk" if dest == "UK" else "xi")
    if not lines:
        return {"origin": origin, "status": f"HS {hs} not in {dest} snapshot: {CHECK}", "complete": False}
    side = origin_side(origin, dest)
    domestic = _domestic(origin, dest)
    cif = value + freight + insurance
    duty_base = value if dest == "US" else cif   # US: FOB transaction value; EU/UK: CIF
    results = []
    for ln in lines:
        missing = []
        if domestic:
            duty_pct, program = 0.0, ("intra-EU supply (no customs duty)" if dest in ("PT", "EU")
                                      else "domestic (no import)")
            add_pct = 0.0
        else:
            duty_pct, program, add_pct = ln["duty_pct"], ln["program"], ln["additional_pct"]
        if duty_pct is None:
            missing.append("import duty")
        duty = None if duty_pct is None else round(duty_base * (duty_pct + add_pct) / 100, 2)
        if dest == "US":
            vat_pct, vat_note = 0.0, "No federal import VAT; state/local sales or use tax may apply (not modelled)."
        elif dest == "PT":
            vat_pct, vat_note = PT_VAT["standard"], PT_VAT["note"]
        elif dest == "UK":
            rates = ln.get("vat_rates") or []
            vat_pct = max(rates) if rates else None
            vat_note = ("UK import VAT from tariff measures; other listed rates " +
                        ", ".join(f"{r:g}%" for r in rates if r != vat_pct) + " may apply (e.g. children's clothing): check footnotes") \
                if len(rates) > 1 else "UK import VAT from tariff measures."
        else:
            vat_pct, vat_note = None, "EU VAT depends on member state: " + CHECK
        if vat_pct is None:
            missing.append("import VAT")
        vat = None if vat_pct is None or duty is None else round((cif + duty) * vat_pct / 100, 2)
        exp_pct = 0.0 if domestic else side["export_duty_pct"]
        if exp_pct is None:
            missing.append("origin export duty")
        exp = round(value * (exp_pct or 0) / 100, 2)
        known = cif + exp + (duty or 0) + (vat or 0)
        results.append({
            "line": ln["line"], "description": ln["description"], "program": program,
            "duty_pct": duty_pct, "additional_pct": 0.0 if domestic else add_pct,
            "additional": [] if domestic else ln["additional"],
            "import_duty": duty if duty is not None else CHECK,
            "vat_pct": vat_pct if vat_pct is not None else CHECK,
            "import_vat": vat if vat is not None else CHECK, "vat_note": vat_note,
            "export_duty": exp if exp_pct is not None else CHECK,
            "landed_total": round(known, 2), "complete": not missing, "missing": missing,
            "notes": ln["notes"], "sources": ln["sources"]})
    best = min(results, key=lambda r: r["landed_total"])
    worst = max(results, key=lambda r: r["landed_total"])
    return {"origin": origin, "origin_name": origins().get(origin, {}).get("name", origin),
            "domestic": domestic, "landed_min": best["landed_total"], "landed_max": worst["landed_total"],
            "complete": all(r["complete"] for r in results), "best_line": best, "lines": results,
            "origin_side": side}


def landed_cost(hs, origin="any", destination="US", value=100.0, freight=0.0, insurance=0.0,
                seller_accepts_crypto=False):
    dest = norm_dest(destination)
    if dest == "SPACE":
        return space_route(None, value)
    if dest not in DESTS:
        return {"error": f"destination must be one of {sorted(DESTS) + ['SPACE']} (phase 1)"}
    d = digits(hs)
    if not d:
        m = search(str(hs))
        return {"query": hs, "matches": m, "note": "Keyword search: pick an HS code and call again."
                if m else "No match in snapshots; try an HS code."}
    if len(d) < 4:
        return {"error": "Provide at least 4 HS digits."}
    o = norm_origin(origin)
    cands = list(origins()) if o == "ANY" else [o]
    routes = [route(d, c, dest, float(value), float(freight), float(insurance)) for c in cands]
    ranked = sorted(routes, key=lambda r: (r.get("landed_min") is None, r.get("landed_min") or 0,
                                          not r.get("complete")))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return {"hs": d, "destination": dest, "destination_name": DESTS[dest], "value": value,
            "freight": freight, "insurance": insurance,
            "valuation": "US duty on transaction (FOB) value; EU/UK duty on CIF; VAT on CIF + duty.",
            "routes": ranked, "crypto_filter": {"requested": bool(seller_accepts_crypto), "note": CRYPTO_NOTE},
            "compliance": COMPLIANCE, "data": meta().get("destinations", {}).get(dest, {}),
            "legend": f"'{CHECK}' = rate not in our official snapshot; never guessed."}


# ---------------------------------------------------------------- compare to my plan
def compare_plan(hs, origin, destination="US", value=100.0, freight=0.0, insurance=0.0, qty=None,
                 weight_kg=None, top=5):
    """User's planned route beside the cheapest legal alternatives, with savings ($ and %)."""
    if norm_dest(destination) == "SPACE":
        return space_route(weight_kg, value)
    plan = landed_cost(hs, origin, destination, value, freight, insurance)
    if "routes" not in plan:
        return plan
    allr = landed_cost(hs, "any", destination, value, freight, insurance)
    p = plan["routes"][0]
    if "landed_min" not in p:
        return {"plan": p, "error": "plan route not computable: " + CHECK}
    alts = []
    for r in allr["routes"]:
        if r["origin"] == p["origin"] or "landed_min" not in r:
            continue
        save = round(p["landed_min"] - r["landed_min"], 2)
        alts.append({"origin": r["origin"], "origin_name": r["origin_name"], "landed": r["landed_min"],
                     "program": r["best_line"]["program"], "complete": r["complete"],
                     "missing": r["best_line"]["missing"], "savings": save,
                     "savings_pct": round(100 * save / p["landed_min"], 2) if p["landed_min"] else None})
    alts.sort(key=lambda a: a["landed"])
    return {"hs": plan["hs"], "destination": plan["destination"],
            "plan": {"origin": p["origin"], "landed": p["landed_min"], "complete": p["complete"],
                     "program": p["best_line"]["program"], "missing": p["best_line"]["missing"],
                     "qty": qty, "weight_kg": weight_kg},
            "alternatives": alts[:top],
            "note": ("Savings compare sourced components only; routes marked complete=false have 'check source' "
                     "gaps. Qty/weight are recorded but specific (per-unit/kg) duties are not computed: " + CHECK
                     + ". Switching origin requires genuinely sourcing from that country (rules of origin); "
                     "relabeling or transshipment is fraud."),
            "compliance": COMPLIANCE, "crypto_note": CRYPTO_NOTE}


# ---------------------------------------------------------------- space
SPACE_NOTES = [
    "No customs tariff or import VAT applies in orbit: space is not a customs territory. Duties/VAT can still "
    "apply when goods are imported into the launch country (e.g. shipping a satellite from abroad to a US "
    "launch site) and on anything returned to Earth: check source.",
    "Export controls are NOT computed: spacecraft and related items may be controlled under ITAR (USML Cat. XV) "
    "or EAR (CCL, e.g. 9A515); launching from or exporting to another country can need a license. "
    "Also launch/spectrum licensing (FAA/FCC or national equivalents). Get export-control counsel.",
    "Paying in crypto does not change any of this.",
]


@functools.lru_cache(maxsize=None)
def launch_prices():
    return json.loads((DATA / "space" / "launch_prices.json").read_text())


def space_route(weight_kg=None, value=None):
    out = []
    for p in launch_prices()["providers"]:
        price = CHECK
        if weight_kg is not None and p.get("per_kg_above_base") is not None and p.get("base_price") is not None:
            w = float(weight_kg)
            if p.get("max_kg_per_port") and w > p["max_kg_per_port"]:
                price = f"over {p['max_kg_per_port']} kg per port: {CHECK}"
            else:
                price = p["base_price"] + max(0.0, w - p["base_kg"]) * p["per_kg_above_base"]
        out.append({"provider": p["provider"], "offer": p["offer"], "status": p["status"],
                    "launch_price_usd": price,
                    "effective_per_kg": round(price / float(weight_kg), 2)
                    if isinstance(price, float) and weight_kg else CHECK,
                    "per_kg_above_base": p.get("per_kg_above_base", CHECK) or CHECK,
                    "excludes": p.get("excludes"), "official": p.get("official"), "sources": p.get("sources"),
                    "as_of": p.get("as_of", CHECK)})
    out.sort(key=lambda r: (not isinstance(r["launch_price_usd"], float), r["launch_price_usd"]
                            if isinstance(r["launch_price_usd"], float) else 0))
    return {"destination": "SPACE", "weight_kg": weight_kg, "goods_value": value, "tariff": "none in orbit",
            "launch_options": out, "notes": SPACE_NOTES, "policy": launch_prices()["policy"],
            "retrieved": launch_prices()["retrieved"]}


# HS prefixes whose goods are often export-controlled (spacecraft, avionics, optics, radio, navigation).
# Text flag only: classification under ITAR (USML) / EAR (CCL) depends on the item, not the HS code.
LIKELY_CONTROLLED_HS = {"8802": "spacecraft/satellites (USML XV / ECCN 9A515)", "8803": "spacecraft parts",
                        "8526": "radar/radio navigation", "8525": "transmitters/cameras", "9013": "lasers/optics",
                        "9014": "navigation instruments", "8542": "integrated circuits (rad-hard)",
                        "9301": "military weapons", "8710": "armoured vehicles", "3602": "explosives/propellants"}


def export_control_flag(hs):
    """Text-only hint for SpaceLog: is this item likely ITAR/EAR-relevant? Not a determination."""
    d = re.sub(r"\D", "", str(hs))
    hit = next((v for k, v in LIKELY_CONTROLLED_HS.items() if d.startswith(k)), None)
    return {"hs": d, "likely_controlled": bool(hit), "reason": hit,
            "note": "Text flag only, not a classification. Self-attest a license or 'not required' after checking "
                    "USML (22 CFR 121) / CCL (15 CFR 774) with counsel."}
