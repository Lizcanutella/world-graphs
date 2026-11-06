"""NE vs geoBoundaries audit over the pairs tables.

    uv run python -m wg.audit    -> data/audit/{countries.csv, disagreements.csv, summary.json}

Bands for the gB border estimate (gb_len_m minus the 2*tol end noise):
  none   <= GB_NONE_M         gB shows no border (or only a point contact)
  short  between              too short to call either way
  border >= GB_BORDER_M       gB shows a real border

The audit judges the PUBLISHED graph (NE geometry plus pinned overrides), since that is what
users get; NE's raw contact and length are kept on each row. A pair is `checked` when gB
identifies both units (unit quality >= Q_MIN). Classes:
  agree_edge     published edge and gB border
  agree_non      not an edge and no gB border
  ne_only        published edge, gB none         -> possible false edge
  gb_only        gB border, not an edge          -> possible missing edge
  short          gB border in the ambiguous band
  unchecked      a unit is not identified in gB, or the country has no gB layer

Each disagreement also says which side Wikidata P47 takes ("p47_sides_with"). P47 includes
maritime neighbours, so it is a weak third vote: it can side with a gB-only border that runs
across water, never the other way round.

Unit flags (units.csv), one row per flagged NE unit:
  merged         NE rows dissolved into this vertex sit in different gB units (a unit NE
                 mislabelled, e.g. Croatia's Pozega-Slavonia filed as a second HR-12)
  code           a row sits in a gB unit of the same name but another code (a code error)
  label          a row sits in a gB unit of another name and code (the datasets disagree on
                 what the polygon is; needs a third source)
  area           code-matched, but the gB unit's area is outside AREA_BAND times NE's
  shape          code-matched, but IoU with gB < IOU_MIN
  unidentified   gB identifies the unit with quality < Q_MIN
  orphan_codes   (per country) gB units whose code NE never uses, and the NE unit holding them
"""
from __future__ import annotations

import csv
import glob
import json
import os
from collections import Counter

GB_NONE_M = 100.0
GB_BORDER_M = 500.0
Q_MIN = 0.8
AREA_BAND = (0.67, 1.5)
IOU_MIN = 0.5
OUT = "data/audit"


def classify(p: dict, tol: float) -> str:
    if p.get("gb_len_m") is None or min(p.get("q") or [0]) < Q_MIN:
        return "unchecked"
    gb = max(p["gb_len_m"] - 2 * tol, 0.0)
    ne_edge = p["release"] is not None
    if GB_NONE_M < gb < GB_BORDER_M:
        return "short"
    gb_edge = gb >= GB_BORDER_M
    if ne_edge and gb_edge:
        return "agree_edge"
    if not ne_edge and not gb_edge:
        return "agree_non"
    return "ne_only" if ne_edge else "gb_only"


def unit_flags(d: dict) -> dict:
    gb = d.get("gb") or {}
    if not gb:
        return {}
    flags = {}
    for k, q in gb["unit_quality"].items():
        f = []
        f += (gb.get("rows", {}).get(k) or {}).get("flags", [])
        if gb["matched_by"].get(k) == "code":
            r = gb["area_ratio"].get(k)
            if r is not None and not AREA_BAND[0] <= r <= AREA_BAND[1]:
                f.append("area")
            if gb["iou"].get(k, 1) < IOU_MIN:
                f.append("shape")
        if q < Q_MIN:
            f.append("unidentified")
        if f:
            flags[k] = f
    return flags


def orphan_codes(d: dict) -> list:
    gb = d.get("gb") or {}
    ne_codes = {k.split(":", 1)[0] for k in gb.get("unit_quality", {})}
    return [u for u in gb.get("units_list", []) if u["code"] and u["code"] not in ne_codes]


def main():
    rows, dis, units = [], [], []
    tot = Counter()
    for f in sorted(glob.glob(os.path.join(OUT, "pairs", "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        tol = d["gb_tol_m"]
        c = Counter()
        flags = unit_flags(d)
        gbd = d.get("gb") or {}
        orph = orphan_codes(d)
        for k, f in flags.items():
            units.append({"iso": d["iso"], "unit": k, "flags": ";".join(f),
                          "matched_by": gbd["matched_by"].get(k), "iou": gbd["iou"].get(k),
                          "area_ratio": gbd["area_ratio"].get(k),
                          "quality": gbd["unit_quality"].get(k),
                          "rows": json.dumps((gbd.get("rows", {}).get(k) or {}).get("rows", []), ensure_ascii=False),
                          "orphans_held": ";".join(f"{u['code']} {u['name']}" for u in orph
                                                   if u["owner"] == k)})
        for p in d["pairs"]:
            k = classify(p, tol)
            ne_edge = p["release"] is not None
            c[k] += 1
            if ne_edge:
                c["ne_edges"] += 1
                c["ne_edges_checked"] += k not in ("unchecked",)
                if p["release"] == ["wikidata_code"]:
                    c["p47_only_edges"] += 1
                    c["p47_only_checked"] += k not in ("unchecked",)
                    c["p47_only_ne_only"] += k == "ne_only"
            if k in ("ne_only", "gb_only"):
                dis.append({"iso": d["iso"], "class": k, "u": p["u"], "v": p["v"],
                            "ne_contact": p["ne_contact"], "ne_len_m": p["ne_len_m"],
                            "ne_gap_m": p["ne_gap_m"],
                            "gb_est_m": round(max(p["gb_len_m"] - 2 * tol, 0.0), 1),
                            "gb_gap_m": p["gb_gap_m"], "q": min(p["q"]), "p47": p["p47"],
                            "p47_sides_with": ("ne" if p["p47"] == (k == "ne_only") else "gb"),
                            "unit_flags": ";".join(sorted(set(flags.get(p["u"], []) + flags.get(p["v"], [])))),
                            "release": ";".join(p["release"]) if p["release"] else ""})
        gb = d.get("gb") or {}
        checked = c["agree_edge"] + c["agree_non"] + c["ne_only"] + c["gb_only"]
        rows.append({"iso": d["iso"], "n": d["n"], "gb_level": gb.get("level", ""),
                     "gb_units": gb.get("units", ""), "gb_year": gb.get("year", ""),
                     "gb_quality": gb.get("quality", ""),
                     "poor_units": sum(q < Q_MIN for q in (gb.get("unit_quality") or {}).values()),
                     "ne_edges": c["ne_edges"],
                     "coverage": round(c["ne_edges_checked"] / c["ne_edges"], 3) if c["ne_edges"] else "",
                     "agree_edge": c["agree_edge"], "agree_non": c["agree_non"],
                     "ne_only": c["ne_only"], "gb_only": c["gb_only"], "short": c["short"],
                     "unchecked": c["unchecked"],
                     "flagged_units": len(flags), "orphan_codes": len(orph),
                     "disagree_rate": round((c["ne_only"] + c["gb_only"]) / checked, 4) if checked else "",
                     "gb_source": gb.get("source", ""), "gb_license": gb.get("license", "")})
        tot.update(c)
    with open(os.path.join(OUT, "countries.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    with open(os.path.join(OUT, "disagreements.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(dis[0]) if dis else ["iso"])
        w.writeheader(); w.writerows(sorted(dis, key=lambda r: (r["iso"], r["class"], r["u"])))
    with open(os.path.join(OUT, "units.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(units[0]) if units else ["iso"])
        w.writeheader(); w.writerows(units)
    summary = {"bands_m": {"none": GB_NONE_M, "border": GB_BORDER_M}, "q_min": Q_MIN,
               "countries": len(rows),
               "countries_with_gb": sum(1 for r in rows if r["gb_level"]),
               "totals": dict(tot),
               "flagged_units": dict(Counter(f for u in units for f in u["flags"].split(";"))),
               "disagreements_by_p47": dict(Counter(f"{r['class']} / p47 sides with {r['p47_sides_with']}" for r in dis)),
               "disagreements_touching_flagged_units": sum(bool(r["unit_flags"]) for r in dis)}
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
