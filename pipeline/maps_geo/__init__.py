"""Geodata pipeline (Unit C of the map-aware visualizer).

Turns Natural Earth administrative polygons into (n, edges, positions) graphs and
writes them as the ``maps`` artifact (``maps_geo.artifact``). Building needs
geopandas + shapely; reading a committed artifact needs no geo deps.
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    import geopandas  # noqa: F401
    import shapely  # noqa: F401
    HAVE_GEO = True
except Exception:  # noqa: BLE001 — any import failure means the extra is absent
    HAVE_GEO = False


class MapsGeoUnavailable(RuntimeError):
    """Raised when the [geo] extra is not installed."""


@dataclass
class GeoGraph:
    n: int
    edges: list = field(default_factory=list)      # list[tuple[int, int]], u < v, sorted
    positions: list = field(default_factory=list)  # list[[x, y]] normalized 0..1, y flipped (north up)
    labels: list = field(default_factory=list)     # list[str], index == vertex id
    granularity: str | None = None                 # admin level ("states"/"provinces"/...) or None
    codes: list = field(default_factory=list)      # list[str] ISO 3166-2, index == vertex id
    adjacency: dict = field(default_factory=dict)  # provenance block for the artifact


def require_geo() -> None:
    if not HAVE_GEO:
        raise MapsGeoUnavailable(
            "the 'geo' extra is required for the geodata pipeline — "
            "install it with:  uv pip install geopandas shapely")


__all__ = ["GeoGraph", "MapsGeoUnavailable", "HAVE_GEO", "require_geo"]
