"""ISO 3166-2 roster, land mask, curated snapshot and arbitration (2026-09-18)."""
import pytest

pytest.importorskip("pycountry")


def test_country_roster_returns_every_iso_entry_code_sorted():
    from maps_geo.roster import country_roster
    us = country_roster("US")
    codes = [u.code for u in us]
    assert codes == sorted(codes)
    assert "US-CA" in codes and "US-DC" in codes and "US-PR" in codes
    assert len(us) == 57


def test_dominant_type_is_modal_and_deterministic():
    from maps_geo.roster import RosterUnit, dominant_type
    units = [RosterUnit("X-1", "a", "State"), RosterUnit("X-2", "b", "State"),
             RosterUnit("X-3", "c", "Territory")]
    assert dominant_type(units) == "State"
    # A tie breaks by type name ascending, so the answer is stable across runs.
    tied = [RosterUnit("X-1", "a", "Region"), RosterUnit("X-2", "b", "Province")]
    assert dominant_type(tied) == "Province"
    assert dominant_type([]) is None


def _sq(x0, y0, x1, y1):
    from shapely.geometry import Polygon
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_clip_units_removes_the_water_portion():
    # Two units meeting along x=1. Their shared boundary is water above y=0.5,
    # land below. Clipping the lake away must shorten the shared boundary.
    pytest.importorskip("geopandas")
    from maps_geo.landmask import clip_units
    lake = _sq(0.5, 0.5, 1.5, 1.0)
    geoms = {"A": _sq(0, 0, 1, 1), "B": _sq(1, 0, 2, 1)}
    out = clip_units(geoms, lake)
    assert out["A"].intersection(lake).area == pytest.approx(0.0, abs=1e-12)
    assert out["B"].intersection(lake).area == pytest.approx(0.0, abs=1e-12)


def test_clip_units_severs_a_purely_lacustrine_border():
    # The Michigan-Illinois case in miniature: the ONLY contact is across water.
    pytest.importorskip("geopandas")
    from maps_geo.adjacency import geo_adjacency
    from maps_geo.landmask import clip_units
    lake = _sq(0.9, 0.0, 1.1, 1.0)
    geoms = {0: _sq(0, 0, 1, 1), 1: _sq(1, 0, 2, 1)}
    assert geo_adjacency(geoms, eps=100.0) == [(0, 1)]        # before: an edge
    assert geo_adjacency(clip_units(geoms, lake), eps=100.0) == []   # after: none


def test_clip_units_never_deletes_a_unit_entirely():
    # A unit swallowed by the mask keeps its original geometry rather than
    # vanishing from the roster.
    pytest.importorskip("geopandas")
    from maps_geo.landmask import clip_units
    out = clip_units({"A": _sq(0, 0, 1, 1)}, _sq(-1, -1, 2, 2))
    assert not out["A"].is_empty


def test_clip_units_with_no_mask_is_identity():
    pytest.importorskip("geopandas")
    from maps_geo.landmask import clip_units
    geoms = {"A": _sq(0, 0, 1, 1)}
    assert clip_units(geoms, None)["A"].equals(geoms["A"])


def test_canonical_pairs_sorts_dedups_and_drops_self_pairs():
    # P47 is symmetric in intent but not in the data: both directions appear,
    # inconsistently. Canonicalise so the arbiter sees one pair per border.
    from maps_geo.curated import canonical_pairs
    rows = [("US-NY", "US-PA"), ("US-PA", "US-NY"), ("US-NY", "US-NY")]
    assert canonical_pairs(rows) == {("US-NY", "US-PA")}


def test_load_snapshot_round_trips(tmp_path):
    import json
    from maps_geo.curated import load_snapshot
    p = tmp_path / "curated.json"
    p.write_text(json.dumps({
        "fetched": "2026-09-18T00:00:00Z", "query": "SELECT ...",
        "sha256": "unused-on-load",
        "pairs": [["US-NY", "US-PA"], ["AU-NSW", "AU-VIC"]]}))
    snap = load_snapshot(str(p))
    assert ("US-NY", "US-PA") in snap.pairs
    assert snap.pairs_for({"US-NY", "US-PA"}) == {("US-NY", "US-PA")}
    # Pairs with an endpoint outside the roster are filtered out, which is how
    # Michigan-Ontario is kept from leaking into the US map.
    assert snap.pairs_for({"US-NY"}) == set()


def test_covers_reports_whether_the_country_has_any_curated_data():
    from maps_geo.curated import CuratedAdjacency
    snap = CuratedAdjacency(pairs={("US-NY", "US-PA")})
    assert snap.covers({"US-NY", "US-PA"})
    assert not snap.covers({"ZZ-1", "ZZ-2"})


def test_reconcile_geometry_is_necessary_curated_never_adds():
    # The resolved arbitration rule: geometry decides the edge set; curated
    # classifies it. A curated-only pair (Lake Michigan) is dropped and recorded.
    from maps_geo.reconcile import reconcile
    geo = [("US-IN", "US-MI"), ("US-MI", "US-OH")]
    cur = [("US-IN", "US-MI"), ("US-MI", "US-OH"), ("US-IL", "US-MI")]
    r = reconcile(geo, cur, curated_available=True)
    assert r.edges == [("US-IN", "US-MI"), ("US-MI", "US-OH")]
    assert r.curated_only_dropped == [("US-IL", "US-MI")]
    assert r.counts == {"both": 2, "geometry_only": 0, "curated_only": 1}
    assert r.source == "reconciled"


def test_reconcile_keeps_and_flags_uncorroborated_geometry_edges():
    # Absent curated data is not counter-evidence: geometry saw land contact.
    from maps_geo.reconcile import reconcile
    r = reconcile([("A", "B"), ("B", "C")], [("A", "B")], curated_available=True)
    assert r.edges == [("A", "B"), ("B", "C")]
    assert r.geometry_only_kept == [("B", "C")]
    assert r.geometry_only_rate == pytest.approx(0.5)


def test_reconcile_without_curated_data_is_geometry_only():
    from maps_geo.reconcile import reconcile
    r = reconcile([("A", "B")], [], curated_available=False)
    assert r.edges == [("A", "B")]
    assert r.source == "geometry_only"
    assert r.geometry_only_rate == pytest.approx(1.0)


def test_reconcile_normalises_pair_order_on_both_sides():
    from maps_geo.reconcile import reconcile
    r = reconcile([("B", "A")], [("A", "B")], curated_available=True)
    assert r.edges == [("A", "B")]
    assert r.counts["both"] == 1


def test_reconcile_empty_geometry_has_zero_rate_not_division_error():
    from maps_geo.reconcile import reconcile
    r = reconcile([], [("A", "B")], curated_available=True)
    assert r.edges == [] and r.geometry_only_rate == 0.0


class _Inst:
    def __init__(self, iid, n, edges, labels):
        self.id, self.n, self.edges, self.labels = iid, n, edges, labels
        self.family, self.params = "map_country", {"iso": iid[-2:]}


def test_audit_reports_vertex_and_edge_deltas_per_country():
    from maps_geo.audit import audit_maps
    from maps_geo import GeoGraph
    proposed = {"US": GeoGraph(n=51, edges=[(0, 1)], positions=[], labels=[],
                               codes=["US-AL", "US-FL"],
                               adjacency={"source": "reconciled",
                                          "counts": {"both": 1, "geometry_only": 0,
                                                     "curated_only": 2},
                                          "geometry_only_rate": 0.0,
                                          "roster": {"units": 57, "matched": 51,
                                                     "not_in_current_iso": ["US-XX"],
                                                     "unmatched_roster": [],
                                                     "unmatched_geometry": []}})}
    committed = [_Inst("map_country-n51-isoUS", 51, [[0, 1], [0, 2]], ["a", "b"])]
    rep = audit_maps(proposed, committed)
    row = rep["countries"]["US"]
    assert row["n_before"] == 51 and row["n_after"] == 51
    assert row["edges_before"] == 2 and row["edges_after"] == 1
    assert row["curated_only_dropped"] == 2
    assert row["join_rate"] == pytest.approx(51 / 57)


def test_audit_flags_countries_above_the_geometry_only_review_rate():
    from maps_geo.audit import audit_maps
    from maps_geo import GeoGraph

    def mk(rate):
        return GeoGraph(n=2, edges=[(0, 1)], positions=[], labels=[],
                        codes=["A", "B"],
                        adjacency={"source": "reconciled",
                                   "counts": {"both": 0, "geometry_only": 1,
                                              "curated_only": 0},
                                   "geometry_only_rate": rate,
                                   "roster": {"units": 2, "matched": 2,
                                              "not_in_current_iso": [],
                                              "unmatched_roster": [],
                                              "unmatched_geometry": []}})

    rep = audit_maps({"AA": mk(0.9), "BB": mk(0.0)}, [], review_rate=0.5)
    assert rep["needs_review"] == ["AA"]


def test_render_report_is_plain_text_and_names_every_country():
    from maps_geo.audit import render_report
    text = render_report({"countries": {
        "US": {"n_before": 51, "n_after": 51, "edges_before": 108,
               "edges_after": 106, "curated_only_dropped": 5,
               "geometry_only": 0, "geometry_only_rate": 0.0,
               "join_rate": 0.89, "not_in_current_iso": 0}},
        "needs_review": [], "totals": {"countries": 1}})
    assert "US" in text and "106" in text
