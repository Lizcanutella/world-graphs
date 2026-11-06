"""wg.geom on synthetic projected squares (metres): point noise, shared borders, gaps, matching."""
import pytest

shapely = pytest.importorskip("shapely")
from shapely.geometry import box  # noqa: E402

from wg import geom as G  # noqa: E402

T = 50.0


def near(a, b):
    return min(G.border_near(a, b.buffer(T)), G.border_near(b, a.buffer(T)))


def test_point_contact_reads_as_point_noise():
    # Four Corners: diagonal squares touching at one point.
    a, b = box(0, 0, 1000, 1000), box(1000, 1000, 2000, 2000)
    assert near(a, b) == pytest.approx(G.point_noise(T), rel=0.05)


def test_shared_edge_reads_its_length():
    a, b = box(0, 0, 1000, 1000), box(1000, 300, 2000, 1300)   # 700 m shared
    assert near(a, b) == pytest.approx(700 + 2 * T, rel=0.02)


def test_sliver_gap_below_tolerance_still_reads_as_border():
    # Sloppy topology: a 20 m gap between neighbours drawn from different surveys.
    a, b = box(0, 0, 1000, 1000), box(1020, 0, 2000, 1000)
    assert near(a, b) > 900


def test_gap_above_tolerance_reads_zero():
    a, b = box(0, 0, 1000, 1000), box(1200, 0, 2000, 1000)
    assert near(a, b) == 0.0


def test_match_nesting_and_redraw():
    ne = {"A": box(0, 0, 1000, 1000), "B": box(1000, 0, 2000, 1000)}
    # gB splits each NE unit in two; one gB unit straddles slightly (95% in B).
    gb = [box(0, 0, 500, 1000), box(500, 0, 1000, 1000),
          box(1000, 0, 1500, 1000), box(1475, 0, 2000, 1000)]
    m = G.match(ne, gb)
    assert m.owner == ["A", "A", "B", "B"]
    assert m.unit_quality["A"] == pytest.approx(1.0)
    assert m.unit_quality["B"] > 0.95
    assert m.poor == []
    assert near(m.redraw["A"], m.redraw["B"]) == pytest.approx(1000 + 2 * T, rel=0.02)


def test_unmatched_unit_has_zero_quality():
    # NE has a capital district inside a province; gB only has the province.
    ne = {"P": box(0, 0, 1000, 1000).difference(box(400, 400, 600, 600)),
          "C": box(400, 400, 600, 600)}
    m = G.match(ne, [box(0, 0, 1000, 1000)])
    assert m.owner == ["P"]
    assert m.unit_quality["C"] == 0.0 and m.poor == ["C"]
    assert m.redraw["C"].is_empty


def test_code_match_survives_generalisation():
    # NE draws a small unit far off its real outline: most of gB's X-2 falls inside NE's X-1,
    # so area matching gives it away; the code keeps it (it still covers 75% of NE's X-2),
    # and the shape difference is reported as IoU.
    ne = {"X-1": box(0, 0, 1000, 1000), "X-2": box(1000, 0, 1200, 1000)}
    gb = [box(0, 0, 600, 1000), box(600, 0, 1150, 1000)]
    by_area = G.match(ne, gb)
    assert by_area.redraw["X-2"].is_empty
    m = G.match(ne, gb, {k: k for k in ne}, ["X-1", "X-2"])
    assert m.matched_by == {"X-1": "code", "X-2": "code"}
    assert m.unit_quality["X-2"] == 1.0 and m.iou["X-2"] == pytest.approx(150 / 600)


def test_stale_code_reused_elsewhere_is_rejected():
    # gB reuses code X-2 for a unit on the other side of the country (a renumbering).
    ne = {"X-1": box(0, 0, 1000, 1000), "X-2": box(1000, 0, 2000, 1000)}
    gb = [box(0, 0, 1000, 1000), box(1000, 0, 2000, 1000)]
    m = G.match(ne, gb, {k: k for k in ne}, ["X-2", "X-1"])
    assert set(m.matched_by.values()) == {"area"}
    assert m.owner == ["X-1", "X-2"]
