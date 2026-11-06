"""Region boundary outlines for the Gallery "see original" overlay.

Reconstructs each map unit's real polygon border from the Natural Earth source
and normalizes every coordinate with the SAME centroid bounding box that
``normalize_positions`` (adjacency.py) uses for the committed ``positions`` — so
the outlines overlay the already-drawn vertices exactly. Vertex ordering is
reproduced from the build's own ``country_units``/``world_units``, and the
returned ``codes`` let the caller assert they match the dataset's ``codes``
before trusting the overlay (a mismatch would mean silently misaligned borders).

This is a *view-time* convenience: it needs the [geo] extra and the Natural Earth
shapefiles on disk. It does not touch the committed dataset or its numbers.
"""
from __future__ import annotations

import os

from . import require_geo
from .build import _labels_for, ordered_geoms


def _rings(geom, sx, sy, simplify_tol):
    """Normalized exterior rings of a (Multi)Polygon after topology-preserving
    simplification. Interior holes are dropped — exteriors suffice to read
    adjacency, and this keeps the payload small."""
    from shapely.geometry import Polygon, MultiPolygon

    g = geom.simplify(simplify_tol, preserve_topology=True) if simplify_tol else geom
    parts = g.geoms if isinstance(g, MultiPolygon) else [g]
    rings = []
    for part in parts:
        if not isinstance(part, Polygon) or part.is_empty:
            continue
        rings.append([[round(sx(x), 5), round(sy(y), 5)]
                      for x, y in part.exterior.coords])
    return rings


def _polygons(keys, geoms, simplify_tol):
    """Rings per vertex, normalized by the SAME representative-point box that
    `normalize_positions` applies to the committed positions."""
    reps = [geoms[k].representative_point() for k in keys]
    xs = [p.x for p in reps]
    ys = [p.y for p in reps]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    def sx(x):
        return 0.5 if x1 - x0 < 1e-12 else (x - x0) / (x1 - x0)

    def sy(y):                                   # y flipped so north renders up
        return 0.5 if y1 - y0 < 1e-12 else 1.0 - (y - y0) / (y1 - y0)

    return [_rings(geoms[k], sx, sy, simplify_tol) for k in keys]


def _outlines_from_gdf(gdf, *, key, simplify_tol, label=None):
    keys, geoms = ordered_geoms(gdf, key=key)
    polygons = _polygons(list(range(len(keys))), geoms, simplify_tol)
    names = keys if label is None else _labels_for(gdf, key=key, label=label, keys=keys)
    return names, polygons


def region_outlines(data_dir, *, family, iso=None, policy=None, simplify_tol=0.02,
                    min_lake_km2=None, overrides=None):
    """(codes, polygons) for a committed map instance.

    `family` == "map_world" -> the admin-0 world under inclusion `policy` (Unit
    4b: un195 / natural_earth; defaults to `policy.DEFAULT_POLICY`); otherwise the
    admin-1 units of country `iso`. Vertices come from the same `world_units` /
    `country_units` the build uses, lake-clipped with the dataset's
    `min_lake_km2` (None = unclipped), so `codes[v]` matches `Instance.codes`,
    which is what `serve.py` compares against. `polygons[v]` is a list of rings;
    each ring is a list of [x, y] in the same normalized, y-flipped space as the
    served `positions`. `overrides` defaults to the committed pinned file (when
    present), whose relabels change which code a polygon carries.
    """
    require_geo()
    import geopandas as gpd
    from .build import country_units, world_units
    from .landmask import water_mask
    from .naturalearth import fetch_natural_earth

    paths = fetch_natural_earth(data_dir)        # local files present -> no network
    water = water_mask(data_dir, min_area_km2=min_lake_km2) if min_lake_km2 else None
    if family == "map_world":
        from .policy import DEFAULT_POLICY, assign_world_vertices
        gdf = gpd.read_file(paths["admin0"])
        block = assign_world_vertices(gdf, policy or DEFAULT_POLICY)
        codes, geoms = world_units(block, water=water)
    else:
        from .roster import country_roster
        from .overrides import OVERRIDES_PATH, apply_relabels, load_overrides
        if overrides is None and os.path.exists(OVERRIDES_PATH):
            overrides = load_overrides(OVERRIDES_PATH)
        gdf = apply_relabels(gpd.read_file(paths["admin1"]), overrides)
        sub = gdf[gdf["iso_a2"].astype(str) == str(iso)]
        codes, geoms, _, _ = country_units(sub, country_roster(str(iso)), water=water)
    return codes, _polygons(codes, geoms, simplify_tol)


__all__ = ["region_outlines"]
