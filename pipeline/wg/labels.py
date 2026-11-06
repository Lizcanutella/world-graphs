"""Label check: does Wikidata's point for each ISO 3166-2 code fall inside the NE vertex that
carries the code?

    label_status(...)             called by wg.pairs for every country (stored as "labels")
    uv run python -m wg.labels    -> data/audit/labels.csv, data/audit/labels_summary.json

Independent of geoBoundaries, so it covers every country. Run after the rule relabels
(wg.units), so what it reports is what Wikidata still disputes.

Per vertex, the Wikidata items holding its code (any rank: NE uses codes ISO has since
deprecated) and their coordinates. Status:
  ok          a point of the code's item(s) lies in the vertex (or within NEAR_M of it)
  elsewhere   every point lies in, or nearest to, another vertex: the label disagrees with
              Wikidata (code swap, shuffled labels, or a stale code reused for another unit)
  outside     the points lie outside the country's NE units altogether
  no_point    no item with this code has coordinates
  shared_code the point lies in a sibling vertex filed under the same code (`CODE:Name`)
A region's Wikidata point is usually its capital or centroid. A capital that NE draws as its
own vertex inside the province therefore reads `elsewhere` (into the capital); the report
marks those `capital_vertex` so they are not mistaken for label errors.
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict

NEAR_M = 5000.0
OUT = "data/audit"


def label_status(keys, ne: dict, pts: dict, crs: str) -> dict:
    """{vertex: {"status", "point_in", "km"}} for the projected vertices `ne`."""
    import geopandas as gpd
    from shapely.geometry import Point
    out = {}
    for k in keys:
        base = k.split(":", 1)[0]
        cands = pts.get(base, [])
        located = [c for c in cands if c[1] is not None]
        status, where, dist = "no_point", None, None
        if located:
            P = gpd.GeoSeries([Point(*c[1]) for c in located], crs=4326).to_crs(crs)
            hits = []
            for p in P:
                d = {v: ne[v].distance(p) for v in keys}
                v = min(d, key=d.get)
                hits.append((d[k], v, d[v]))
            best = min(hits)                    # the point closest to this vertex
            if best[0] <= NEAR_M:
                status, where, dist = "ok", k, best[0]
            else:
                near = min(hits, key=lambda h: h[2])
                where, dist = near[1], near[0]
                status = "elsewhere" if near[2] <= NEAR_M else "outside"
                # A province whose point is its capital, drawn by NE as its own vertex inside it.
                if status == "elsewhere" and ne[k].convex_hull.contains(ne[where]):
                    status = "capital_vertex"
                # NE files several units under one code (`CODE:Name`): the code's point
                # lands in one of them, which says nothing about this one's label.
                if status == "elsewhere" and where.split(":", 1)[0] == base:
                    status = "shared_code"
        out[k] = {"status": status, "point_in": where,
                  "km": round(dist / 1000, 1) if dist is not None else None,
                  "items": [f"{q} {lab or ''} ({rank})" for q, _, lab, rank in cands]}
    return out


def main():
    import glob
    rows, tally = [], Counter()
    for f in sorted(glob.glob(os.path.join(OUT, "pairs", "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        names = d.get("vertices", {})
        for k, s in d.get("labels", {}).items():
            tally[s["status"]] += 1
            if s["status"] != "ok":
                rows.append({"iso": d["iso"], "vertex": k, "name": names.get(k) or "",
                             "status": s["status"], "point_in": s["point_in"] or "",
                             "point_in_name": names.get(s["point_in"]) or "" if s["point_in"] else "",
                             "km_from_vertex": "" if s["km"] is None else s["km"],
                             "items": ";".join(s["items"])})
    with open(os.path.join(OUT, "labels.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    s = {"near_m": NEAR_M, "status": dict(tally),
         "elsewhere_by_country": dict(Counter(r["iso"] for r in rows if r["status"] == "elsewhere").most_common())}
    json.dump(s, open(os.path.join(OUT, "labels_summary.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(s, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
