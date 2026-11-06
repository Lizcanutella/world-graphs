"""wg.export: edge sources and corroboration, and the diff against the previous release."""
from wg.export import diff_rows, edge_record


def e(rule, ne="yes", gb="yes", p47=True, **kw):
    return {"u": "X-A", "v": "X-B", "rule": rule, "votes": {"ne": ne, "gb": gb, "p47": p47},
            "ne_len_m": 1234.5, **kw}


def test_corroborated_needs_two_sources_or_a_hand_decision():
    r = edge_record(e("ne_and_gb", p47=False))
    assert [s["source"] for s in r["sources"]] == ["natural_earth", "geoboundaries"] and r["corroborated"]
    assert not edge_record(e("ne_uncheckable", gb=None, p47=False))["corroborated"]
    assert edge_record(e("ne_uncheckable", gb=None))["corroborated"]          # NE and P47
    h = edge_record(e("hand", ne="point", gb="short", p47=False, reason="r"))
    assert h["sources"] == [{"source": "hand", "reason": "r"}] and h["corroborated"]


def graph(nodes, edges):
    return {"nodes": [{"code": c, "name": n} for c, n in nodes],
            "edges": [{"u": u, "v": v, "rule": "ne_and_gb", "sources": [{"source": "natural_earth"}]}
                      for u, v in edges]}


def test_swap_reads_as_relabels_not_edge_changes():
    prev = graph([("X-A", "Alpha"), ("X-B", "Beta"), ("X-C", "Gamma")], [("X-A", "X-C")])
    new = graph([("X-A", "Beta"), ("X-B", "Alpha"), ("X-C", "Gamma")], [("X-B", "X-C")])
    rows = diff_rows("X", prev, {"1": "X-A", "2": "X-B", "3": "X-C"}, new,
                     {"1": "X-B", "2": "X-A", "3": "X-C"})
    assert sorted(r[1] for r in rows) == ["node_relabelled", "node_relabelled"]


def test_split_adds_one_vertex_and_only_its_new_border():
    prev = graph([("X-A", "Alpha"), ("X-C", "Gamma")], [("X-A", "X-C")])
    new = graph([("X-A", "Alpha"), ("X-H", "Hidden"), ("X-C", "Gamma")],
                [("X-A", "X-C"), ("X-C", "X-H"), ("X-A", "X-H")])
    rows = diff_rows("X", prev, {"1": "X-A", "2": "X-A", "3": "X-C"}, new,
                     {"1": "X-A", "2": "X-H", "3": "X-C"})
    assert [(r[1], r[2], r[3]) for r in rows] == [("node_relabelled", "X-A", "X-H"),
                                                   ("edge_added", "X-A", "X-H")]
