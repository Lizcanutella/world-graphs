"""Unit C — geodata pipeline tests (maps_geo)."""
import pytest

# geopandas is the optional [geo] extra; without it these tests cannot run, so skip
# the module rather than failing (`uv pip install -e ".[geo]"` to actually run them).
pytest.importorskip("geopandas")


def test_geograph_dataclass_defaults():
    from maps_geo import GeoGraph
    g = GeoGraph(n=3, edges=[(0, 1), (1, 2)], positions=[[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]],
                 labels=["a", "b", "c"])
    assert g.n == 3 and g.edges == [(0, 1), (1, 2)]
    assert len(g.positions) == 3 and g.labels[2] == "c"


def test_require_geo_present():
    # geo deps are installed in this env; require_geo must not raise.
    from maps_geo import require_geo, HAVE_GEO
    assert HAVE_GEO
    require_geo()  # no exception


def _sq(x0, y0, x1, y1):
    from shapely.geometry import Polygon
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_geo_adjacency_path_of_three():
    # Three unit squares in a row: 0-1 share an edge, 1-2 share an edge, 0-2 don't.
    # (1° ≈ 111 km, far above the 100 m default metric eps.)
    from maps_geo.adjacency import geo_adjacency
    geoms = {0: _sq(0, 0, 1, 1), 1: _sq(1, 0, 2, 1), 2: _sq(2, 0, 3, 1)}
    assert geo_adjacency(geoms, eps=100.0) == [(0, 1), (1, 2)]


def test_geo_adjacency_corner_touch_suppressed():
    # Diagonal squares touch at a single point → shared-border length 0 → no edge.
    from maps_geo.adjacency import geo_adjacency
    geoms = {0: _sq(0, 0, 1, 1), 1: _sq(1, 1, 2, 2)}
    assert geo_adjacency(geoms, eps=100.0) == []


def test_geo_adjacency_eps_is_metric_not_degrees():
    # Unit 3: `eps` is geodesic METRES, not a coordinate angle. Two boxes near the
    # equator share a ~445 m border (0.004° of longitude). The old 0.01°-degree
    # threshold dropped it (0.004 < 0.01) even though it is a real border — the
    # exact Vatican–Italy failure mode. Under a 100 m metric eps it is an edge;
    # under a 1 km metric eps it is (correctly, by that threshold) not.
    from maps_geo.adjacency import geo_adjacency
    geoms = {0: _sq(0.0, 0.0, 0.5, 0.004), 1: _sq(0.5, 0.0, 1.0, 0.004)}
    assert geo_adjacency(geoms, eps=100.0) == [(0, 1)]     # ~445 m > 100 m
    assert geo_adjacency(geoms, eps=1000.0) == []          # ~445 m < 1 km


def test_normalize_positions_flips_y():
    from maps_geo.adjacency import normalize_positions
    # lat increases north; after flip, the northern point gets the smaller y.
    out = normalize_positions([(0.0, 0.0), (10.0, 90.0)])  # (lon, lat)
    assert out[0] == [0.0, 1.0]      # south → bottom (y=1)
    assert out[1] == [1.0, 0.0]      # north → top   (y=0)


def test_gdf_to_geograph_dissolve_and_adjacency():
    import geopandas as gpd
    from maps_geo.build import gdf_to_geograph
    # "B" is two disjoint squares (islands) → must dissolve to ONE vertex.
    rows = [
        {"name": "A", "geometry": _sq(0, 0, 1, 1)},
        {"name": "B", "geometry": _sq(1, 0, 2, 1)},
        {"name": "B", "geometry": _sq(5, 5, 6, 6)},   # island of B
        {"name": "C", "geometry": _sq(2, 0, 3, 1)},
    ]
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    g = gdf_to_geograph(gdf, key="name", eps=100.0)
    assert g.n == 3                       # A, B, C — B's island merged
    assert g.labels == ["A", "B", "C"]
    assert g.edges == [(0, 1), (1, 2)]    # A-B, B-C (path)
    assert len(g.positions) == 3


def test_build_maps_ships_both_worlds_with_policy_params():
    from maps_geo import GeoGraph
    from maps_geo.build import build_maps
    # build_maps ships one map_world instance PER inclusion policy, each tagged
    # params={"policy": ...}. Worlds: un195 = triangle (K3), natural_earth = path P3
    # (a different graph, to prove they are distinct instances). One country = path P3.
    un195 = GeoGraph(n=3, edges=[(0, 1), (1, 2), (0, 2)],
                     positions=[[0, 0], [1, 0], [0.5, 1]], labels=["X", "Y", "Z"])
    ne = GeoGraph(n=3, edges=[(0, 1), (1, 2)],
                  positions=[[0, 0], [1, 0], [2, 0]], labels=["X", "Y", "Z"])
    p3 = GeoGraph(n=3, edges=[(0, 1), (1, 2)],
                  positions=[[0, 0], [0.5, 0], [1, 0]], labels=["a", "b", "c"])
    manifest, instances = build_maps(
        {"un195": un195, "natural_earth": ne}, {"AAA": p3}, eps=100.0,
        data_source="unit-test")
    assert manifest.n_instances == 3
    assert manifest.counts == {"map_world": 2, "map_country": 1}
    assert manifest.extra["eps"] == 100.0 and manifest.extra["eps_unit"] == "metres"
    assert manifest.extra["data_source"] == "unit-test"
    worlds = [i for i in instances if i.family == "map_world"]
    assert {w.params["policy"] for w in worlds} == {"un195", "natural_earth"}
    un195_inst = next(w for w in worlds if w.params["policy"] == "un195")
    assert un195_inst.edges == [(0, 1), (1, 2), (0, 2)]
    assert un195_inst.positions == [[0, 0], [1, 0], [0.5, 1]]
    assert un195_inst.id == "map_world-n3-policyun195"
    country = next(i for i in instances if i.family == "map_country")
    assert country.params == {"iso": "AAA"}


def test_build_maps_ships_every_country_whatever_its_size():
    # No size cap: a 300-unit country ships like a 3-unit one, with its granularity.
    from maps_geo import GeoGraph
    from maps_geo.build import build_maps

    def mk(n, level=None):
        return GeoGraph(n=n, edges=[(i, i + 1) for i in range(n - 1)],
                        positions=[[0, 0]] * n, labels=[f"r{i}" for i in range(n)],
                        granularity=level)

    _, insts = build_maps({}, {"BIG": mk(300, "municipalities"), "SML": mk(3)},
                          eps=100.0, data_source="test")
    by_iso = {i.params["iso"]: i for i in insts}
    assert set(by_iso) == {"BIG", "SML"}
    assert by_iso["BIG"].n == 300 and len(by_iso["BIG"].edges) == 299
    assert by_iso["BIG"].params == {"iso": "BIG", "granularity": "municipalities"}
    assert by_iso["SML"].params == {"iso": "SML"}


def test_artifact_round_trips(tmp_path):
    from maps_geo import GeoGraph
    from maps_geo.artifact import load, write
    from maps_geo.build import build_maps
    g = GeoGraph(n=3, edges=[(0, 1), (1, 2)], positions=[[0, 0], [0.5, 0], [1, 0]],
                 labels=["a", "b", "c"], codes=["X-A", "X-B", "X-C"],
                 adjacency={"source": "reconciled"})
    manifest, insts = build_maps({}, {"XX": g}, eps=100.0, data_source="test")
    write(str(tmp_path), manifest, insts)
    m2, back = load(str(tmp_path))
    assert m2 == manifest and back == insts


def test_naturalearth_module_imports():
    # Pure import + signature check (no network).
    from maps_geo.naturalearth import (
        fetch_natural_earth, world_geograph, country_geographs)
    assert callable(fetch_natural_earth)
    assert callable(world_geograph) and callable(country_geographs)


def test_admin0_source_is_10m():
    # 110m ships exactly 177 units by design and omits microstates (Liechtenstein,
    # Vatican, San Marino, Singapore...). The oracle in test_maps_geo_oracle.py
    # asserts on those, so admin-0 must match admin-1's 10m scale.
    from maps_geo.naturalearth import _URLS
    url, shp = _URLS["admin0"]
    assert "/10m/" in url and "ne_10m_admin_0_countries" in shp


@pytest.mark.skipif(
    "WG_RUN_GEO_BUILD" not in __import__("os").environ,
    reason="real Natural Earth build — set WG_RUN_GEO_BUILD=1 to run")
def test_real_world_geograph_smoke(tmp_path):
    from maps_geo.naturalearth import world_geograph
    g = world_geograph(str(tmp_path), eps=100.0)
    assert g.n > 100 and len(g.edges) > 100
    assert all(u < v for (u, v) in g.edges)


@pytest.mark.skipif(
    "WG_RUN_GEO_BUILD" not in __import__("os").environ,
    reason="real Natural Earth build — set WG_RUN_GEO_BUILD=1 to run")
def test_real_world_un195_is_exactly_195(tmp_path):
    # Unit 4b: the un195 world is the 193 UN members + 2 observers, and the build
    # asserts the headline count rather than shipping a quietly-wrong 194/196.
    from maps_geo.naturalearth import world_geograph
    from maps_geo.policy import UN195_EXPECTED_COUNT
    g = world_geograph(str(tmp_path), eps=100.0, policy="un195")
    assert g.n == UN195_EXPECTED_COUNT == 195


@pytest.mark.skipif(
    "WG_RUN_GEO_BUILD" not in __import__("os").environ,
    reason="real Natural Earth build — set WG_RUN_GEO_BUILD=1 to run")
def test_real_world_natural_earth_drops_only_junk(tmp_path):
    # The companion world keeps every NE polity; only the 9 non-polity junk
    # features are dropped (258 NE units - 9 = 249).
    from maps_geo.naturalearth import world_geograph
    g = world_geograph(str(tmp_path), eps=100.0, policy="natural_earth")
    assert g.n == 249


@pytest.mark.skipif(
    "WG_RUN_GEO_BUILD" not in __import__("os").environ,
    reason="real Natural Earth build — set WG_RUN_GEO_BUILD=1 to run")
def test_region_outlines_world_is_policy_aware(tmp_path):
    # Unit 4b: outlines.py must read the inclusion policy, not assume one world.
    # The reconstructed unit order + codes must match the shipped world for BOTH
    # policies, or the Gallery overlay would sit on the wrong vertices.
    from maps_geo.naturalearth import world_geograph
    from maps_geo.outlines import region_outlines
    for policy in ("un195", "natural_earth"):
        g = world_geograph(str(tmp_path), eps=100.0, policy=policy)
        codes, polys = region_outlines(str(tmp_path), family="map_world",
                                       policy=policy)
        assert codes == g.codes, f"{policy}: outline codes != world codes"
        assert len(polys) == g.n


def test_outlines_align_with_positions():
    # Region outlines must be normalized by the SAME centroid box as positions,
    # so each unit's border encloses its own served centroid.
    import geopandas as gpd
    from shapely.geometry import Point, Polygon
    from maps_geo.outlines import _outlines_from_gdf
    from maps_geo.adjacency import normalize_positions

    geoms = [_sq(0, 0, 1, 1), _sq(1, 0, 2, 1), _sq(1, 1, 2, 2)]
    gdf = gpd.GeoDataFrame({"_key": ["a", "b", "c"], "geometry": geoms})
    keys, polys = _outlines_from_gdf(gdf, key="_key", simplify_tol=0)

    assert keys == ["a", "b", "c"]                       # sorted-key vertex order
    reps = [g.representative_point() for g in geoms]
    positions = normalize_positions([(p.x, p.y) for p in reps])
    for pos, rings in zip(positions, polys):
        pt = Point(pos[0], pos[1])
        assert any(Polygon(r).buffer(1e-9).contains(pt) for r in rings if len(r) >= 4)


def test_outlines_y_flipped_north_up():
    # Northern unit (higher lat) must get the smaller y (renders up), matching
    # normalize_positions' flip.
    import geopandas as gpd
    from maps_geo.outlines import _outlines_from_gdf
    geoms = [_sq(0, 0, 1, 1), _sq(0, 2, 1, 3)]           # south, north
    gdf = gpd.GeoDataFrame({"_key": ["south", "north"], "geometry": geoms})
    keys, polys = _outlines_from_gdf(gdf, key="_key", simplify_tol=0)
    by = {k: min(p[1] for r in rings for p in r) for k, rings in zip(keys, polys)}
    assert by["north"] < by["south"]                     # north renders up (smaller y)


def test_gdf_to_geograph_label_column_separate_from_key():
    # Two DISTINCT units sharing a display name must stay two vertices.
    # Keying on the name (the old behaviour) silently merged them.
    import geopandas as gpd
    from maps_geo.build import gdf_to_geograph
    rows = [
        {"adm1_code": "AR-S", "name": "Santiago", "geometry": _sq(0, 0, 1, 1)},
        {"adm1_code": "AR-T", "name": "Santiago", "geometry": _sq(5, 5, 6, 6)},
    ]
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    g = gdf_to_geograph(gdf, key="adm1_code", label="name", eps=100.0)
    assert g.n == 2                          # NOT merged
    assert g.labels == ["Santiago", "Santiago"]   # labels may repeat; keys may not


def test_gdf_to_geograph_label_defaults_to_key():
    # Omitting `label` must preserve the old behaviour exactly.
    import geopandas as gpd
    from maps_geo.build import gdf_to_geograph
    rows = [{"k": "A", "geometry": _sq(0, 0, 1, 1)},
            {"k": "B", "geometry": _sq(1, 0, 2, 1)}]
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    g = gdf_to_geograph(gdf, key="k", eps=100.0)
    assert g.labels == ["A", "B"]


def test_gdf_to_geograph_label_still_dissolves_multipart():
    # A genuine multi-part unit (island + mainland) shares ONE key and must
    # still collapse to one vertex — duplicate keys are legal.
    import geopandas as gpd
    from maps_geo.build import gdf_to_geograph
    rows = [
        {"code": "A", "nm": "Ayland", "geometry": _sq(0, 0, 1, 1)},
        {"code": "A", "nm": "Ayland", "geometry": _sq(9, 9, 10, 10)},  # its island
        {"code": "B", "nm": "Bee",    "geometry": _sq(1, 0, 2, 1)},
    ]
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    g = gdf_to_geograph(gdf, key="code", label="nm", eps=100.0)
    assert g.n == 2 and g.labels == ["Ayland", "Bee"]
    assert g.edges == [(0, 1)]


def test_admin0_key_uses_stable_code_not_name():
    # ISO_A3 is '-99' for France/Norway/Kosovo/N.Cyprus/Somaliland. The old code
    # fell back to the ADMIN *name*, putting display names in the key space.
    import geopandas as gpd
    from maps_geo.naturalearth import _admin0_key
    gdf = gpd.GeoDataFrame({
        "ISO_A3": ["-99", "ESP"],
        "ADM0_A3": ["FRA", "ESP"],
        "ADMIN": ["France", "Spain"],
        "geometry": [_sq(0, 0, 1, 1), _sq(1, 0, 2, 1)],
    }, crs="EPSG:4326")
    assert list(_admin0_key(gdf)) == ["FRA", "ESP"]      # not ["France", "ESP"]


def test_outlines_return_labels_matching_geograph_labels():
    # serve.py guards the overlay with `keys != inst.labels`, so outlines must
    # return the SAME strings gdf_to_geograph puts in GeoGraph.labels, in the
    # same (sorted-key) order — otherwise the guard fires forever once keys and
    # labels stop being the same string.
    import geopandas as gpd
    from maps_geo.build import gdf_to_geograph
    from maps_geo.outlines import _outlines_from_gdf
    rows = [
        {"_key": "B-2", "_label": "Beta", "geometry": _sq(1, 0, 2, 1)},
        {"_key": "A-1", "_label": "Alpha", "geometry": _sq(0, 0, 1, 1)},
    ]
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    g = gdf_to_geograph(gdf, key="_key", label="_label", eps=100.0)
    names, polys = _outlines_from_gdf(gdf, key="_key", label="_label", simplify_tol=0)
    assert names == g.labels == ["Alpha", "Beta"]     # sorted by KEY, not label
    assert len(polys) == 2


def test_outlines_label_defaults_to_key():
    # Existing callers that pass no label keep getting keys back.
    import geopandas as gpd
    from maps_geo.outlines import _outlines_from_gdf
    gdf = gpd.GeoDataFrame({"_key": ["a", "b"], "_label": ["A", "B"],
                            "geometry": [_sq(0, 0, 1, 1), _sq(1, 0, 2, 1)]},
                           crs="EPSG:4326")
    names, _ = _outlines_from_gdf(gdf, key="_key", simplify_tol=0)
    assert names == ["a", "b"]


# --- Unit 7: administrative-granularity labels ---------------------------------

def test_normalize_granularity_maps_known_levels_and_omits_when_absent():
    from maps_geo.naturalearth import admin1_granularity_label
    # Dominant Natural Earth `type_en` -> a clean plural label.
    assert admin1_granularity_label(["State", "State", "District"]) == "states"
    assert admin1_granularity_label(["Province"]) == "provinces"
    assert admin1_granularity_label(["Municipality"]) == "municipalities"
    assert admin1_granularity_label(["District", "District"]) == "districts"
    # Never guess a level: empty / all-missing -> None (label omitted).
    assert admin1_granularity_label([]) is None
    assert admin1_granularity_label([None, None, ""]) is None
    # pandas reads a missing type_en cell as float NaN (str() -> "nan"); it must
    # count as missing, not as a level literally named "nan".
    assert admin1_granularity_label([float("nan")]) is None
    assert admin1_granularity_label(["nan", "NaN", "None"]) is None
    assert admin1_granularity_label([float("nan"), "Province", float("nan")]) == "provinces"
    # An unknown type is reported honestly (lowercased NE value), not fabricated.
    assert admin1_granularity_label(["Emirate"]) == "emirate"


def test_build_maps_country_params_carry_granularity_when_known():
    from maps_geo import GeoGraph
    from maps_geo.build import build_maps
    p3 = GeoGraph(n=3, edges=[(0, 1), (1, 2)], positions=[[0, 0], [0.5, 0], [1, 0]],
                  labels=["a", "b", "c"], granularity="provinces")
    p2 = GeoGraph(n=2, edges=[(0, 1)], positions=[[0, 0], [1, 0]],
                  labels=["a", "b"])  # granularity unknown -> None
    manifest, insts = build_maps(
        worlds={}, countries={"AAA": p3, "BBB": p2}, eps=100.0, data_source="test")
    by_iso = {i.params["iso"]: i for i in insts}
    assert by_iso["AAA"].params == {"iso": "AAA", "granularity": "provinces"}
    # Unknown level omits the key entirely — never a guessed placeholder.
    assert by_iso["BBB"].params == {"iso": "BBB"}



def _gdf(rows):
    """rows: [(iso_3166_2, name, geometry)] -> GeoDataFrame like NE admin-1."""
    import geopandas as gpd
    return gpd.GeoDataFrame(
        {"iso_3166_2": [r[0] for r in rows], "name": [r[1] for r in rows],
         "geometry": [r[2] for r in rows]}, crs="EPSG:4326")


def test_roster_geograph_dissolves_multi_row_units_into_one_vertex():
    # The spurious-node bug: NE ships 60 ISO codes as several rows (BA-BIH has 9).
    # Keying on the ISO code must collapse them into a single vertex.
    from maps_geo.build import roster_geograph
    from maps_geo.roster import RosterUnit
    gdf = _gdf([("XX-A", "Alpha", _sq(0, 0, 1, 1)),
                ("XX-A", "Alpha", _sq(1, 0, 2, 1)),      # same unit, second piece
                ("XX-B", "Beta", _sq(2, 0, 3, 1))])
    units = [RosterUnit("XX-A", "Alpha", "Province"),
             RosterUnit("XX-B", "Beta", "Province")]
    g = roster_geograph(gdf, units, eps=100.0)
    assert g.n == 2
    assert g.codes == ["XX-A", "XX-B"]
    assert g.edges == [(0, 1)]


def test_roster_geograph_drops_roster_units_without_geometry():
    from maps_geo.build import roster_geograph
    from maps_geo.roster import RosterUnit
    gdf = _gdf([("XX-A", "Alpha", _sq(0, 0, 1, 1)),
                ("XX-B", "Beta", _sq(1, 0, 2, 1))])
    units = [RosterUnit("XX-A", "Alpha", "Province"),
             RosterUnit("XX-B", "Beta", "Province"),
             RosterUnit("XX-C", "Gamma", "Province")]      # no NE geometry
    g = roster_geograph(gdf, units, eps=100.0)
    assert g.codes == ["XX-A", "XX-B"]
    assert g.adjacency["roster"]["unmatched_roster"] == ["XX-C"]


def test_roster_geograph_keeps_ne_codes_missing_from_the_current_roster():
    # NE's codes are an older ISO vintage (PL-DS became PL-02). Intersecting with
    # pycountry's current roster matched zero units for PL, CZ, GT, KE, ... and
    # deleted whole countries, so NE's own codes are the vertex set.
    from maps_geo.build import roster_geograph
    from maps_geo.roster import RosterUnit
    gdf = _gdf([("XX-OLD", "Old", _sq(0, 0, 1, 1)),
                ("XX-A", "Alpha", _sq(1, 0, 2, 1))])
    g = roster_geograph(gdf, [RosterUnit("XX-A", "Alpha", "Province"),
                              RosterUnit("XX-NEW", "New", "Province")], eps=100.0)
    assert g.codes == ["XX-A", "XX-OLD"]
    assert g.edges == [(0, 1)]
    assert g.adjacency["roster"]["not_in_current_iso"] == ["XX-OLD"]
    assert g.adjacency["roster"]["unmatched_roster"] == ["XX-NEW"]


def test_roster_geograph_keeps_non_dominant_units_however_they_connect():
    # The removed outlying filter kept a non-dominant unit only if it touched a
    # dominant-type one, which dropped Chechnya (touches only a krai and other
    # republics), Budapest and all of Sicily. Every unit NE ships is kept.
    from maps_geo.build import roster_geograph
    from maps_geo.roster import RosterUnit
    gdf = _gdf([("XX-S1", "S1", _sq(0, 0, 1, 1)), ("XX-S2", "S2", _sq(1, 0, 2, 1)),
                ("XX-K", "Krai", _sq(2, 0, 3, 1)), ("XX-R", "Rep", _sq(3, 0, 4, 1)),
                ("XX-I", "Isl", _sq(40, 40, 41, 41))])
    units = [RosterUnit("XX-S1", "S1", "State"), RosterUnit("XX-S2", "S2", "State"),
             RosterUnit("XX-K", "Krai", "Krai"), RosterUnit("XX-R", "Rep", "Republic"),
             RosterUnit("XX-I", "Isl", "Outlying area")]
    g = roster_geograph(gdf, units, eps=100.0)
    assert g.codes == ["XX-I", "XX-K", "XX-R", "XX-S1", "XX-S2"]


def test_roster_geograph_drops_unidentified_unnamed_fragments():
    # Antarctica's second NE row has no name and a placeholder code: nothing can
    # label it, so it is dropped and recorded rather than shipped as "nan".
    from maps_geo.build import roster_geograph
    gdf = _gdf([("XX-A", "Alpha", _sq(0, 0, 1, 1)),
                ("XX-X02~", float("nan"), _sq(1, 0, 2, 1))])
    g = roster_geograph(gdf, [], eps=100.0)
    assert g.codes == ["XX-A"]
    assert g.adjacency["roster"]["dropped_unnamed"] == ["XX-X02~"]


def test_country_geographs_group_by_iso_a2_and_skip_unassigned():
    # `-1` rows formed the junk `iso-1` country; a `US-PR`-coded row filed under
    # iso_a2 = PR must not join the US map.
    import geopandas as gpd
    from maps_geo.naturalearth import _country_geographs_from_gdf
    rows = [("US", "US-AL", "Alabama", _sq(0, 0, 1, 1)),
            ("US", "US-GA", "Georgia", _sq(1, 0, 2, 1)),
            ("PR", "US-PR", "Puerto Rico", _sq(5, 0, 6, 1)),
            ("-1", "-99-X16~", "Kashmir", _sq(8, 0, 9, 1)),
            ("-1", "-99-X17~", "Baykonur", _sq(9, 0, 10, 1))]
    gdf = gpd.GeoDataFrame({"iso_a2": [r[0] for r in rows],
                            "iso_3166_2": [r[1] for r in rows],
                            "name": [r[2] for r in rows],
                            "geometry": [r[3] for r in rows]}, crs="EPSG:4326")
    out = _country_geographs_from_gdf(gdf, eps=100.0)
    assert sorted(out) == ["US"]
    assert out["US"].codes == ["US-AL", "US-GA"]


def test_reconciled_adjacency_maps_codes_into_the_curated_key_space():
    # The world path keys vertices on ADM0_A3 but the snapshot speaks alpha-2.
    from maps_geo.build import _reconciled_adjacency
    from maps_geo.curated import CuratedAdjacency
    geoms = {"AAA": _sq(0, 0, 1, 1), "BBB": _sq(1, 0, 2, 1), "CCC": _sq(2, 0, 3, 1)}
    cur = CuratedAdjacency(pairs={("AA", "BB"), ("AA", "CC")})
    edges, rec = _reconciled_adjacency(
        ["AAA", "BBB", "CCC"], geoms, eps=100.0, curated=cur,
        curated_key=lambda c: {"AAA": "AA", "BBB": "BB"}.get(c))
    assert edges == [(0, 1), (1, 2)]
    assert rec.counts == {"both": 1, "geometry_only": 1, "curated_only": 0}


def test_roster_geograph_labels_fall_back_to_the_official_name():
    # The NaN-label defect: NE sometimes ships a missing name as float NaN.
    from maps_geo.build import roster_geograph
    from maps_geo.roster import RosterUnit
    gdf = _gdf([("XX-A", float("nan"), _sq(0, 0, 1, 1)),
                ("XX-B", "Beta", _sq(1, 0, 2, 1))])
    units = [RosterUnit("XX-A", "Alpha", "Province"),
             RosterUnit("XX-B", "Beta", "Province")]
    g = roster_geograph(gdf, units, eps=100.0)
    assert g.labels == ["Alpha", "Beta"]
    assert all(isinstance(x, str) for x in g.labels)


def test_roster_geograph_keeps_differently_named_units_under_one_code_apart():
    # NE files distinct units under one code: Bogota under Cundinamarca's,
    # Madagascar's 22 regions under 6 old province codes, Bosnia's cantons under
    # BA-BIH. Merging them deletes real units (and a stale code's roster name
    # labelled Tehran+Alborz "Fars"), so only same-name rows dissolve.
    from maps_geo.build import roster_geograph
    from maps_geo.roster import RosterUnit
    gdf = _gdf([("XX-A", "Piece One", _sq(0, 0, 1, 1)),
                ("XX-A", "Piece Two", _sq(1, 0, 2, 1)),
                ("XX-B", "Beta", _sq(2, 0, 3, 1)),
                ("XX-B", float("nan"), _sq(3, 0, 4, 1))])   # nameless piece of Beta
    units = [RosterUnit("XX-A", "Wrong Official", "Province"),
             RosterUnit("XX-B", "Beta", "Province")]
    g = roster_geograph(gdf, units, eps=100.0)
    assert g.codes == ["XX-A:Piece One", "XX-A:Piece Two", "XX-B"]
    assert g.labels == ["Piece One", "Piece Two", "Beta"]
    assert g.edges == [(0, 1), (1, 2)]


def test_roster_geograph_disambiguates_only_repeated_labels():
    # NE ships Rasinski okrug (RS-19) mislabelled as a second "Pomoravski"; the
    # current ISO name fixes it. True namesakes get their NE unit type.
    import geopandas as gpd
    from maps_geo.build import roster_geograph
    from maps_geo.roster import RosterUnit
    rows = [("RS-13", "Pomoravski", "District", _sq(0, 0, 1, 1)),
            ("RS-19", "Pomoravski", "District", _sq(1, 0, 2, 1)),
            ("HU-VE", "Veszprém", "County", _sq(2, 0, 3, 1)),
            ("HU-VM", "Veszprém", "City", _sq(3, 0, 4, 1)),
            ("HU-BA", "Baranya", "County", _sq(4, 0, 5, 1))]
    gdf = gpd.GeoDataFrame({"iso_3166_2": [r[0] for r in rows],
                            "name": [r[1] for r in rows],
                            "type_en": [r[2] for r in rows],
                            "geometry": [r[3] for r in rows]}, crs="EPSG:4326")
    units = [RosterUnit("RS-13", "Pomoravski okrug", "District"),
             RosterUnit("RS-19", "Rasinski okrug", "District"),
             RosterUnit("HU-VE", "Veszprém", "County"),
             RosterUnit("HU-VM", "Veszprém", "City of county right"),
             RosterUnit("HU-BA", "Baranya megye", "County")]
    g = roster_geograph(gdf, units, eps=100.0)
    assert g.labels == ["Baranya", "Veszprém (County)", "Veszprém (City)",
                        "Pomoravski okrug", "Rasinski okrug"]


def test_roster_geograph_records_curated_provenance():
    from maps_geo.build import roster_geograph
    from maps_geo.curated import CuratedAdjacency
    from maps_geo.roster import RosterUnit
    gdf = _gdf([("XX-A", "Alpha", _sq(0, 0, 1, 1)),
                ("XX-B", "Beta", _sq(1, 0, 2, 1))])
    units = [RosterUnit("XX-A", "Alpha", "Province"),
             RosterUnit("XX-B", "Beta", "Province")]
    curated = CuratedAdjacency(pairs={("XX-A", "XX-B"), ("XX-A", "XX-Z")})
    g = roster_geograph(gdf, units, eps=100.0, curated=curated)
    assert g.adjacency["source"] == "reconciled"
    assert g.adjacency["counts"] == {"both": 1, "geometry_only": 0, "curated_only": 0}


# --- Gate 2: hand-checked ground truth, run against real Natural Earth data ---

_REAL = pytest.mark.skipif(
    "WG_RUN_GEO_BUILD" not in __import__("os").environ,
    reason="real Natural Earth build — set WG_RUN_GEO_BUILD=1 to run")


def _fixture(name):
    import json
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "fixtures", name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def real_countries():
    import os
    from maps_geo.curated import load_snapshot
    from maps_geo.landmask import water_mask
    from maps_geo.naturalearth import country_geographs
    data = os.environ.get("WG_GEODATA", "data/naturalearth")
    return country_geographs(data, water=water_mask(data), curated=load_snapshot())


def _code_edges(g):
    return {tuple(sorted((g.codes[u], g.codes[v]))) for (u, v) in g.edges}


# Australia, enumerated by hand from a map. Tasmania is an island and correctly
# has no edges; the ACT is an enclave in NSW; Jervis Bay Territory (NE code
# AU-X02~) touches only NSW.
AU_EDGES = {
    ("AU-ACT", "AU-NSW"), ("AU-NSW", "AU-QLD"), ("AU-NSW", "AU-SA"),
    ("AU-NSW", "AU-VIC"), ("AU-NT", "AU-QLD"), ("AU-NT", "AU-SA"),
    ("AU-NT", "AU-WA"), ("AU-QLD", "AU-SA"), ("AU-SA", "AU-VIC"),
    ("AU-SA", "AU-WA"), ("AU-NSW", "AU-X02~"),
}


@_REAL
def test_gate2_us_states_match_hand_checked_adjacency(real_countries):
    g = real_countries["US"]
    fx = _fixture("us_state_adjacency.json")
    assert g.n == fx["n"]
    assert _code_edges(g) == {tuple(e) for e in fx["edges"]}
    for code in fx["must_contain_codes"]:
        assert code in g.codes
    for code in fx["must_not_contain_codes"]:
        assert code not in g.codes


@_REAL
def test_gate2_australia_matches_hand_checked_adjacency(real_countries):
    g = real_countries["AU"]
    assert {"AU-NT", "AU-ACT", "AU-TAS", "AU-X02~"} <= set(g.codes)
    assert _code_edges(g) == AU_EDGES


@_REAL
def test_gate2_no_real_unit_or_country_is_deleted(real_countries):
    # Each of these was deleted by the first draft of this pipeline: whole
    # countries by the roster-vintage mismatch, mainland units by the outlying
    # filter. See the spec's 2026-09-26 amendment.
    for iso, n in {"PL": 16, "CZ": 14, "GT": 22, "KE": 8, "NP": 14, "LU": 3,
                   "NO": 21, "EE": 15, "XK": 30, "HK": 18}.items():
        assert real_countries[iso].n == n, iso
    must = {"RU": ["RU-CE", "RU-DA", "RU-PRI"], "IT": ["IT-PA", "IT-CT"],
            "HU": ["HU-BU"], "TW": ["TW-TPE", "TW-KEE"], "TJ": ["TJ-DU"],
            "BR": ["BR-DF"], "IN": ["IN-DL"], "CO": ["CO-CUN:Bogota"],
            "GB": ["GB-EDH", "GB-GLG"]}
    for iso, codes in must.items():
        for c in codes:
            assert c in real_countries[iso].codes, (iso, c)


@_REAL
def test_gate2_reported_split_units_are_one_vertex(real_countries):
    # The user-reported defect: one unit arriving as two touching vertices.
    for iso, code in [("MW", "MW-CT"), ("AF", "AF-URU"), ("AF", "AF-PAR"),
                      ("MD", "MD-RE"), ("HR", "HR-12")]:
        g = real_countries[iso]
        assert g.codes.count(code) == 1, (iso, code)
        assert len(set(g.labels)) == g.n, iso


# --- Gate 3: structural invariants over the committed artifact ---

def test_gate3_committed_maps_satisfy_structural_invariants():
    from maps_geo.artifact import load
    from maps_geo.audit import _edges_of
    _, instances = load("data/maps")
    for inst in instances:
        ctx = inst.id
        assert len(inst.codes) == inst.n, ctx
        assert len(inst.labels) == inst.n, ctx
        assert len(inst.positions) == inst.n, ctx
        assert len(set(inst.codes)) == inst.n, f"duplicate codes in {ctx}"
        assert all(isinstance(x, str) and x for x in inst.labels), ctx
        seen = set()
        for u, v in _edges_of(inst):
            assert 0 <= u < inst.n and 0 <= v < inst.n, ctx
            assert u != v, f"self-loop in {ctx}"
            key = (min(u, v), max(u, v))
            assert key not in seen, f"multi-edge in {ctx}"
            seen.add(key)
        for x, y in inst.positions:
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, ctx
        assert inst.adjacency.get("source") in {"reconciled", "geometry_only"}, ctx
        assert inst.adjacency.get("land_clipped") is True, ctx


def test_gate3_no_junk_pseudo_countries_remain():
    # The shipped `iso-1` instance (Akrotiri, Baykonur, Kashmir, Spratly Islands)
    # must be gone, and every country code must be a real two-letter alpha-2.
    from maps_geo.artifact import load
    _, instances = load("data/maps")
    for inst in instances:
        if not inst.params.get("iso"):
            continue
        iso = inst.params["iso"]
        assert len(iso) == 2 and iso.isalpha() and iso.isupper(), inst.id
        for code in inst.codes:
            if code in _NE_DE_FACTO.get(iso, ()):
                continue
            assert code.startswith(iso + "-"), f"{inst.id}: stray code {code}"


# Natural Earth files Crimea and Sevastopol under iso_a2 = RU while ISO 3166-2
# codes them under UA. The map follows NE (unchanged from earlier artifacts);
# pinned here so any other cross-country unit fails loudly.
_NE_DE_FACTO = {"RU": {"UA-40", "UA-43"}}
