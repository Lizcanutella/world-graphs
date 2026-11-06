"""Adjacency ground-truth oracle — Unit 1 of the 2026-07-17 map gallery design.

An INDEPENDENT oracle for border adjacency: known geography, written from
outside the geometry code, so no bug in geo_adjacency can talk it into
agreeing. Mirrors the role the brute-force proper-colouring oracle plays for
the engine (CLAUDE.md: "Keep independent oracles").

The `GROUND_TRUTH` neighbour sets are exact for the **natural_earth** world
(every NE polity is its own vertex, so France's Caribbean dependency St-Martin
stays separate and does not add a Netherlands border). Unit 4b's un195 world
*merges* dependencies, which legitimately changes some neighbour sets — those
policy-dependent consequences are asserted separately below (Serbia gains
Albania via merged Kosovo; Morocco loses Mauritania with Western Sahara dropped;
France gains the Netherlands via merged St-Martin/Sint-Maarten).

Needs the [geo] extra AND the real Natural Earth download, so it is gated on
WG_RUN_GEO_BUILD=1 like test_real_world_geograph_smoke.
"""
import os

import pytest

pytest.importorskip("geopandas")

pytestmark = pytest.mark.skipif(
    "WG_RUN_GEO_BUILD" not in os.environ,
    reason="real Natural Earth build — set WG_RUN_GEO_BUILD=1 to run")

DATA_DIR = os.environ.get("WG_GEO_DATA", "data/naturalearth")
EPS = 100.0        # metres (geodesic) — Unit 3 made geo_adjacency metric

# Ground truth: LAND borders, by Natural Earth ADM0_A3 code. Hand-checked.
# France includes French Guiana (a real 730km border with Brazil) — the
# 2026-07-17 design keeps full sovereign geometry, so BRA and SUR are correct
# and their absence is a bug, not a quirk.
GROUND_TRUTH = {
    "PRT": {"ESP"},                                        # simplest true case
    "CHE": {"FRA", "DEU", "ITA", "AUT", "LIE"},            # LIE present at 10m; border < eps in degrees
    "POL": {"DEU", "CZE", "SVK", "UKR", "BLR", "LTU", "RUS"},   # RUS via Kaliningrad
    "FRA": {"BEL", "LUX", "DEU", "CHE", "ITA", "ESP", "AND", "MCO", "BRA", "SUR"},
    "BRA": {"URY", "ARG", "PRY", "BOL", "PER", "COL", "VEN", "GUY", "SUR", "FRA"},
    "LSO": {"ZAF"},                                        # enclave
    "SMR": {"ITA"},                                        # microstate — 10m only
    "VAT": {"ITA"},                                        # microstate — 10m only
    "SGP": set(),                                          # island — isolated vertex
    "ISL": set(),                                          # island — isolated vertex
    "CHL": {"PER", "BOL", "ARG"},
    "NPL": {"CHN", "IND"},
    "MNG": {"CHN", "RUS"},
    "GMB": {"SEN"},
}


def neighbours_by_code(g, policy):
    """{ADM0_A3: {ADM0_A3, ...}} from a world GeoGraph built under `policy`.

    Vertex order is by sorted key (ordered_geoms); the same policy assignment
    that built the graph re-derives that key order here, so the oracle is checked
    against the exact keyset the pipeline shipped rather than a re-guess.
    """
    import geopandas as gpd
    from maps_geo.naturalearth import fetch_natural_earth
    from maps_geo.policy import assign_world_vertices

    paths = fetch_natural_earth(DATA_DIR)
    gdf = gpd.read_file(paths["admin0"])
    keys = sorted(set(assign_world_vertices(gdf, policy)["_key"].astype(str)))
    assert len(keys) == g.n, f"key/vertex count mismatch: {len(keys)} vs {g.n}"
    out = {k: set() for k in keys}
    for u, v in g.edges:
        out[keys[u]].add(keys[v])
        out[keys[v]].add(keys[u])
    return out


@pytest.fixture(scope="module")
def world_neighbours():
    # GROUND_TRUTH is exact for the natural_earth world (dependencies separate).
    from maps_geo.naturalearth import world_geograph
    return neighbours_by_code(
        world_geograph(DATA_DIR, eps=EPS, policy="natural_earth"), "natural_earth")


@pytest.fixture(scope="module")
def un195_neighbours():
    from maps_geo.naturalearth import world_geograph
    return neighbours_by_code(
        world_geograph(DATA_DIR, eps=EPS, policy="un195"), "un195")


@pytest.mark.parametrize("code", sorted(GROUND_TRUTH))
def test_no_expected_neighbour_missing(world_neighbours, code):
    # Unit 3's core property: every real border is present. A regression that
    # DROPS a real border fails loudly here.
    expected = GROUND_TRUTH[code]
    assert code in world_neighbours, f"{code} absent from the world map entirely"
    missing = expected - world_neighbours[code]
    assert not missing, f"{code}: missing real borders {sorted(missing)}"


@pytest.mark.parametrize("code", sorted(GROUND_TRUTH))
def test_country_has_exactly_its_real_neighbours(world_neighbours, code):
    # Exact match, natural_earth world. BRA/CHL now pass: Unit 4b drops the
    # non-polity junk vertices (Brazilian Island / Patagonian Ice Field) that
    # previously injected a spurious border, so no xfail is needed.
    expected = GROUND_TRUTH[code]
    assert code in world_neighbours, f"{code} absent from the world map entirely"
    got = world_neighbours[code]
    assert got == expected, (
        f"{code}: missing={sorted(expected - got)} spurious={sorted(got - expected)}")


def test_island_states_are_isolated_vertices(world_neighbours):
    # Isolated vertices must survive the pipeline: the engine's disconnected
    # -> product reduction handles them for free (each contributes a factor k).
    for code in ("SGP", "ISL"):
        assert world_neighbours.get(code) == set(), (
            f"{code} should have no land border, got {sorted(world_neighbours.get(code, []))}")


# --- un195 policy consequences (Unit 4b, design lines 231-241) ---------------
# The un195 unit-mapping rule changes some neighbour sets vs natural_earth, and
# the design requires those consequences be asserted, not hidden.

def test_un195_serbia_borders_albania_via_merged_kosovo(un195_neighbours):
    # Serbia touches Albania only through Kosovo; merging Kosovo into Serbia
    # (UNSC 1244) must PRESERVE that border rather than delete it.
    assert "ALB" in un195_neighbours["SRB"], sorted(un195_neighbours["SRB"])


def test_un195_morocco_not_adjacent_to_mauritania(un195_neighbours):
    # Morocco touches Mauritania only via Western Sahara; dropping Western Sahara
    # (no UN-recognised sovereign) removes that contact — disclosed, not hidden.
    assert "MRT" not in un195_neighbours["MAR"], sorted(un195_neighbours["MAR"])
    assert "DZA" in un195_neighbours["MAR"]      # a real Morocco border still present


def test_un195_merging_dependencies_adds_a_neighbour(un195_neighbours):
    # St-Martin (France) borders Sint-Maarten (Netherlands); merging each into its
    # sovereign creates a France-Netherlands edge absent from natural_earth. This
    # is why France's neighbour set is policy-dependent and not in GROUND_TRUTH.
    assert "NLD" in un195_neighbours["FRA"], sorted(un195_neighbours["FRA"])


def test_un195_contested_units_absent_as_vertices(un195_neighbours):
    # Taiwan/Kosovo/N.Cyprus/Somaliland and dropped Western Sahara/Antarctica are
    # not their own vertices in un195 (they are merged or dropped).
    for code in ("TWN", "KOS", "CYN", "SOL", "SAH", "ATA"):
        assert code not in un195_neighbours, f"{code} should not be a un195 vertex"
