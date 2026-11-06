"""Stage 4: write the release from the decided graphs.

    uv run python -m wg.export [--out ..] [--version 0.2.0] [--viz DIR]

Reads data/build/graphs/<ISO>.json (wg.decide) and writes, into --out:
  data/countries/<ISO>.{json,graphml}   one graph per country (schema region-adjacency/2)
  data/nodes.csv, data/edges.csv        every graph, flat
  manifest.json                         index, pinned sources, file hashes
and, with --viz DIR, the globe viewer's data (not part of the dataset):
  DIR/graphs.json, DIR/{outlines,borders}/<ISO>.json
and data/audit/diff_previous.csv: every node and edge that differs from the release it
replaces (read from --out before anything is written).

The world graphs (data/world) come from admin-0 and are outside this pipeline: their files,
index entries (and, with --viz, their globe data in DIR) are carried over unchanged.

Vertex geometry is rebuilt exactly as wg.pairs built it (NE admin-1 with the hand relabels,
then the graph's rule relabels, lakes over 500 km2 clipped); the export fails if the vertex
set differs from the decided graph's. Coordinates are each vertex's representative point;
the Wikidata item is chosen by `wikidata_ids`.

An edge's sources are the independent sources that support it: natural_earth (a shared NE
border over EPS_M), geoboundaries (a gB border estimate over GB_BORDER_M), wikidata_p47, and
hand (a decisions.json entry, with its reason). It is corroborated when a hand decision or
at least two sources support it. `rule` names the wg.decide rule that made it an edge.

`prior_evidence` lists what the 0.1 review found for an edge (data/maps/review/
edge_evidence.json): wikipedia (a border sentence naming the neighbour, matched by script),
review (a fact-checking agent's verbatim quote, machine-checked against the page),
wikidata_item (P47 between the regions' own Wikidata items), geometry_enclave (one region
inside the other). It is information only and does not count towards corroboration: none of
it is a pinned input of this pipeline. Wikipedia is recorded as a URL only (its text is
CC BY-SA).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import hashlib
import json
import os
from collections import Counter
from xml.sax.saxutils import escape

SCHEMA = "region-adjacency/2"
BUILD = "data/build/graphs"
PAIRS = "data/audit/pairs"
AUDIT = "data/audit"
PRIOR_EVIDENCE = "data/maps/review/edge_evidence.json"
PRIOR_SOURCES = ("wikipedia", "review", "wikidata_item", "geometry_enclave")
SOURCE_OF = {"ne": "natural_earth", "gb": "geoboundaries", "p47": "wikidata_p47"}


def sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def edge_record(e: dict) -> dict:
    v = e["votes"]
    src = [{"source": SOURCE_OF[k]} for k in ("ne", "gb", "p47")
           if (v[k] is True) or v[k] == "yes"]
    if e["rule"] == "hand":
        src.append({"source": "hand", "reason": e["reason"]})
    return {"u": e["u"], "v": e["v"], "rule": e["rule"], "sources": src,
            "corroborated": e["rule"] == "hand" or len(src) >= 2,
            "ne_border_m": round(e["ne_len_m"])}


def wikidata_ids(codes, rows: dict, ne_qid: dict, v01_ids: dict, v01_rows: dict | None,
                 relabelled: set, pts: dict, q2codes: dict, labels: dict) -> dict:
    """{vertex: Wikidata item or None}, first of:
      1. NE's own `wikidataid` on the vertex's rows (one item), when that item carries the
         vertex's code (P300, any rank). It follows the geometry and agrees with the label.
      2. The 0.1 release's item, voted from GeoNames, HASC, FIPS and other identifiers, when the
         vertex is made of exactly the rows of one 0.1 vertex and was not relabelled.
      3. The code's only non-deprecated item, when its point lies in the vertex."""
    by_key, v01_of = {}, {}
    for nid, k in rows.items():
        by_key.setdefault(k, set()).add(nid)
    if v01_rows is not None:
        v01_by = {}
        for nid, k in v01_rows.items():
            v01_by.setdefault(k, set()).add(nid)
        for k, ids in v01_by.items():
            for c, ids2 in by_key.items():
                if ids == ids2:
                    v01_of[c] = k
    out = {}
    for c in codes:
        base = c.split(":", 1)[0]
        qs = {ne_qid.get(n) for n in by_key.get(c, ())} - {None}
        if len(qs) == 1 and base in q2codes.get(next(iter(qs)), ()):
            out[c] = next(iter(qs))
        elif c not in relabelled and v01_ids.get(v01_of.get(c)):
            out[c] = v01_ids[v01_of[c]]
        else:
            items = [q for q, _, _, rank in pts.get(base, []) if rank != "DeprecatedRank"]
            ok = (labels.get(c) or {}).get("status") == "ok"
            out[c] = items[0] if ok and len(items) == 1 else None
    return out


def graphml(g: dict) -> str:
    keys = [("name", "node", "string"), ("code", "node", "string"), ("wikidata", "node", "string"),
            ("lon", "node", "double"), ("lat", "node", "double"),
            ("sources", "edge", "string"), ("rule", "edge", "string"),
            ("corroborated", "edge", "boolean"), ("verified", "graph", "boolean")]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
    out += [f'  <key id="{k}" for="{f}" attr.name="{k}" attr.type="{t}"/>' for k, f, t in keys]
    out.append(f'  <graph id="{escape(g["id"])}" edgedefault="undirected">')
    out.append(f'    <data key="verified">{str(g["verified"]).lower()}</data>')
    for n in g["nodes"]:
        out.append(f'    <node id="{escape(n["code"])}">'
                   f'<data key="name">{escape(n["name"])}</data>'
                   f'<data key="code">{escape(n["code"])}</data>'
                   f'<data key="wikidata">{escape(n.get("wikidata") or "")}</data>'
                   f'<data key="lon">{n["lon"]}</data><data key="lat">{n["lat"]}</data></node>')
    for e in g["edges"]:
        src = ",".join(s["source"] for s in e["sources"])
        out.append(f'    <edge source="{escape(e["u"])}" target="{escape(e["v"])}">'
                   f'<data key="sources">{escape(src)}</data>'
                   f'<data key="rule">{escape(e["rule"])}</data>'
                   f'<data key="corroborated">{str(e["corroborated"]).lower()}</data></edge>')
    out += ["  </graph>", "</graphml>", ""]
    return "\n".join(out)


def viz_outlines(codes, geoms, tol=None, q=None):
    """Simplified outlines per vertex, as flat quantized [lon, lat, lon, lat, ...] rings.

    Exteriors only, oriented clockwise (d3-geo's convention for spherical polygons, so fills
    don't flip to cover the globe). Tolerance and precision scale with the graph's extent;
    tiny parts are dropped, but a unit always keeps its largest part."""
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.geometry.polygon import orient
    t, qq = _extent(codes, geoms)
    tol, q = tol or t, q or qq
    out = []
    for c in codes:
        g = geoms[c].simplify(tol, preserve_topology=True)
        parts = [p for p in (g.geoms if isinstance(g, MultiPolygon) else [g])
                 if isinstance(p, Polygon) and not p.is_empty]
        parts.sort(key=lambda p: -p.area)
        keep = parts[:1] + [p for p in parts[1:] if p.area > 4 * tol * tol]
        rings = []
        for p in keep:
            ring = orient(p, sign=-1.0).exterior.coords
            rings.append([round(v * q) for xy in ring for v in xy])
        out.append(rings)
    return {"q": q, "units": out}


def _extent(codes, geoms):
    from shapely.ops import unary_union
    x0, y0, x1, y1 = unary_union([geoms[c] for c in codes]).bounds
    diag = max(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, 1e-6)
    return min(max(diag * 0.0012, 0.0004), 0.03), (10000 if diag < 3 else 1000)


def viz_borders(codes, geoms, pairs, tol=None, q=None):
    """The land border of each edge as simplified, quantized polylines. Drawing these instead of
    whole unit outlines leaves coastlines to the land fill, which roughly halves the stroke work."""
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge

    t, qq = _extent(codes, geoms)
    tol, q = tol or t, q or qq
    lines = []
    for u, v in pairs:
        b = geoms[u].boundary.intersection(geoms[v].boundary)
        parts = [g for g in getattr(b, "geoms", [b])
                 if isinstance(g, (LineString, MultiLineString)) and not g.is_empty]
        if not parts:
            continue
        m = linemerge(parts).simplify(tol)
        for ln in getattr(m, "geoms", [m]):
            if len(ln.coords) >= 2:
                lines.append([round(c * q) for xy in ln.coords for c in xy])
    return {"q": q, "lines": lines}


def country_block(iso: str, a1, water, relabels: list):
    """(vertex codes in NE order, {code: geometry}, {ne_id: code}, {code: name})."""
    from maps_geo.build import country_units
    from maps_geo.overrides import Overrides, apply_relabels
    from maps_geo.roster import country_roster
    rows = a1[a1["iso_a2"].astype(str) == iso]
    ids = set(rows["ne_id"].astype(str))
    relabels = [r for r in relabels if str(r["ne_id"]) in ids]
    if relabels:
        rows = apply_relabels(rows, Overrides(relabel=relabels))
    from .units import vertex_names
    roster = country_roster(iso)
    codes, geoms, block, _ = country_units(rows, roster, water=water)
    return (list(codes), geoms, dict(zip(block["ne_id"].astype(str), block["_key"])),
            vertex_names(block, codes, roster))


def prior_evidence(ev: dict, v01_rows: dict, rows: dict) -> dict:
    """{(u, v): [evidence]} from the first review (keyed by 0.1 codes), mapped onto the
    current vertices through the NE rows. geoBoundaries entries are left out (wg.decide's gB
    vote supersedes them), as are entries disputing an edge."""
    fwd = {}
    for nid, k in v01_rows.items():
        if nid in rows:
            fwd.setdefault(k, set()).add(rows[nid])
    out = {}
    for key, items in ev.items():
        a, b = key.split("|")
        keep = [{k: t[k] for k in ("source", "url") if k in t} for t in items
                if t["source"] in PRIOR_SOURCES]
        if not keep:
            continue
        for x in fwd.get(a, {a}):
            for y in fwd.get(b, {b}):
                if x != y:
                    out.setdefault(tuple(sorted((x, y))), []).extend(keep)
    return out


def diff_rows(iso: str, prev: dict | None, prev_rows: dict | None, g: dict, rows: dict) -> list:
    """What changed against the previous release. Vertices are matched through the NE rows
    they are made of, so a relabel reads as one renamed vertex and a split (a hidden unit) as
    a vertex added beside the one it came from, not as a run of edge changes."""
    out = []
    old = {n["code"]: n["name"] for n in (prev or {}).get("nodes", [])}
    new = {n["code"]: n["name"] for n in g["nodes"]}
    fwd, back = {}, {}
    if prev_rows is not None:
        for nid, k in prev_rows.items():
            if nid in rows:
                fwd.setdefault(k, set()).add(rows[nid]); back.setdefault(rows[nid], set()).add(k)
    for c in old:
        fwd.setdefault(c, {c} if c in new else set())
    for c in new:
        back.setdefault(c, {c} if c in old else set())
    for c in sorted(old):
        to = sorted(fwd[c])
        if not to:
            out.append([iso, "node_removed", c, "", old[c], "", ""])
        elif to != [c] or new[c] != old[c]:
            for t in to:
                if t == c and new[c] == old[c]:
                    continue                    # the part of a split that keeps its code
                out.append([iso, "node_relabelled" if t != c else "node_renamed", c, t,
                            old[c], new[t], ""])
    for c in sorted(new):
        if not back[c]:
            out.append([iso, "node_added", "", c, "", new[c], ""])
    old_e = {tuple(sorted((e["u"], e["v"]))): e for e in (prev or {}).get("edges", [])}
    new_e = {(e["u"], e["v"]): e for e in g["edges"]}
    for (a, b), e in sorted(old_e.items()):
        if not any(tuple(sorted((x, y))) in new_e for x in fwd[a] for y in fwd[b] if x != y):
            out.append([iso, "edge_removed", a, b, ";".join(s["source"] for s in e["sources"]), "", ""])
    for (u, v), e in sorted(new_e.items()):
        if not any(tuple(sorted((x, y))) in old_e for x in back[u] for y in back[v] if x != y):
            out.append([iso, "edge_added", u, v, "", e["rule"], e["sources"][-1].get("reason", "")])
    return out


def main(argv=None):
    import geopandas as gpd
    from maps_geo.landmask import water_mask
    from maps_geo.verified import load_verified, verification
    from .units import DECISIONS_PATH, apply_hand, load_decisions, wikidata_points

    ap = argparse.ArgumentParser(prog="wg.export")
    ap.add_argument("--out", default="..")
    ap.add_argument("--version", default="0.2.0")
    ap.add_argument("--viz", default=None, help="also write the globe viewer's data into this directory")
    a = ap.parse_args(argv)

    # The release being replaced, read before anything is written.
    prev_man = json.load(open(os.path.join(a.out, "manifest.json"), encoding="utf-8"))
    prev_viz = json.load(open(os.path.join(a.viz, "graphs.json"), encoding="utf-8")) if a.viz else None
    prev = {}
    for f in glob.glob(os.path.join(a.out, "data", "countries", "*.json")):
        d = json.load(open(f, encoding="utf-8"))
        prev[d["id"]] = d

    dec = load_decisions()
    a1_raw = gpd.read_file("data/naturalearth/ne_10m_admin_1_states_provinces.shp")
    a1 = apply_hand(a1_raw, dec)
    v01_relabels = json.load(open("data/maps/overrides.json", encoding="utf-8"))["relabel"]
    prior = json.load(open(PRIOR_EVIDENCE, encoding="utf-8"))["countries"]
    ne_qid = {str(n): str(q) for n, q in zip(a1["ne_id"], a1["wikidataid"]) if str(q).startswith("Q")}
    pts = wikidata_points()
    q2codes = {}
    for code, items in pts.items():
        for q, _, _, _ in items:
            q2codes.setdefault(q, set()).add(code)
    water = water_mask("data/naturalearth", min_area_km2=500.0)
    verified = load_verified()
    import pycountry

    os.makedirs(os.path.join(a.out, "data", "countries"), exist_ok=True)
    if a.viz:
        for d in ("outlines", "borders"):
            os.makedirs(os.path.join(a.viz, d), exist_ok=True)
    built = sorted(glob.glob(os.path.join(BUILD, "*.json")))
    stale = set(prev) - {os.path.basename(f)[:-5] for f in built}
    if stale:
        raise ValueError(f"countries in the previous release with no decided graph: {sorted(stale)}")

    viz, index, nodes_rows, edges_rows, diff, rules = [], [], [], [], [], Counter()
    for f in built:
        b = json.load(open(f, encoding="utf-8"))
        iso = b["iso"]
        pairs = json.load(open(os.path.join(PAIRS, f"{iso}.json"), encoding="utf-8"))
        codes, geoms, rows, names = country_block(iso, a1, water, b["relabels"])
        prev_rows = None
        if iso in prev:
            # The previous release's vertices from the same NE rows: v0.1 relabelled with
            # overrides.json, a v0.2 release with its graph's own relabels.
            pr = prev[iso].get("relabels")
            if pr is None:
                pc, _, prev_rows, _ = country_block(iso, a1_raw, water, v01_relabels)
            else:
                pc, _, prev_rows, _ = country_block(iso, a1, water, pr)
            if sorted(pc) != sorted(n["code"] for n in prev[iso]["nodes"]):
                print(f"{iso}: previous release's vertices not reproducible; diff by code only")
                prev_rows = None
        if sorted(codes) != [n["code"] for n in b["nodes"]]:
            raise ValueError(f"{iso}: vertex set differs from the decided graph")
        v01_rows = country_block(iso, a1_raw, water, v01_relabels)[2] if iso in prior else None
        qids = wikidata_ids(codes, rows, ne_qid, (prior.get(iso) or {}).get("wikidata", {}), v01_rows,
                            {r["set"]["iso_3166_2"] for r in b["relabels"]}, pts, q2codes,
                            pairs["labels"])
        nodes = []
        for c in codes:
            p = geoms[c].representative_point()
            nodes.append({"code": c, "name": names[c], "wikidata": qids[c],
                          "lon": round(p.x, 5), "lat": round(p.y, 5)})
        edges = sorted((edge_record(e) for e in b["edges"]), key=lambda e: (e["u"], e["v"]))
        if iso in prior:
            ev = prior_evidence(prior[iso]["edges"], v01_rows, rows)
            for e in edges:
                if (e["u"], e["v"]) in ev:
                    e["prior_evidence"] = ev[(e["u"], e["v"])]
        rules.update(e["rule"] for e in edges)
        ver = verification(verified, iso, codes, [(e["u"], e["v"]) for e in edges])
        c = pycountry.countries.get(alpha_2=iso)
        gb = b.get("gb")
        g = {"schema": SCHEMA, "id": iso, "kind": "country",
             "name": c.name if c else {"XK": "Kosovo"}.get(iso, iso),
             "level": (prev.get(iso) or {}).get("level"),
             "n": len(nodes), "m": len(edges),
             "verified": ver is not None, **({"verification": ver} if ver else {}),
             "nodes": nodes, "edges": edges,
             "relabels": [{k: r[k] for k in ("ne_id", "was", "set", "rule")} for r in b["relabels"]],
             "geoboundaries": gb and {k: gb.get(k) for k in ("boundaryID", "level", "year", "license")}}
        sub = os.path.join(a.out, "data", "countries")
        with open(os.path.join(sub, f"{iso}.json"), "w", encoding="utf-8") as fh:
            json.dump(g, fh, ensure_ascii=False, indent=1)
        with open(os.path.join(sub, f"{iso}.graphml"), "w", encoding="utf-8") as fh:
            fh.write(graphml(g))
        if a.viz:
            pairs_uv = [(e["u"], e["v"]) for e in edges]
            with open(os.path.join(a.viz, "outlines", f"{iso}.json"), "w") as fh:
                json.dump(viz_outlines(codes, geoms), fh, separators=(",", ":"))
            with open(os.path.join(a.viz, "borders", f"{iso}.json"), "w") as fh:
                json.dump(viz_borders(codes, geoms, pairs_uv), fh, separators=(",", ":"))
        unc = sum(not e["corroborated"] for e in edges)
        viz.append({"id": iso, "kind": "country", "name": g["name"], "level": g["level"],
                    "n": g["n"], "m": g["m"], "verified": g["verified"], "unc": unc,
                    "nodes": [[n["code"], n["name"], n["lon"], n["lat"]] for n in nodes],
                    "edges": [[codes.index(e["u"]), codes.index(e["v"]), int(e["corroborated"])]
                              for e in edges]})
        index.append({"id": iso, "kind": "country", "n": g["n"], "m": g["m"],
                      "uncorroborated_edges": unc, "verified": g["verified"]})
        nodes_rows += [[iso, n["code"], n["name"], n["wikidata"] or "", n["lon"], n["lat"]] for n in nodes]
        edges_rows += [[iso, e["u"], e["v"], ";".join(s["source"] for s in e["sources"]), e["rule"],
                        int(e["corroborated"])] for e in edges]
        diff += diff_rows(iso, prev.get(iso), prev_rows, g, rows)

    # World graphs: carried over from the previous release.
    worlds = [x for x in prev_man["index"] if x["kind"] == "world"]
    for w in worlds:
        wg_ = json.load(open(os.path.join(a.out, "data", "world", f"{w['id']}.json"), encoding="utf-8"))
        nodes_rows += [[w["id"], n["code"], n["name"], n.get("wikidata") or "", n["lon"], n["lat"]]
                       for n in wg_["nodes"]]
        edges_rows += [[w["id"], e["u"], e["v"], ";".join(s["source"] for s in e["sources"]), "",
                        int(e["corroborated"])] for e in wg_["edges"]]
    index = worlds + index
    if a.viz:
        viz = [x for x in prev_viz["graphs"] if x["kind"] == "world"] + viz

    with open(os.path.join(a.out, "data", "nodes.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["graph", "code", "name", "wikidata", "lon", "lat"]); w.writerows(nodes_rows)
    with open(os.path.join(a.out, "data", "edges.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["graph", "u", "v", "sources", "rule", "corroborated"]); w.writerows(edges_rows)
    if a.viz:
        with open(os.path.join(a.viz, "graphs.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": a.version, "graphs": viz}, fh, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(AUDIT, "diff_previous.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["iso", "change", "u", "v", "before", "after_or_rule", "reason"])
        w.writerows(diff)

    lock = json.load(open("sources.lock.json", encoding="utf-8"))
    files = sorted(os.path.relpath(os.path.join(r, f), a.out)
                   for r, _, fs in os.walk(os.path.join(a.out, "data")) for f in fs)
    man = {"schema": SCHEMA, "version": a.version, "exported": dt.date.today().isoformat(),
           "previous": prev_man.get("version"),
           "graphs": len(index), "edges": len(edges_rows),
           "uncorroborated_edges": sum(r[5] == 0 for r in edges_rows),
           "verified": [x["id"] for x in index if x["verified"]],
           "country_edge_rules": dict(sorted(rules.items())),
           "sources": {"pipeline": "wg (fetch, pairs, decide, export)",
                       "sources_lock_sha256": sha256("sources.lock.json"),
                       "decisions_sha256": sha256(DECISIONS_PATH),
                       "natural_earth": {f[:-len(".VERSION.txt")]: open(os.path.join("data/naturalearth", f)).read().strip()
                                         for f in sorted(os.listdir("data/naturalearth")) if f.endswith(".VERSION.txt")},
                       "geoboundaries_commits": sorted({u["url"].split("/raw/", 1)[1].split("/", 1)[0]
                                                        for u in lock["geoboundaries"]["files"].values()}),
                       "wikidata": {k: v.get("fetched") for k, v in lock["wikidata"].items()},
                       "wikidata_p47_snapshot": prev_man["sources"].get("wikidata_p47_snapshot"),
                       "world_graphs": f"carried over from {prev_man.get('version')}",
                       "min_lake_km2": 500.0, "eps_m": 100.0},
           "index": index,
           "sha256": {f: sha256(os.path.join(a.out, f)) for f in files}}
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=1, ensure_ascii=False)
    kinds = Counter(r[1] for r in diff)
    print(f"{len(index)} graphs, {len(edges_rows)} edges ({man['uncorroborated_edges']} uncorroborated) "
          f"-> {a.out}; changes vs {prev_man.get('version')}: {dict(kinds)}")


if __name__ == "__main__":
    main()
