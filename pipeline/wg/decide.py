"""Stage 3: decide every edge from three independent votes, by fixed rules.

    uv run python -m wg.decide   -> data/build/graphs/<ISO>.json, data/audit/review.csv,
                                    data/audit/decide_summary.json

Votes per candidate pair (from wg.pairs):
  ne    yes    NE shares more than EPS_M of border (geodesic, after lake clipping)
        no     a point contact, or apart
  gb    yes    gB border estimate (gb_len_m - gb_sea_m - 2*tol) >= GB_BORDER_M. Only border
               over land and rivers counts; what is sea is NE's coastline (wg.pairs.sea_mask)
        no     estimate <= GB_NONE_M; `apart` when the redraws are also >= GB_APART_M apart
        short  in between (too short to call)
        -      not usable: a unit gB does not identify (quality < Q_MIN), or a code-matched
               unit whose gB area or shape differs from NE's (another vintage of the unit)
  p47   Wikidata P47 lists the pair. Includes maritime neighbours, and is incomplete, so it
        only breaks ties between the two maps.

Rules, first match wins:
  hand              data/maps/decisions.json `edges` entry for the pair (reason required)
  ne_and_gb         ne yes, gb yes                      -> edge
  ne_and_gb_none    ne no,  gb no/short-or-unusable     -> no edge (NE stands)
  ne_uncheckable    ne yes, gb unusable                 -> edge (single source: NE)
  gb_and_p47        ne no,  gb yes, p47                 -> edge (NE collapsed or lost a border)
  gb_and_p47_apart  ne yes, gb apart, not p47           -> no edge (NE draws a border that the
                                                           other two sources lack)
  ne_and_p47        ne yes, gb no or short, p47         -> edge
  ne_short          ne yes, gb short, not p47           -> edge (NE stands; gB cannot refute)
  review            anything else: two against one with the weak vote deciding it the
                    wrong way, or a point contact. NE stands, and the pair is listed in
                    review.csv until a hand decision settles it.
The old overrides.json corrections are not inputs: the rules reproduce most of them, and the
rest are hand decisions with their original evidence.
"""
from __future__ import annotations

import csv
import glob
import json
import os
from collections import Counter

from .audit import AREA_BAND, IOU_MIN, Q_MIN

EPS_M = 100.0
GB_NONE_M = 100.0
GB_BORDER_M = 500.0
GB_APART_M = 1000.0
PAIRS = "data/audit/pairs"
OUT = "data/build/graphs"
AUDIT = "data/audit"


def vintage_units(gb: dict) -> set:
    """Code-matched units whose gB polygon is another drawing of the unit (area or shape)."""
    out = set()
    for k, by in gb.get("matched_by", {}).items():
        if by != "code":
            continue
        r = gb["area_ratio"].get(k)
        if (r is not None and not AREA_BAND[0] <= r <= AREA_BAND[1]) or gb["iou"].get(k, 1) < IOU_MIN:
            out.add(k)
    return out


def votes(p: dict, tol: float, vintage: set) -> dict:
    ne = "yes" if p["ne_contact"] == "line" and p["ne_len_m"] > EPS_M else \
         ("point" if p["ne_contact"] != "none" else "no")
    gb = None
    if p.get("gb_len_m") is not None and min(p.get("q") or [0]) >= Q_MIN \
            and p["u"] not in vintage and p["v"] not in vintage:
        est = max(p["gb_len_m"] - (p.get("gb_sea_m") or 0.0) - 2 * tol, 0.0)
        if est >= GB_BORDER_M:
            gb = "yes"
        elif est <= GB_NONE_M:
            gb = "apart" if (p.get("gb_gap_m") or 0) >= GB_APART_M else "no"
        else:
            gb = "short"
    return {"ne": ne, "gb": gb, "p47": bool(p["p47"])}


def rule(v: dict) -> tuple:
    """(edge, rule name) for one pair's votes; rule 'review' keeps NE's answer."""
    ne, gb, p47 = v["ne"] == "yes", v["gb"], v["p47"]
    if ne and gb == "yes":
        return True, "ne_and_gb"
    if ne and gb is None:
        return True, "ne_uncheckable"
    if not ne and gb in ("no", "apart", None):
        return False, "ne_and_gb_none"
    if not ne and gb == "yes" and p47:
        return True, "gb_and_p47"
    if ne and gb == "apart" and not p47:
        return False, "gb_and_p47_apart"
    if ne and gb in ("no", "apart", "short") and p47:
        return True, "ne_and_p47"
    if ne and gb == "short":
        return True, "ne_short"
    if not ne and gb == "short":
        return False, "ne_and_gb_none" if not p47 else "review"
    return ne, "review"


def decide_country(d: dict, hand: dict) -> tuple:
    gb = d.get("gb") or {}
    vint = vintage_units(gb)
    tol = d["gb_tol_m"]
    edges, review, counts = [], [], Counter()
    seen = set()
    for p in d["pairs"]:
        key = (p["u"], p["v"])
        seen.add(key)
        v = votes(p, tol, vint)
        edge, why = rule(v)
        h = hand.get(key)
        if h is not None:
            edge, why = h["edge"], "hand"
        counts[why] += 1
        rec = {"u": p["u"], "v": p["v"], "rule": why, "votes": v,
               "ne_len_m": p["ne_len_m"], "gb_len_m": p.get("gb_len_m"),
               "gb_gap_m": p.get("gb_gap_m")}
        if h is not None:
            rec["reason"] = h["reason"]
        if edge:
            edges.append(rec)
        if why == "review":
            review.append(dict(rec, iso=d["iso"], kept=edge,
                               release=";".join(p["release"]) if p["release"] else ""))
    missing = [k for k in hand if k not in seen]
    if missing:
        raise ValueError(f"{d['iso']}: hand decisions for pairs that are not candidates: {missing}")
    graph = {"iso": d["iso"], "n": d["n"],
             "nodes": [{"code": k, "name": d.get("vertices", {}).get(k)} for k in sorted(d["vertices"])],
             "relabels": d.get("relabels", []), "edges": edges, "rules": dict(counts),
             "gb": {k: gb.get(k) for k in ("level", "year", "source", "license", "boundaryID")} if gb else None}
    return graph, review


def main():
    from .units import load_decisions
    dec = load_decisions()
    hand_by_iso = {}
    for e in dec["edges"]:
        if "reason" not in e or "edge" not in e:
            raise ValueError(f"hand edge decision needs 'edge' and 'reason': {e}")
        hand_by_iso.setdefault(e["iso"], {})[tuple(sorted((e["u"], e["v"])))] = e
    os.makedirs(OUT, exist_ok=True)
    reviews, tot, per = [], Counter(), []
    for f in sorted(glob.glob(os.path.join(PAIRS, "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        g, r = decide_country(d, hand_by_iso.get(d["iso"], {}))
        json.dump(g, open(os.path.join(OUT, f"{d['iso']}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
        reviews += r
        tot.update(g["rules"])
        per.append({"iso": d["iso"], "n": g["n"], "m": len(g["edges"]), "relabels": len(g["relabels"]),
                    **{k: g["rules"].get(k, 0) for k in ("review", "ne_uncheckable")}})
    with open(os.path.join(AUDIT, "review.csv"), "w", newline="", encoding="utf-8") as fh:
        cols = ["iso", "u", "v", "kept", "ne_len_m", "gb_len_m", "gb_gap_m", "release"]
        w = csv.DictWriter(fh, fieldnames=cols + ["ne", "gb", "p47"])
        w.writeheader()
        for r in reviews:
            w.writerow({**{c: r[c] for c in cols}, **r["votes"]})
    edges = sum(p["m"] for p in per)
    s = {"countries": len(per), "vertices": sum(p["n"] for p in per), "edges": edges,
         "relabelled_rows": sum(p["relabels"] for p in per), "rules": dict(tot),
         "single_source_share": round(tot["ne_uncheckable"] / edges, 4) if edges else None}
    json.dump(s, open(os.path.join(AUDIT, "decide_summary.json"), "w"), indent=1)
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
