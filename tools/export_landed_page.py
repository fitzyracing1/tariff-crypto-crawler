"""Export precomputed landed-cost rates (percentages, not totals) for the static landed.html page.

Usage: python tools/export_landed_page.py OUT.json
For every HS6 in the UK/XI snapshots, and every origin in origins.json, for US/PT/UK.
The page recomputes totals for the user's value/freight in the browser with the same formulas.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crawler import landed_cost as lc  # noqa: E402


def compact(rt):
    if "best_line" not in rt:
        return {"o": rt["origin"], "status": rt["status"]}
    b = rt["best_line"]
    lines = rt["lines"]
    num = lambda v: v if isinstance(v, (int, float)) else None  # noqa: E731
    return {"o": rt["origin"], "n": rt["origin_name"], "dom": rt["domestic"],
            "line": b["line"], "prog": b["program"], "d": num(b["duty_pct"]), "a": b["additional_pct"],
            "v": num(b["vat_pct"]), "x": None if b["export_duty"] == lc.CHECK else 0,
            "add": b["additional"], "notes": b["notes"] + [b["vat_note"]], "miss": b["missing"],
            "nlines": len(lines), "dmax": max((l["duty_pct"] or 0) + l["additional_pct"] for l in lines),
            "ov": rt["origin_side"]["export_vat"], "src": b["sources"][:1] + rt["origin_side"]["sources"][:2]}


def main(out):
    hs6 = set()
    for t in ("uk", "xi"):
        hs6 |= {c[:6] for c in lc.tariff_snapshot(t)}
    desc = {}
    for t in ("uk", "xi"):
        for c, v in lc.tariff_snapshot(t).items():
            desc.setdefault(c[:6], v["description"])
    for r in lc.us_lines():
        d = lc.digits(r["hts"])[:6]
        if d in hs6 and r["inherited"] == "False":
            desc[d] = r["path"][:140]
    res = {}
    for h in sorted(hs6):
        res[h] = {"desc": desc.get(h, ""), "dest": {}}
        for dest in ("US", "PT", "UK"):
            r = lc.landed_cost(h, "any", dest)
            res[h]["dest"][dest] = [compact(x) for x in r["routes"]]
    m = lc.meta()
    doc = {"generated": "2026-10-23", "valuation": "US duty on FOB value; PT/UK duty on CIF; VAT on CIF+duty",
           "compliance": lc.COMPLIANCE, "space": dict(lc.launch_prices(), notes=lc.SPACE_NOTES), "crypto": lc.CRYPTO_NOTE, "pt_vat": lc.PT_VAT,
           "meta": m.get("destinations", {}), "hs": res}
    Path(out).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
    print(len(res), "HS6 codes ->", out)


if __name__ == "__main__":
    main(sys.argv[1])
