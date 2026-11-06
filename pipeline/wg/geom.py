"""Geometry primitives for comparing two drawings of one vertex set. Everything is in metres.

Each country is projected to an azimuthal equidistant CRS centred on it, so tolerances are
real distances at every latitude (the first-generation review used degree tolerances, whose
metric size shrinks toward the poles). Shared-border lengths that decide edges stay geodesic,
as in the build; the projection is only used for tolerances, gaps and areas.

Point-contact noise: with tolerance t, `border_near` counts the parts of a's boundary within t
of b, so a pure point contact still measures about 2t per contact point (each of a's two
boundary arms near the point). The first review's 0.6 km "Four Corners noise floor" was exactly
this artifact of its ~300 m degree tolerance. Callers compare against `point_noise(t)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
from pyproj import Geod
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.strtree import STRtree

GEOD = Geod(ellps="WGS84")


def local_crs(geoms) -> str:
    """AEQD centred on the union's representative point (lon/lat input)."""
    from shapely.ops import unary_union
    p = unary_union(list(geoms)).representative_point()
    return f"+proj=aeqd +lat_0={p.y:.6f} +lon_0={p.x:.6f} +datum=WGS84 +units=m +no_defs"


def project(geoms: dict, crs: str) -> dict:
    keys = list(geoms)
    s = gpd.GeoSeries([geoms[k] for k in keys], crs=4326).to_crs(crs)
    return {k: polygonal(g) for k, g in zip(keys, s)}


def polygonal(g):
    """The (Multi)Polygon part of a geometry, made valid; empty Polygon if none."""
    if g is None or g.is_empty:
        return Polygon()
    if not g.is_valid:
        g = make_valid(g)
    if isinstance(g, (Polygon, MultiPolygon)):
        return g
    if isinstance(g, GeometryCollection):
        parts = []
        for p in g.geoms:
            if isinstance(p, Polygon):
                parts.append(p)
            elif isinstance(p, MultiPolygon):
                parts.extend(p.geoms)
        return MultiPolygon(parts) if parts else Polygon()
    return Polygon()


def geodesic_shared(a, b) -> float:
    """Geodesic length (m) of the exact shared boundary of two lon/lat polygons."""
    s = a.boundary.intersection(b.boundary)
    return 0.0 if s.is_empty or s.length <= 0 else abs(GEOD.geometry_length(s))


def contact(a, b) -> str:
    """'line' | 'point' | 'none' for two lon/lat polygons, exactly as the build sees them."""
    s = a.boundary.intersection(b.boundary)
    if s.is_empty:
        return "none"
    return "line" if s.length > 0 else "point"


def point_noise(tol: float) -> float:
    return 2.0 * tol


def border_near(a, b_buf, within=None) -> float:
    """Length (projected m) of a's boundary inside b_buf (b buffered by the tolerance), or
    only the part of it inside `within` when given."""
    if a.is_empty or b_buf.is_empty:
        return 0.0
    seg = a.boundary.intersection(b_buf)
    return (seg if within is None else seg.intersection(within)).length


CODE_MIN_OVERLAP = 0.5   # a code match must share this much of the smaller unit's area


@dataclass
class Match:
    """gB units assigned to NE owners, and how confidently each NE unit is identified."""
    owner: list                      # NE key per gB unit (None if it overlaps no NE unit)
    purity: list                     # share of each gB unit's area inside its owner
    redraw: dict                     # NE key -> union of its gB units (projected)
    unit_quality: dict               # NE key -> identification confidence in [0, 1]
    coverage: dict                   # NE key -> share of NE area covered by its own gB units
    matched_by: dict = field(default_factory=dict)   # NE key -> "code" | "area" | None
    iou: dict = field(default_factory=dict)          # NE key -> IoU of NE unit and its redraw
    quality: float = 0.0             # area-weighted mean unit quality over the country
    poor: list = field(default_factory=list)   # NE keys with unit quality < 0.8


def match(ne: dict, gb: list, ne_codes: dict | None = None, gb_codes: list | None = None) -> Match:
    """Assign gB units (projected) to NE units (projected).

    1. By code: an NE unit whose ISO code no other NE unit shares takes the gB unit carrying
       that code, if the two overlap by at least CODE_MIN_OVERLAP of the smaller one (a stale
       code reused for a different unit fails this). Identity is then settled (quality 1):
       generalisation can make NE's outline differ a lot from gB's without making it a
       different unit, and the shape difference is reported separately as IoU.
    2. By area: every other gB unit goes to the NE unit holding most of its area. An NE unit
       identified only this way gets quality min(coverage, area-weighted purity).
    """
    from shapely.ops import unary_union
    keys = list(ne)
    tree = STRtree([ne[k] for k in keys])
    owner, purity = [None] * len(gb), [0.0] * len(gb)
    by_code = {}
    if ne_codes and gb_codes:
        ne_count = {}
        for k in keys:
            ne_count[ne_codes[k]] = ne_count.get(ne_codes[k], 0) + 1
        gb_index = {}
        for i, c in enumerate(gb_codes):
            if c:
                gb_index.setdefault(c, []).append(i)
        for k in keys:
            c = ne_codes[k]
            hits = gb_index.get(c, [])
            if ne_count[c] != 1 or len(hits) != 1:
                continue
            i = hits[0]
            g = gb[i]
            small = min(g.area, ne[k].area)
            if small > 0 and g.intersection(ne[k]).area >= CODE_MIN_OVERLAP * small:
                owner[i], by_code[k] = k, i
                purity[i] = g.intersection(ne[k]).area / g.area
    for i, g in enumerate(gb):
        if owner[i] is not None or g.is_empty:
            continue
        best, ba = None, 0.0
        for j in tree.query(g):
            a = g.intersection(ne[keys[int(j)]]).area
            if a > ba:
                best, ba = keys[int(j)], a
        owner[i] = best
        purity[i] = ba / g.area if g.area > 0 else 0.0
    groups = {k: [] for k in keys}
    for i, k in enumerate(owner):
        if k is not None:
            groups[k].append(i)
    redraw, uq, cov, how, iou = {}, {}, {}, {}, {}
    for k in keys:
        idx = groups[k]
        if not idx:
            redraw[k], uq[k], cov[k], how[k], iou[k] = Polygon(), 0.0, 0.0, None, 0.0
            continue
        r = polygonal(unary_union([gb[i] for i in idx]))
        redraw[k] = r
        area = ne[k].area
        inter = r.intersection(ne[k]).area
        cov[k] = inter / area if area > 0 else 0.0
        union = r.union(ne[k]).area
        iou[k] = inter / union if union > 0 else 0.0
        if k in by_code:
            uq[k], how[k] = 1.0, "code"
        else:
            wsum = sum(gb[i].area for i in idx)
            wp = sum(purity[i] * gb[i].area for i in idx) / wsum if wsum > 0 else 0.0
            uq[k], how[k] = min(cov[k], wp), "area"
    total = sum(ne[k].area for k in keys)
    q = sum(uq[k] * ne[k].area for k in keys) / total if total > 0 else 0.0
    return Match(owner, purity, redraw, uq, cov, how, iou, q,
                 sorted(k for k in keys if uq[k] < 0.8))
