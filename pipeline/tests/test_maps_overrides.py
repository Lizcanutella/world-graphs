"""Pinned NE corrections (`maps_geo.overrides`): relabels, edge additions and removals."""
import json

import pytest

pd = pytest.importorskip("pandas")

from maps_geo.build import _record_overrides
from maps_geo.overrides import (
    Overrides, apply_edge_overrides, apply_relabels, load_overrides)

SWAP = [
    {"ne_id": "1", "set": {"iso_3166_2": "EC-T", "name": "Tungurahua"},
     "was": {"iso_3166_2": "EC-N", "name": "Napo"}, "reason": "swap"},
    {"ne_id": "2", "set": {"iso_3166_2": "EC-N", "name": "Napo"},
     "was": {"iso_3166_2": "EC-T", "name": "Tungurahua"}, "reason": "swap"},
]


def _frame():
    return pd.DataFrame({"ne_id": ["1", "2", "3"], "iso_3166_2": ["EC-N", "EC-T", "EC-G"],
                         "name": ["Napo", "Tungurahua", "Guayas"]})


def test_relabel_swaps_two_rows_without_touching_others():
    out = apply_relabels(_frame(), Overrides(relabel=SWAP))
    assert out["iso_3166_2"].tolist() == ["EC-T", "EC-N", "EC-G"]
    assert out["name"].tolist() == ["Tungurahua", "Napo", "Guayas"]
    assert _frame()["name"].tolist()[0] == "Napo"          # input not mutated


def test_relabel_fails_when_ne_changed_underneath():
    df = _frame()
    df.loc[0, "name"] = "Napo (fixed upstream)"
    with pytest.raises(ValueError, match="expected"):
        apply_relabels(df, Overrides(relabel=SWAP))


def test_relabel_fails_on_missing_row():
    with pytest.raises(ValueError, match="matches 0 rows"):
        apply_relabels(_frame(), Overrides(relabel=[{"ne_id": "9", "set": {"name": "x"}}]))


def test_no_overrides_is_identity():
    df = _frame()
    assert apply_relabels(df, None) is df
    assert apply_edge_overrides(["a", "b"], [(0, 1)], "XX", None) == ([(0, 1)], [])


CODES = ["EC-A", "EC-G", "EC-H"]
OV = Overrides(add_edges=[{"iso": "EC", "u": "EC-H", "v": "EC-G", "reason": "collapsed_border"}],
               remove_edges=[{"iso": "EC", "u": "EC-A", "v": "EC-G", "reason": "water"}])


def test_edge_overrides_add_and_remove_only_for_their_country():
    edges, applied = apply_edge_overrides(CODES, [(0, 1)], "EC", OV)
    assert edges == [(1, 2)]
    assert {(a["op"], a["u"], a["v"], a["reason"]) for a in applied} == {
        ("add", "EC-G", "EC-H", "collapsed_border"), ("remove", "EC-A", "EC-G", "water")}
    assert apply_edge_overrides(CODES, [(0, 1)], "PE", OV) == ([(0, 1)], [])


@pytest.mark.parametrize("edges,msg", [
    ([(0, 1), (1, 2)], "cannot add"),        # addition already present
    ([], "cannot add|cannot remove"),         # removal absent
])
def test_edge_override_that_no_longer_describes_the_graph_fails(edges, msg):
    with pytest.raises(ValueError, match=msg):
        apply_edge_overrides(CODES, edges, "EC", OV)


def test_edge_override_unknown_vertex_fails():
    bad = Overrides(add_edges=[{"iso": "EC", "u": "EC-Z", "v": "EC-G", "reason": "x"}])
    with pytest.raises(ValueError, match="unknown vertex"):
        apply_edge_overrides(CODES, [], "EC", bad)


def test_record_overrides_keeps_provenance_true_to_published_edges():
    adj = {"counts": {"both": 3, "geometry_only": 2, "curated_only": 2},
           "curated_only_dropped": [["EC-G", "EC-H"], ["EC-B", "EC-T"]],
           "geometry_only_kept": [["EC-A", "EC-G"], ["EC-L", "EC-O"]],
           "geometry_only_rate": 0.4}
    applied = [{"op": "add", "u": "EC-G", "v": "EC-H", "reason": "collapsed_border"},
               {"op": "remove", "u": "EC-A", "v": "EC-G", "reason": "water"}]
    _record_overrides(adj, applied)
    assert adj["curated_only_dropped"] == [["EC-B", "EC-T"]]
    assert adj["geometry_only_kept"] == [["EC-L", "EC-O"]]
    assert adj["counts"] == {"both": 3, "geometry_only": 1, "curated_only": 1, "override": 1}
    assert adj["geometry_only_rate"] == round(1 / 5, 6)
    assert adj["overrides"] == applied


def test_committed_overrides_file_is_well_formed():
    ov = load_overrides()
    assert len(ov.sha256) == 64
    for e in ov.relabel:
        assert {"ne_id", "set", "was", "reason", "evidence"} <= set(e)
    for e in ov.add_edges + ov.remove_edges:
        assert {"iso", "u", "v", "reason", "evidence"} <= set(e)
        assert e["u"].startswith(e["iso"]) and e["v"].startswith(e["iso"])
    # relabels come in swaps: every code set is a code some other entry gives up
    sets = sorted(e["set"]["iso_3166_2"] for e in ov.relabel)
    gives = sorted(e["was"]["iso_3166_2"] for e in ov.relabel)
    assert sets == gives
    json.dumps(ov.add_edges)                  # serialisable as recorded provenance


def _committed(iso):
    from maps_geo.artifact import load
    _, inst = load("data/maps")
    I = next(i for i in inst if i.params.get("iso") == iso)
    return I, {tuple(sorted((I.codes[u], I.codes[v]))) for (u, v) in I.edges}


def test_committed_artifact_carries_every_edge_override():
    ov = load_overrides()
    for e in ov.add_edges + ov.remove_edges:
        I, edges = _committed(e["iso"])
        pair = tuple(sorted((e["u"], e["v"])))
        assert (pair in edges) == (e in ov.add_edges), (e["iso"], pair)
        assert any({o["u"], o["v"]} == set(pair) for o in I.adjacency["overrides"])


def test_committed_ecuador_labels_follow_the_polygons():
    # After the swap, Tungurahua (EC-T) is the Andean province bordering Chimborazo and
    # Bolivar; Napo (EC-N) is the Amazonian one bordering Orellana and Sucumbios.
    I, edges = _committed("EC")
    for pair in [("EC-H", "EC-T"), ("EC-B", "EC-T"), ("EC-D", "EC-N"), ("EC-N", "EC-U")]:
        assert pair in edges
    assert ("EC-D", "EC-T") not in edges and ("EC-B", "EC-N") not in edges
    assert I.labels[I.codes.index("EC-T")] == "Tungurahua"
