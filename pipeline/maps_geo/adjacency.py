"""Shared-border adjacency over shapely geometries (Unit C core, dep-guarded)."""
from __future__ import annotations

from . import require_geo

# Default shared-border threshold, in METRES (geodesic). 100 m sits above the
# longest point-contact/numerical artifact (0 m) and below the shortest real
# short border measured in the 2026-07-18 admin-1 diagnostic (Vatican–Italy at
# 427 m; the 120 admin-1 sub-threshold borders span 200–1101 m), so it recovers
# every real border while still rejecting point contacts (e.g. the Four Corners
# US states, which meet at a zero-length point).
DEFAULT_EPS_M = 100.0


def geo_adjacency(geoms: dict, *, eps: float = DEFAULT_EPS_M) -> list:
    """Edges (u, v), u < v, between units whose shared border exceeds `eps` METRES.

    `eps` is a real geodesic distance on the WGS84 ellipsoid, **not** a coordinate
    angle: the same physical threshold applies at every latitude (0.01° is ~1.1 km
    at the equator but ~0.55 km at 60°N), and point contacts — a zero-length shared
    boundary, like the Four Corners US states — are rejected consistently.

    `geoms`: {vertex_id: shapely (Multi)Polygon} in EPSG:4326 (lon/lat). Uses an
    STRtree bbox filter to avoid the full O(n^2) boundary intersection on large
    inputs, and only pays for the geodesic length on pairs that actually touch.
    """
    require_geo()
    from pyproj import Geod
    from shapely.strtree import STRtree

    geod = Geod(ellps="WGS84")
    ids = sorted(geoms)
    boundary = {i: geoms[i].boundary for i in ids}
    tree = STRtree([geoms[i] for i in ids])
    edges = set()
    for u in ids:
        for j in tree.query(geoms[u]):              # bbox-overlap candidates (indices)
            v = ids[int(j)]
            if v <= u:
                continue
            shared = boundary[u].intersection(boundary[v])
            if shared.length <= 0.0:                 # point contact or no contact
                continue
            if abs(geod.geometry_length(shared)) > eps:
                edges.add((u, v))
    return sorted(edges)


def normalize_positions(centroids: list) -> list:
    """(lon, lat) -> [x, y] in [0,1]^2, y flipped so north renders up."""
    if not centroids:
        return []
    xs = [c[0] for c in centroids]
    ys = [c[1] for c in centroids]

    def scale(v, lo, hi):
        return 0.5 if hi - lo < 1e-12 else (v - lo) / (hi - lo)

    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return [[scale(x, x0, x1), 1.0 - scale(y, y0, y1)] for x, y in centroids]
