"""Land-only geometry: clip lake basins out of administrative polygons.

Natural Earth partitions lakes among the units that surround them, so a lake
basin is a LONG shared boundary and sails past the metric eps. That is why the
committed artifact carried Michigan-Illinois and Michigan-Minnesota: the eps rule
correctly rejects point contacts but cannot tell land from water.

Rivers are deliberately NOT masked — NE ships them as lines, and a river border
is a real border.
"""
from __future__ import annotations

from . import require_geo

# Lakes smaller than this are left alone, so that a small lake straddling a
# border cannot sever it. The five Great Lakes are orders of magnitude above it.
DEFAULT_MIN_LAKE_AREA_KM2 = 500.0


def water_mask(data_dir: str, *, min_area_km2: float = DEFAULT_MIN_LAKE_AREA_KM2):
    """Union of NE 10m lakes larger than `min_area_km2`, or None if none qualify.

    Area is measured in an equal-area projection (Mollweide), never in degrees.
    """
    require_geo()
    import geopandas as gpd
    from shapely.ops import unary_union
    from .naturalearth import fetch_natural_earth

    gdf = gpd.read_file(fetch_natural_earth(data_dir)["lakes"])
    km2 = gdf.to_crs("ESRI:54009").area / 1.0e6
    keep = gdf[km2.values > min_area_km2]
    if keep.empty:
        return None
    return unary_union(list(keep.geometry.values))


def clip_units(geoms: dict, mask) -> dict:
    """{key: geometry} with `mask` subtracted from every unit.

    A unit the mask would erase entirely keeps its original geometry: losing a
    vertex is a worse failure than leaving one unclipped, and it would silently
    change `n`.
    """
    if mask is None:
        return dict(geoms)
    require_geo()
    from shapely.validation import make_valid

    out = {}
    for key, geom in geoms.items():
        clipped = geom.difference(mask)
        out[key] = geom if clipped.is_empty else make_valid(clipped)
    return out
