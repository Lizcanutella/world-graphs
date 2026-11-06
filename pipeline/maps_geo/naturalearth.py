"""Fetch + load Natural Earth admin-0/admin-1 into GeoGraphs (pinned sources)."""
from __future__ import annotations

import io
import os
import urllib.request
import zipfile

from . import require_geo
from .adjacency import DEFAULT_EPS_M
from . import GeoGraph
from .policy import DEFAULT_POLICY
from .roster import admin1_granularity_label  # noqa: F401 — re-exported for callers

# Pinned Natural Earth sources (reachable, versioned by the CDN).
# admin-0 is 10m to match admin-1: the 110m file ships only 177 units by design,
# omitting microstates and most island states.
_URLS = {
    "admin0": ("https://naciscdn.org/naturalearth/10m/cultural/"
               "ne_10m_admin_0_countries.zip", "ne_10m_admin_0_countries.shp"),
    "admin1": ("https://naciscdn.org/naturalearth/10m/cultural/"
               "ne_10m_admin_1_states_provinces.zip",
               "ne_10m_admin_1_states_provinces.shp"),
    "lakes": ("https://naciscdn.org/naturalearth/10m/physical/ne_10m_lakes.zip",
              "ne_10m_lakes.shp"),
    "ocean": ("https://naciscdn.org/naturalearth/10m/physical/ne_10m_ocean.zip",
              "ne_10m_ocean.shp"),
}


def fetch_natural_earth(data_dir: str) -> dict:
    require_geo()
    os.makedirs(data_dir, exist_ok=True)
    out = {}
    for kind, (url, shp) in _URLS.items():
        target = os.path.join(data_dir, shp)
        if not os.path.exists(target):
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(data_dir)
        out[kind] = target
    return out


def _admin0_key(gdf):
    """ADM0_A3 — Natural Earth's always-populated admin-0 code.

    ISO_A3 is '-99' for France, Norway, Kosovo, N. Cyprus and Somaliland; the
    old fallback substituted the ADMIN *name*, mixing display names into the key
    space (and letting same-named units merge under dissolve).
    """
    return gdf["ADM0_A3"].astype(str).values


def _admin1_cols(gdf):
    """(iso_col, key_col, label_col) for the admin-1 layer.

    key_col is a stable unit ID (`adm1_code`); label_col is the display name.
    Keying on the name merged distinct same-named provinces into one vertex.
    """
    iso_col = "iso_a2" if "iso_a2" in gdf.columns else "adm0_a3"
    key_col = "adm1_code" if "adm1_code" in gdf.columns else (
        "name" if "name" in gdf.columns else "gn_name")
    label_col = "name" if "name" in gdf.columns else "gn_name"
    return iso_col, key_col, label_col


def world_geograph(data_dir: str, *, eps: float = DEFAULT_EPS_M,
                   policy: str = DEFAULT_POLICY, water=None, curated=None):
    """The admin-0 world GeoGraph under an inclusion `policy` (Unit 4b).

    `policy="un195"` (default) merges non-member NE units into their UN-recognised
    sovereign and drops units with none (see `maps_geo.policy`); `"natural_earth"`
    keeps every polity as its own vertex. Both drop the non-polity junk features.
    A `un195` build asserts exactly 195 units (fail loudly, Risk 7).

    Like the country maps, geometry is lake-clipped when `water` is given (this
    removes exactly DRC-Tanzania, a Lake Tanganyika border) and edges are
    classified against the curated snapshot's ISO 3166-1 (P297) pairs. `codes`
    are the vertex keys (ADM0_A3).
    """
    require_geo()
    import geopandas as gpd
    from .adjacency import normalize_positions
    from .build import _labels_for, _provenance, _reconciled_adjacency, world_units
    from .policy import UN195_EXPECTED_COUNT, assign_world_vertices
    paths = fetch_natural_earth(data_dir)
    gdf = gpd.read_file(paths["admin0"])
    block = assign_world_vertices(gdf, policy)
    codes, geoms = world_units(block, water=water)
    if policy == "un195" and len(codes) != UN195_EXPECTED_COUNT:
        raise ValueError(
            f"un195 world has {len(codes)} units, expected {UN195_EXPECTED_COUNT} "
            "(193 UN members + Vatican + Palestine) — Natural Earth's 10m unit "
            "inventory no longer matches the UN list after merging; review "
            "maps_geo.policy before shipping")
    a2 = {str(k): str(v) for k, v in zip(gdf["ADM0_A3"], gdf["ISO_A2_EH"])}
    edges, rec = _reconciled_adjacency(
        codes, geoms, eps=eps, curated=curated,
        curated_key=lambda c: a2.get(c) if len(a2.get(c, "")) == 2 else None)
    reps = [geoms[c].representative_point() for c in codes]
    return GeoGraph(n=len(codes), edges=edges,
                    positions=normalize_positions([(p.x, p.y) for p in reps]),
                    labels=_labels_for(block, key="_key", label="_label", keys=codes),
                    codes=list(codes),
                    adjacency=_provenance(rec, eps=eps, water=water))


def _country_geographs_from_gdf(gdf, *, eps=DEFAULT_EPS_M, min_units: int = 2,
                                water=None, curated=None, overrides=None) -> dict:
    """Admin-1 GeoDataFrame -> {alpha2: GeoGraph}, one vertex per ISO 3166-2 code.

    Grouping is by NE's `iso_a2`, skipping the non-country `-99`/`-1` values —
    that is what keeps the unassigned rows from forming a fake country (the
    shipped `iso-1` instance of Akrotiri, Baykonur, Kashmir, ...). `iso_a2` is
    also what keeps Puerto Rico (filed as `PR`, coded `US-PR`) off the US map.
    """
    from .build import roster_geograph
    from .roster import country_roster

    out = {}
    for alpha2, sub in gdf.groupby(gdf["iso_a2"].astype(str)):
        if len(alpha2) != 2 or not alpha2.isalpha():
            continue                       # "-99" and "-1" are not countries
        g = roster_geograph(sub, country_roster(alpha2.upper()), eps=eps,
                            water=water, curated=curated, overrides=overrides,
                            iso=alpha2.upper())
        if g.n >= min_units:
            out[alpha2.upper()] = g
    return out


def country_geographs(data_dir: str, *, eps: float = DEFAULT_EPS_M,
                      min_units: int = 2, water=None, curated=None, overrides=None) -> dict:
    require_geo()
    import geopandas as gpd
    paths = fetch_natural_earth(data_dir)
    from .overrides import apply_relabels
    gdf = apply_relabels(gpd.read_file(paths["admin1"]), overrides)
    return _country_geographs_from_gdf(gdf, eps=eps, min_units=min_units,
                                       water=water, curated=curated, overrides=overrides)
