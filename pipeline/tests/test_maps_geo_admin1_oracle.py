"""Admin-1 (country subdivision) adjacency ground-truth oracle.

The companion to `test_maps_geo_oracle.py` (which covers admin-0, the world map).
The user's border complaint spanned *country* subdivision maps too, and until now
those had no independent oracle — the 2026-07-17 admin-0 diagnostic explicitly
flagged admin-1 as an unmeasured blind spot. This file closes it.

US states are the gold-standard ground truth: their mutual land borders are
unambiguous and public. LAND borders only — states that meet at a single point
are NOT adjacent (a zero-length shared boundary), so the two Four Corners point
contacts (Colorado–Arizona and Utah–New Mexico) are deliberately absent below.
That is exactly what a correct `geo_adjacency` must also exclude, which makes
this a real independent cross-check rather than a restatement of the geometry.

Like the admin-0 oracle, this needs the [geo] extra AND the real Natural Earth
download, so it is gated on WG_RUN_GEO_BUILD=1.
"""
import os

import pytest

pytest.importorskip("geopandas")

pytestmark = pytest.mark.skipif(
    "WG_RUN_GEO_BUILD" not in os.environ,
    reason="real Natural Earth build — set WG_RUN_GEO_BUILD=1 to run")

DATA_DIR = os.environ.get("WG_GEO_DATA", "data/naturalearth")

# LAND-border neighbour sets, hand-checked, by US state display name. Point
# contacts excluded: Colorado does NOT list Arizona, Utah does NOT list New
# Mexico (Four Corners is a single point). Hawaii and Alaska are isolated.
US_TRUTH = {
    "Maine": {"New Hampshire"},
    "New Hampshire": {"Maine", "Massachusetts", "Vermont"},
    "Florida": {"Georgia", "Alabama"},
    "California": {"Oregon", "Nevada", "Arizona"},
    "Colorado": {"Wyoming", "Nebraska", "Kansas", "Oklahoma", "New Mexico", "Utah"},
    "Wyoming": {"Montana", "South Dakota", "Nebraska", "Colorado", "Utah", "Idaho"},
    "Utah": {"Idaho", "Wyoming", "Colorado", "Arizona", "Nevada"},
    "Tennessee": {"Kentucky", "Virginia", "North Carolina", "Georgia", "Alabama",
                  "Mississippi", "Arkansas", "Missouri"},
    "Missouri": {"Iowa", "Illinois", "Kentucky", "Tennessee", "Arkansas",
                 "Oklahoma", "Kansas", "Nebraska"},
    "Kentucky": {"Illinois", "Indiana", "Ohio", "West Virginia", "Virginia",
                 "Tennessee", "Missouri"},
    "Hawaii": set(),
    "Alaska": set(),
}


def neighbours_by_label(g):
    """{state name: {state name, ...}} from a country GeoGraph. US state names
    are unique, so labels are a safe key here (the same-name-merge bug this
    pipeline had is exactly why the world oracle re-derives keys instead)."""
    lab = g.labels
    out = {name: set() for name in lab}
    for u, v in g.edges:
        out[lab[u]].add(lab[v])
        out[lab[v]].add(lab[u])
    return out


@pytest.fixture(scope="module")
def us_neighbours():
    from maps_geo.naturalearth import country_geographs
    cg = country_geographs(DATA_DIR)          # default metric eps
    assert "US" in cg, "US country graph missing from admin-1"
    return neighbours_by_label(cg["US"])


@pytest.mark.parametrize("state", sorted(US_TRUTH))
def test_us_state_has_exactly_its_real_neighbours(us_neighbours, state):
    assert state in us_neighbours, f"{state} absent from the US map entirely"
    got = us_neighbours[state]
    expected = US_TRUTH[state]
    assert got == expected, (
        f"{state}: missing={sorted(expected - got)} spurious={sorted(got - expected)}")


def test_noncontiguous_states_are_isolated(us_neighbours):
    # Hawaii (islands) and Alaska (separated by Canada) have no US land border;
    # the engine's disconnected -> product reduction handles them for free.
    for state in ("Hawaii", "Alaska"):
        assert us_neighbours.get(state) == set(), (
            f"{state} should have no US land border, got {sorted(us_neighbours.get(state, []))}")
