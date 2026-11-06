"""Inclusion-policy unit tests — Unit 4b of the 2026-07-17 map gallery design.

Pure logic over a small synthetic admin-0 GeoDataFrame (no Natural Earth
download, no WG_RUN_GEO_BUILD gate): asserts the un195 unit-mapping rule and
the natural_earth companion world, including the two politically load-bearing
consequences the design calls out — Palestine stays its own observer vertex
(NE files it under SOVEREIGNT='Israel') and contested units merge per the
explicit table (Taiwan -> China).
"""
import pytest

pytest.importorskip("geopandas")


def _sq(x0, y0):
    from shapely.geometry import Polygon
    return Polygon([(x0, y0), (x0 + 1, y0), (x0 + 1, y0 + 1), (x0, y0 + 1)])


def _mini_admin0():
    """A miniature admin-0 frame exercising every policy branch.

    Columns mirror the Natural Earth admin-0 shapefile: ADM0_A3 (stable key),
    ADMIN (display name), SOVEREIGNT + SOV_A3 (NE's sovereign grouping; a
    sovereign's *home* unit has ADMIN == SOVEREIGNT).
    """
    import geopandas as gpd
    rows = [
        # home units (ADMIN == SOVEREIGNT)
        {"ADM0_A3": "FRA", "ADMIN": "France", "SOVEREIGNT": "France", "SOV_A3": "FR1", "geometry": _sq(0, 0)},
        {"ADM0_A3": "CHN", "ADMIN": "China", "SOVEREIGNT": "China", "SOV_A3": "CH1", "geometry": _sq(2, 0)},
        {"ADM0_A3": "ISR", "ADMIN": "Israel", "SOVEREIGNT": "Israel", "SOV_A3": "IS1", "geometry": _sq(4, 0)},
        # dependency -> merges into its sovereign (France) under un195
        {"ADM0_A3": "NCL", "ADMIN": "New Caledonia", "SOVEREIGNT": "France", "SOV_A3": "FR1", "geometry": _sq(6, 0)},
        # contested: NE marks sovereign; UN reassigns (Taiwan -> China)
        {"ADM0_A3": "TWN", "ADMIN": "Taiwan", "SOVEREIGNT": "Taiwan", "SOV_A3": "TWN", "geometry": _sq(8, 0)},
        # observer NE files under Israel; must NOT fold into ISR
        {"ADM0_A3": "PSX", "ADMIN": "Palestine", "SOVEREIGNT": "Israel", "SOV_A3": "IS1", "geometry": _sq(10, 0)},
        # dropped under un195 (no UN-recognised sovereign)
        {"ADM0_A3": "SAH", "ADMIN": "Western Sahara", "SOVEREIGNT": "Western Sahara", "SOV_A3": "SAH", "geometry": _sq(12, 0)},
        {"ADM0_A3": "ATA", "ADMIN": "Antarctica", "SOVEREIGNT": "Antarctica", "SOV_A3": "ATA", "geometry": _sq(14, 0)},
        # non-polity junk -> dropped from BOTH worlds
        {"ADM0_A3": "BRI", "ADMIN": "Brazilian Island", "SOVEREIGNT": "Brazilian Island", "SOV_A3": "BRI", "geometry": _sq(16, 0)},
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _keys(block):
    return set(block["_key"].astype(str))


def _label_of(block, key):
    m = dict(zip(block["_key"].astype(str), block["_label"].astype(str)))
    return m[key]


def test_natural_earth_keeps_every_polity_drops_only_junk():
    from maps_geo.policy import assign_world_vertices
    block = assign_world_vertices(_mini_admin0(), "natural_earth")
    # every polity its own vertex; only the non-polity junk (BRI) is dropped.
    assert _keys(block) == {"FRA", "CHN", "ISR", "NCL", "TWN", "PSX", "SAH", "ATA"}
    # contested units are shown separately here — that is the point of this world.
    assert _label_of(block, "TWN") == "Taiwan"


def test_un195_merges_dependency_into_sovereign():
    from maps_geo.policy import assign_world_vertices
    block = assign_world_vertices(_mini_admin0(), "un195")
    # New Caledonia folds into France; France stays one vertex.
    assert "NCL" not in _keys(block)
    assert "FRA" in _keys(block)
    assert _label_of(block, "FRA") == "France"


def test_un195_applies_contested_table():
    from maps_geo.policy import assign_world_vertices
    block = assign_world_vertices(_mini_admin0(), "un195")
    # Taiwan is not a vertex; it is merged into China (UNGA 2758) and shows China's name.
    assert "TWN" not in _keys(block)
    assert "CHN" in _keys(block)
    assert _label_of(block, "CHN") == "China"


def test_un195_keeps_palestine_as_own_observer_vertex():
    from maps_geo.policy import assign_world_vertices
    block = assign_world_vertices(_mini_admin0(), "un195")
    # NE files Palestine under SOVEREIGNT='Israel'; the mechanical merge would
    # fold PSX into ISR. The observer override keeps it separate.
    assert "PSX" in _keys(block)
    assert _label_of(block, "PSX") == "Palestine"


def test_un195_drops_western_sahara_and_antarctica():
    from maps_geo.policy import assign_world_vertices
    block = assign_world_vertices(_mini_admin0(), "un195")
    assert "SAH" not in _keys(block)
    assert "ATA" not in _keys(block)


def test_non_polity_junk_dropped_from_both_worlds():
    from maps_geo.policy import assign_world_vertices
    for policy in ("un195", "natural_earth"):
        block = assign_world_vertices(_mini_admin0(), policy)
        assert "BRI" not in _keys(block), f"junk BRI leaked into {policy}"


def test_unknown_policy_raises():
    from maps_geo.policy import assign_world_vertices
    with pytest.raises(ValueError, match="policy"):
        assign_world_vertices(_mini_admin0(), "everything")
