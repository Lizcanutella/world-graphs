"""Maintainer-verified graphs (`maps_geo.verified`): the tag is pinned to the graph it was given."""
import pytest

from maps_geo.verified import graph_sha256, load_verified, verification

CODES = ["CO-BOY", "CO-CAS", "CO-MET"]
EDGES = [("CO-BOY", "CO-CAS"), ("CO-CAS", "CO-MET")]


def test_graph_hash_ignores_order_and_edge_direction():
    assert graph_sha256(CODES, EDGES) == graph_sha256(CODES[::-1], [(v, u) for u, v in EDGES[::-1]])
    assert graph_sha256(CODES, EDGES) != graph_sha256(CODES, EDGES + [("CO-BOY", "CO-MET")])


def test_verification_is_published_only_for_the_pinned_graph():
    v = {"CO": {"id": "CO", "date": "2026-10-02", "note": "checked", "graph_sha256": graph_sha256(CODES, EDGES)}}
    assert verification(v, "CO", CODES, EDGES) == {"date": "2026-10-02", "note": "checked"}
    assert verification(v, "EC", CODES, EDGES) is None
    with pytest.raises(ValueError, match="changed since it was verified"):
        verification(v, "CO", CODES, EDGES + [("CO-BOY", "CO-MET")])


def test_committed_verified_graphs_match_the_decided_graphs():
    """Every verified entry pins the graph wg.decide builds now (data/build/graphs)."""
    import json
    import os
    verified = load_verified()
    for gid, e in verified.items():
        assert {"id", "date", "note", "graph_sha256"} <= set(e)
        path = f"data/build/graphs/{gid}.json"
        if not os.path.exists(path):
            pytest.skip("no decided graphs (run wg.pairs and wg.decide)")
        g = json.load(open(path, encoding="utf-8"))
        codes = [n["code"] for n in g["nodes"]]
        assert verification(verified, gid, codes, [(x["u"], x["v"]) for x in g["edges"]]) is not None
