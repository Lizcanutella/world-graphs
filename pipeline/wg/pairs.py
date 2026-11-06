"""Stage 2: measure every candidate pair of units in every independent geometry.

    uv run python -m wg.pairs [--iso CO US ...] [--jobs 4]   -> data/audit/pairs/<ISO>.json

A candidate pair is any two NE units of one country that come within NE_NEAR_M of each other
in Natural Earth, or whose geoBoundaries redraws come within GB_TOL_M. Edges and non-edges
are measured the same way, and nothing is decided here: the output is the raw table the
decide stage (and the audit report) read.

Per pair:
  ne_contact   'line' | 'point' | 'none'   exact NE topology after lake clipping (as the build)
  ne_len_m     geodesic shared NE border, m (the build's edge rule is ne_len_m > 100)
  ne_gap_m     NE distance between the units, m (0 when they touch)
  gb_len_m     length of gB border between the two redraws: min over both directions of the
               boundary of one within GB_TOL_M of the other (point contacts read ~2*GB_TOL_M)
  gb_sea_m     the part of gb_len_m lying over NE's ocean or a lake over 500 km2 (sea_mask):
               NE's coastline decides what is sea, so rivers count and estuaries do not
  gb_gap_m     distance between the gB redraws, m
  q            [unit quality u, unit quality v] (see wg.geom.match); below 0.8 the gB reading
               of that unit is unreliable
  release      the edge's sources in the published release, or null if it is not an edge
  p47          Wikidata P47 lists the pair (pinned ISO-code snapshot)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

NE_NEAR_M = 2000.0
GB_TOL_M = 50.0
GB_SIMPLIFY_M = 10.0
BIG_FILE = 300 * 2**20          # bytes; larger gB files are read feature by feature
BIG_MIN_PART_DEG2 = 1e-4        # ~0.4 km2 at 70N: islets dropped from huge features
BIG_SIMPLIFY_DEG = 1e-4         # ~11 m of latitude, less of longitude: finer than GB_SIMPLIFY_M
OUT_DIR = "data/audit/pairs"
RELEASE = "../data/countries"

_STATE = {}


def _shared():
    """Inputs every country needs, loaded once per worker process. NE is raw plus the hand
    relabels; the rule relabels are decided per country (wg.units)."""
    if not _STATE:
        import geopandas as gpd
        from maps_geo.curated import load_snapshot
        from maps_geo.landmask import water_mask
        from .units import apply_hand, load_decisions, wikidata_points
        dec = load_decisions()
        a1 = gpd.read_file("data/naturalearth/ne_10m_admin_1_states_provinces.shp")
        _STATE.update(a1=apply_hand(a1, dec), decisions=dec,
                      protected={str(e["ne_id"]) for e in dec["relabel"]},
                      water=water_mask("data/naturalearth", min_area_km2=500.0),
                      ocean=gpd.read_file("data/naturalearth/ne_10m_ocean.shp").geometry.union_all(),
                      p47=load_snapshot().pairs, pts=wikidata_points(),
                      v01_relabelled={str(e["ne_id"]) for e in
                                      json.load(open("data/maps/overrides.json"))["relabel"]})
    return _STATE


def sea_mask(S, bbox):
    """NE 10m ocean plus the lakes over 500 km2, cut to the country's bbox (lon/lat)."""
    from shapely.geometry import box
    b = box(*bbox).buffer(1.0)
    parts = [S["ocean"].intersection(b)]
    if S["water"] is not None:
        parts.append(S["water"].intersection(b))
    from shapely.ops import unary_union
    return unary_union(parts)


def _lighten(g):
    """Simplify one huge gB feature cheaply: drop parts under BIG_MIN_PART_DEG2 (Arctic islets
    that touch nothing), Douglas-Peucker each remaining part, and repair. Topology-preserving
    simplification of Nunavut's multi-million-vertex geometry did not finish in two hours."""
    from shapely.geometry import MultiPolygon
    from .geom import polygonal
    parts = [p for p in getattr(g, "geoms", [g]) if p.area >= BIG_MIN_PART_DEG2]
    parts = [polygonal(p.simplify(BIG_SIMPLIFY_DEG, preserve_topology=False)) for p in parts]
    return polygonal(MultiPolygon([q for p in parts for q in getattr(p, "geoms", [p]) if not q.is_empty]))


def _stream_big_geojson(path: str):
    """Read a gB GeoJSON too big to hold at full resolution (Canada ADM1 is 633 MB on a 5 GB
    machine), one feature at a time, simplifying each at BIG_SIMPLIFY_DEG (~10 m) as it is read.

    gB files hold one feature per line. GDAL cannot stream them by index (each skip_features
    call re-parses the file from the start, which is quadratic), so lines are parsed here. The
    feature count must equal GDAL's, so an unexpected layout fails loudly instead of silently
    losing units. Coordinates are CRS84 (lon/lat), as for every gB layer."""
    import geopandas as gpd
    import pyogrio
    from shapely.geometry import shape
    expected = pyogrio.read_info(path)["features"]
    rows, geoms = [], []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip().rstrip(",")
            if not s.startswith("{") or '"Feature"' not in s[:200] and '"Feature"' not in s[-400:]:
                continue
            try:
                f = json.loads(s)
            except json.JSONDecodeError:
                continue
            if f.get("type") != "Feature":
                continue
            g = _lighten(shape(f["geometry"]))
            rows.append(f.get("properties") or {})
            geoms.append(g)
    if len(rows) != expected:
        raise RuntimeError(f"{path}: streamed {len(rows)} features, GDAL reports {expected}")
    return gpd.GeoDataFrame(rows, geometry=geoms, crs=4326)


def _load_gb(path: str, water, bbox):
    import geopandas as gpd
    from shapely.geometry import box
    from .geom import polygonal
    os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")      # a few gB features exceed 200 MB
    if os.path.getsize(path) < BIG_FILE:
        gdf = gpd.read_file(path).to_crs(4326)
        geoms = [polygonal(g) for g in gdf.geometry]
    else:
        gdf = _stream_big_geojson(path)
        geoms = [polygonal(g) for g in gdf.geometry]
    if water is not None:
        m = water.intersection(box(*bbox).buffer(1.0))
        if not m.is_empty:
            geoms = [g.difference(m) if g.intersects(m) else g for g in geoms]
            geoms = [polygonal(g) for g in geoms]
    clean = lambda col: [str(x) if str(x) not in ("", "None", "nan") else None
                         for x in (gdf[col] if col in gdf else [None] * len(gdf))]
    return geoms, clean("shapeISO"), clean("shapeName")


def measure_country(iso: str, levels: list, meta: list) -> dict:
    from shapely.strtree import STRtree
    from shapely.ops import unary_union
    from maps_geo.build import country_units
    from maps_geo.roster import country_roster
    from . import geom as G
    from .fetch import gb_path

    t0 = time.time()
    S = _shared()
    from .units import points_in_rows, propose, vertex_names
    from maps_geo.overrides import Overrides, apply_relabels
    a1 = S["a1"]
    rows_ne = a1[a1["iso_a2"].astype(str) == iso]
    roster = country_roster(iso)
    codes, ne_ll, block, _ = country_units(rows_ne, roster, water=S["water"])
    crs = G.local_crs(ne_ll.values())
    ne = G.project(ne_ll, crs)
    bbox = unary_union(list(ne_ll.values())).bounds
    keys = list(codes)
    sea = G.project({0: sea_mask(S, bbox)}, crs)[0]
    old_key = dict(zip(block["ne_id"].astype(str), block["_key"]))
    pts = {c: v for c, v in S["pts"].items() if c.split("-", 1)[0] == iso}

    def matched(gb, gb_codes):
        return G.match(ne, gb, {k: k.split(":", 1)[0] for k in keys}, gb_codes)

    # Every downloaded gB level, matched; keep the one that identifies NE's units best.
    best = None
    tried = []
    for level in levels:
        path = gb_path(iso, level)
        if not os.path.exists(path):
            continue
        gb_ll, gb_codes, gb_names = _load_gb(path, S["water"], bbox)
        gb = [g.simplify(GB_SIMPLIFY_M, preserve_topology=True)
              for g in G.project(dict(enumerate(gb_ll)), crs).values()]
        m = matched(gb, gb_codes)
        rec = next(r for r in meta if r["boundaryType"] == level)
        tried.append({"level": level, "units": len(gb), "quality": round(m.quality, 4),
                      "poor": len(m.poor),
                      "by_code": sum(v == "code" for v in m.matched_by.values())})
        if best is None or m.quality > best[1].quality + 1e-9:
            best = (rec, m, gb, gb_codes, gb_names)

    # Rule relabels (wg.units): gB and Wikidata agreeing against NE. The vertices are rebuilt
    # once and re-matched on the chosen level.
    relabels = []
    if best:
        table = _row_table(block, best[2], best[3], best[4], crs)
        relabels = propose(table, points_in_rows(block, pts, crs), pts, S["protected"])
        if relabels:
            rows_ne = apply_relabels(rows_ne, Overrides(relabel=relabels))
            codes, ne_ll, block, _ = country_units(rows_ne, roster, water=S["water"])
            ne = G.project(ne_ll, crs)
            keys = list(codes)
            best = (best[0], matched(best[2], best[3])) + best[2:]
    new_key = dict(zip(block["ne_id"].astype(str), block["_key"]))
    # Rows v0.1 already relabelled (its overrides.json) carried their corrected key there.
    for nid in S["v01_relabelled"] & set(new_key):
        old_key[nid] = new_key[nid]
    # A vertex key of the old release maps to the vertex holding all of its rows (else None).
    renamed = {}
    for nid, k in old_key.items():
        renamed.setdefault(k, set()).add(new_key.get(nid))
    renamed = {k: next(iter(v)) for k, v in renamed.items() if len(v) == 1}

    release_edges = {}
    rel = os.path.join(RELEASE, f"{iso}.json")
    if os.path.exists(rel):
        g = json.load(open(rel, encoding="utf-8"))
        for e in g["edges"]:
            u, v = renamed.get(e["u"]), renamed.get(e["v"])
            if u and v and u != v:
                release_edges[tuple(sorted((u, v)))] = [s["source"] for s in e["sources"]]

    # Candidate pairs from either geometry.
    cand = set()
    tree = STRtree([ne[k] for k in keys])
    for i, k in enumerate(keys):
        for j in tree.query(ne[k].buffer(NE_NEAR_M)):
            j = int(j)
            if j > i and ne[k].distance(ne[keys[j]]) <= NE_NEAR_M:
                cand.add((k, keys[j]) if k < keys[j] else (keys[j], k))
    if best:
        R = best[1].redraw
        rk = [k for k in keys if not R[k].is_empty]
        rtree = STRtree([R[k] for k in rk])
        for i, k in enumerate(rk):
            for j in rtree.query(R[k].buffer(GB_TOL_M)):
                j = int(j)
                if rk[j] != k and R[k].distance(R[rk[j]]) <= GB_TOL_M:
                    a, b = sorted((k, rk[j]))
                    cand.add((a, b))
    cand |= set(release_edges)            # overrides can add edges NE geometry lacks
    cand |= {tuple(sorted((e["u"], e["v"]))) for e in S["decisions"]["edges"] if e["iso"] == iso}

    bufs = {}
    def buf(k):
        if k not in bufs:
            bufs[k] = best[1].redraw[k].buffer(GB_TOL_M)
        return bufs[k]

    pairs = []
    for u, v in sorted(cand):
        if u not in ne or v not in ne:
            continue
        row = {"u": u, "v": v,
               "ne_contact": G.contact(ne_ll[u], ne_ll[v]),
               "ne_len_m": round(G.geodesic_shared(ne_ll[u], ne_ll[v]), 1),
               "ne_gap_m": round(ne[u].distance(ne[v]), 1),
               "release": release_edges.get((u, v)),
               "p47": (u.split(":")[0], v.split(":")[0]) in S["p47"]
                      or (v.split(":")[0], u.split(":")[0]) in S["p47"]}
        if best:
            m = best[1]
            Ru, Rv = m.redraw[u], m.redraw[v]
            if Ru.is_empty or Rv.is_empty:
                row.update(gb_len_m=None, gb_gap_m=None)
            else:
                row["gb_len_m"] = round(min(G.border_near(Ru, buf(v)), G.border_near(Rv, buf(u))), 1)
                # The part of gB's border over NE's sea or a large lake: gB layers that run
                # boundaries out into estuaries and firths. Only land and rivers count.
                row["gb_sea_m"] = round(min(G.border_near(Ru, buf(v), within=sea),
                                            G.border_near(Rv, buf(u), within=sea)), 1) \
                    if row["gb_len_m"] > 0 and not sea.is_empty else 0.0
                row["gb_gap_m"] = round(Ru.distance(Rv), 1)
            row["q"] = [round(m.unit_quality[u], 3), round(m.unit_quality[v], 3)]
        pairs.append(row)

    from .labels import label_status
    out = {"iso": iso, "n": len(keys), "crs": crs, "gb_tol_m": GB_TOL_M,
           "gb_simplify_m": GB_SIMPLIFY_M, "ne_near_m": NE_NEAR_M, "levels_tried": tried,
           "relabels": relabels,
           "vertices": vertex_names(block, keys, roster),
           "labels": label_status(keys, ne, pts, crs),
           "seconds": round(time.time() - t0, 1)}
    if best:
        rec, m, gb, gb_codes, gb_names = best
        out["gb"] = {"level": rec["boundaryType"], "units": len(m.owner),
                     "year": rec.get("boundaryYearRepresented"), "source": rec.get("boundarySource"),
                     "license": rec.get("boundaryLicense"), "boundaryID": rec.get("boundaryID"),
                     "quality": round(m.quality, 4),
                     "unit_quality": {k: round(m.unit_quality[k], 3) for k in keys},
                     "coverage": {k: round(m.coverage[k], 3) for k in keys},
                     "matched_by": dict(m.matched_by),
                     "iou": {k: round(m.iou[k], 3) for k in keys},
                     "area_ratio": {k: (round(m.redraw[k].area / ne[k].area, 3)
                                        if ne[k].area > 0 and not m.redraw[k].is_empty else None)
                                    for k in keys},
                     "units_list": [{"code": c, "name": nm, "owner": o, "purity": round(pu, 3)}
                                    for c, nm, o, pu in zip(gb_codes, gb_names, m.owner, m.purity)],
                     "rows": _row_flags(_row_table(block, gb, gb_codes, gb_names, crs)),
                     "unowned_gb_units": sum(o is None for o in m.owner)}
    out["pairs"] = pairs
    out["seconds"] = round(time.time() - t0, 1)
    return out


_GENERIC = {"region", "province", "provincia", "governorate", "governate", "prefecture", "county",
            "district", "department", "departement", "departamento", "state", "estado", "capital",
            "municipality", "parish", "oblast", "wilayah", "city", "of", "the", "de", "del", "la"}


def name_key(s) -> str:
    """Accent-, case- and generic-word-insensitive form of a unit name."""
    import re
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c))
    words = [w for w in re.split(r"[^a-z0-9]+", s.lower()) if w and w not in _GENERIC]
    return "".join(words)


def same_name(a, b) -> bool:
    import difflib
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka in kb or kb in ka or difflib.SequenceMatcher(None, ka, kb).ratio() >= 0.8


def _row_table(block, gb, gb_codes, gb_names, crs) -> list:
    """Which gB unit holds most of each NE row (before rows dissolve into vertices).

    One entry per row: {key, ne_id, code, name, gb_code, gb_name, share}, where share is the
    fraction of the row's area inside that gB unit."""
    import geopandas as gpd
    from shapely.strtree import STRtree
    from .geom import polygonal
    rows = gpd.GeoSeries(list(block.geometry), crs=4326).to_crs(crs)
    tree = STRtree(gb)
    out = []
    for key, g, code, name, ne_id in zip(block["_key"], rows, block["iso_3166_2"].astype(str),
                                          block["name"], block["ne_id"].astype(str)):
        g = polygonal(g)
        best, ba = None, 0.0
        for j in tree.query(g):
            a = gb[int(j)].intersection(g).area
            if a > ba:
                best, ba = int(j), a
        out.append({"key": key, "ne_id": ne_id, "code": code,
                    "name": None if str(name) in ("", "nan", "None") else str(name).strip(),
                    "gb_code": gb_codes[best] if best is not None else None,
                    "gb_name": gb_names[best] if best is not None else None,
                    "share": round(ba / g.area, 3) if g.area > 0 else 0.0})
    return out


def _row_flags(table: list) -> dict:
    """Per flagged vertex, its rows and flags. Rows under half inside any one gB unit are not
    judged (generalisation, vintage splits).
      merged  two of the vertex's rows sit (>= half each) in different coded gB units: NE filed
              a distinct unit under this one's code and name
      code    a row sits in a gB unit with another code but the same name
      label   a row sits in a gB unit with another code AND another name
    After the rule relabels, what remains flagged is where Wikidata did not side with gB."""
    per = {}
    for r in table:
        per.setdefault(r["key"], []).append(r)
    out = {}
    for key, rs in per.items():
        base = key.split(":", 1)[0]
        firm = [r for r in rs if r["share"] >= 0.5 and r["gb_code"]]
        flags = set()
        if len({r["gb_code"] for r in firm}) > 1:
            flags.add("merged")
        for r in firm:
            if r["gb_code"] != base:
                flags.add("code" if same_name(r["name"], r["gb_name"]) else "label")
        if flags:
            out[key] = {"flags": sorted(flags),
                        "rows": [{k: r[k] for k in ("ne_id", "name", "gb_code", "gb_name", "share")}
                                 for r in rs]}
    return out


def _run(iso, levels, meta):
    try:
        return iso, measure_country(iso, levels, meta), None
    except Exception as e:  # report and continue: one bad layer must not stop the audit
        import traceback
        return iso, None, traceback.format_exc()


def main(argv=None):
    from .fetch import country_isos
    from .gb import choose_levels
    from .lock import load_lock
    ap = argparse.ArgumentParser(prog="wg.pairs")
    ap.add_argument("--iso", nargs="*")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    meta = load_lock()["geoboundaries"]["meta"]
    isos = country_isos()
    if a.iso:
        isos = {k: v for k, v in isos.items() if k in a.iso}
    os.makedirs(OUT_DIR, exist_ok=True)
    todo = [(k, choose_levels(meta.get(k, []), n), meta.get(k, [])) for k, n in sorted(isos.items())]
    todo = [t for t in todo if a.force or not os.path.exists(os.path.join(OUT_DIR, f"{t[0]}.json"))]
    # Largest countries first so the pool ends evenly.
    todo.sort(key=lambda t: -isos[t[0]])
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(_run, *t) for t in todo]
        for f in as_completed(futs):
            iso, out, err = f.result()
            if err:
                print(f"{iso}: FAILED\n{err}", file=sys.stderr, flush=True)
                continue
            with open(os.path.join(OUT_DIR, f"{iso}.json"), "w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False, indent=0)
            gbq = out.get("gb", {}).get("quality")
            print(f"{iso}: n={out['n']} pairs={len(out['pairs'])} gb={out.get('gb', {}).get('level')} "
                  f"q={gbq} {out['seconds']}s", flush=True)


if __name__ == "__main__":
    main()
