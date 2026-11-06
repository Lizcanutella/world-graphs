"""Unit corrections: which NE rows carry the wrong code or name, decided by rule.

NE admin-1 rows are the vertices' raw material (rows sharing a code and name dissolve into one
vertex, see maps_geo.build._unit_keys). A row is relabelled when two independent sources agree
against NE:

  geoBoundaries  the gB unit holding most (>= ROW_SHARE) of the row carries another code c'
  Wikidata       a point of an item holding c' lies in the row (within POINT_NEAR_M), while
                 the points of NE's own code c all lie elsewhere (c must have a point:
                 Wikidata has to place c positively, or a capital city NE draws as its own
                 vertex would be folded into its province)

Two consequences keep the result consistent. A row whose own code another relabel claims,
and whose gB code is left vacant, completes the permutation (Guyana's Demerara-Mahaica row
has no Wikidata point near it but is the last piece of a ten-region shuffle). A relabel onto
a code still held by a row that gB places elsewhere is dropped: the rule never merges units.

This one rule covers every kind of label defect the first review patched by hand: label
swaps (Ecuador's Napo and Tungurahua), shuffles (Guyana, Eritrea), code swaps (Afghanistan's
Paktika and Paktiya) and hidden units (Croatia's Pozega-Slavonia filed as a second HR-12 row,
which then becomes its own vertex).

The new name: the name the code carried on its NE row when that row is itself relabelled
away (names travel with codes in a shuffle); NE's own name when it already matches gB (a
code-only error); otherwise gB's name when it matches Wikidata's label, else Wikidata's.

Hand decisions (data/maps/decisions.json, `relabel`) are applied first and win over the rule
for their rows; an entry {"ne_id", "keep": true} vetoes the rule for one row.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

ROW_SHARE = 0.5
POINT_NEAR_M = 2000.0
DECISIONS_PATH = "data/maps/decisions.json"
WD_POINTS = "data/cache/wikidata/p300_codes.json"


def load_decisions(path: str = DECISIONS_PATH) -> dict:
    if not os.path.exists(path):
        return {"relabel": [], "edges": []}
    d = json.load(open(path, encoding="utf-8"))
    d.setdefault("relabel", []); d.setdefault("edges", [])
    return d


def wikidata_points() -> dict:
    """{code: [(qid, (lon, lat) | None, label, rank)]} from the pinned P300 snapshot."""
    out = defaultdict(list)
    for r in json.load(open(WD_POINTS, encoding="utf-8")):
        c = r.get("coord", "")
        ll = tuple(map(float, c[6:-1].split())) if c.startswith("Point(") else None
        out[r["code"]].append((r["item"].rsplit("/", 1)[-1], ll, r.get("label"),
                               r["rank"].rsplit("#", 1)[-1]))
    return out


def apply_hand(gdf, decisions: dict):
    """NE frame with the hand `relabel` entries applied (fails loudly when NE moved)."""
    from maps_geo.overrides import Overrides, apply_relabels
    entries = [e for e in decisions.get("relabel", []) if "set" in e]
    return apply_relabels(gdf, Overrides(relabel=entries)) if entries else gdf


def points_in_rows(block, pts: dict, crs: str) -> dict:
    """{ne_id: set of codes with a Wikidata point within POINT_NEAR_M of that row}."""
    import geopandas as gpd
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    from .geom import polygonal
    rows = [polygonal(g) for g in gpd.GeoSeries(list(block.geometry), crs=4326).to_crs(crs)]
    ids = list(block["ne_id"].astype(str))
    located = [(code, ll) for code, items in pts.items() for _, ll, _, _ in items if ll]
    if not located:
        return {}
    minx, miny, maxx, maxy = gpd.GeoSeries(list(block.geometry), crs=4326).total_bounds
    located = [(c, ll) for c, ll in located
               if minx - 1 <= ll[0] <= maxx + 1 and miny - 1 <= ll[1] <= maxy + 1]
    P = gpd.GeoSeries([Point(*ll) for _, ll in located], crs=4326).to_crs(crs)
    tree = STRtree(rows)
    out = defaultdict(set)
    for (code, _), p in zip(located, P):
        for j in tree.query(p.buffer(POINT_NEAR_M)):
            j = int(j)
            if rows[j].distance(p) <= POINT_NEAR_M:
                out[ids[j]].add(code)
    return out


def propose(rows: list, in_row: dict, pts: dict, protected: set) -> list:
    """Rule relabels for one country.

    `rows`: [{ne_id, code, name, gb_code, gb_name, share}] for every NE row (the pairs stage's
    row check). `in_row`: points_in_rows output. `protected`: ne_ids with a hand decision.
    """
    from .pairs import same_name
    located = {c for c, items in pts.items() if any(ll for _, ll, _, _ in items)}
    moves = {}
    for r in rows:
        c, c2 = r["code"], r["gb_code"]
        if r["ne_id"] in protected or not c2 or c2 == c or r["share"] < ROW_SHARE:
            continue
        here = in_row.get(r["ne_id"], set())
        if c2 in here and c in located and c not in here:
            moves[r["ne_id"]] = r
    by_code = defaultdict(list)
    for r in rows:
        by_code[r["code"]].append(r)
    rule = dict.fromkeys(moves, "gb_and_wikidata_against_ne")

    def firm(r):
        return r["gb_code"] and r["gb_code"] != r["code"] and r["share"] >= ROW_SHARE \
            and r["ne_id"] not in protected

    changed = True
    while changed:
        changed = False
        claimed = {m["gb_code"] for m in moves.values()}
        # Completion: a row whose own code another move claims, and whose gB code is vacated
        # (every holder moved) and unclaimed, is the remaining piece of the permutation.
        for r in rows:
            if r["ne_id"] in moves or not firm(r):
                continue
            c2 = r["gb_code"]
            vacated = by_code.get(c2, [])
            if r["code"] in claimed and c2 not in claimed and vacated and \
                    all(h["ne_id"] in moves for h in vacated):
                moves[r["ne_id"]], rule[r["ne_id"]] = r, "completes_permutation"
                changed = True
                break
        # No silent merges: a move onto a code still held by a row gB places elsewhere.
        for nid, m in list(moves.items()):
            if any(h["ne_id"] not in moves and h["gb_code"] and h["gb_code"] != m["gb_code"]
                   for h in by_code.get(m["gb_code"], [])):
                del moves[nid]
                changed = True

    out = []
    for nid, r in moves.items():
        c2 = r["gb_code"]
        holders = by_code.get(c2, [])
        moved_away = [h for h in holders if h["ne_id"] in moves and h["name"]]
        staying = [h for h in holders if h["ne_id"] not in moves and h["name"]]
        if same_name(r["name"], r["gb_name"]):
            name, why = r["name"], "code-only error: NE's name matches gB"
        elif moved_away:
            name, why = moved_away[0]["name"], "name travels with the code (shuffle)"
        elif staying:
            name, why = staying[0]["name"], "piece of the NE unit already carrying the code"
        else:
            wd = next((lab for _, ll, lab, _ in pts.get(c2, []) if ll and lab), None)
            if r["gb_name"] and wd and same_name(r["gb_name"], wd):
                name, why = r["gb_name"], "gB name (matches Wikidata)"
            else:
                name, why = wd or r["gb_name"] or c2, "Wikidata label"
        out.append({"ne_id": nid, "was": {"iso_3166_2": r["code"], "name": r["name"]},
                    "set": {"iso_3166_2": c2, "name": name}, "rule": rule[nid],
                    "evidence": {"gb_code": c2, "gb_name": r["gb_name"], "gb_share": r["share"],
                                 "wikidata_point_in_row": c2 in in_row.get(nid, set()),
                                 "name_from": why}})
    return sorted(out, key=lambda e: e["ne_id"])


def vertex_names(block, codes, roster) -> dict:
    """{vertex: display name}: NE's name, else the ISO roster's; repeats are repaired or told
    apart by maps_geo.build._disambiguate (an NE repeat whose code has another current ISO
    name takes that name: Wirral, shipped as a second "Halton"; true namesakes get NE's unit
    type, then the code)."""
    from maps_geo.build import _disambiguate, _ne_label
    by_code = {u.code: u for u in roster}
    codes = list(codes)
    labels = [_ne_label(block, c) or (by_code[c].name if c in by_code else c) for c in codes]
    return dict(zip(codes, _disambiguate(labels, codes, by_code, block)))
