"""wg.units.propose: NE rows are relabelled only when gB and Wikidata agree against NE."""
import pytest

pytest.importorskip("shapely")
from wg.units import propose  # noqa: E402

PT = (0.0, 0.0)


def row(nid, code, name, gb_code, gb_name, share=0.95):
    return {"ne_id": nid, "code": code, "name": name, "gb_code": gb_code, "gb_name": gb_name,
            "share": share}


def pts(*codes):
    return {c: [("Q" + c, PT, c + " label", "normal")] for c in codes}


def moves(out):
    return {e["ne_id"]: (e["set"]["iso_3166_2"], e["set"]["name"], e["rule"]) for e in out}


def test_swap_moves_names_with_codes():
    rows = [row("1", "X-A", "Alpha", "X-B", "Beta"), row("2", "X-B", "Beta", "X-A", "Alpha")]
    out = propose(rows, {"1": {"X-B"}, "2": {"X-A"}}, pts("X-A", "X-B"), set())
    assert moves(out) == {"1": ("X-B", "Beta", "gb_and_wikidata_against_ne"),
                          "2": ("X-A", "Alpha", "gb_and_wikidata_against_ne")}


def test_code_only_error_keeps_ne_name():
    rows = [row("1", "X-A", "Paktika", "X-B", "Paktika"), row("2", "X-B", "Paktya", "X-A", "Paktya")]
    out = propose(rows, {"1": {"X-B"}, "2": {"X-A"}}, pts("X-A", "X-B"), set())
    assert moves(out)["1"][:2] == ("X-B", "Paktika")


def test_wikidata_siding_with_ne_blocks():
    rows = [row("1", "X-A", "Alpha", "X-B", "Beta")]
    assert propose(rows, {"1": {"X-A", "X-B"}}, pts("X-A", "X-B"), set()) == []


def test_ne_code_without_any_point_blocks():
    # A capital city NE draws as its own vertex: gB folds it into the province whose point
    # (the capital) lies in it. With no point for the city's own code, nothing moves.
    rows = [row("1", "X-C", "City", "X-P", "Province")]
    assert propose(rows, {"1": {"X-P"}}, pts("X-P"), set()) == []


def test_permutation_completed_without_point():
    rows = [row("1", "X-A", "Alpha", "X-B", "Beta"), row("2", "X-B", "Beta", "X-C", "Gamma"),
            row("3", "X-C", "Gamma", "X-A", "Alpha")]
    out = propose(rows, {"1": {"X-B"}, "3": {"X-A"}}, pts("X-A", "X-B", "X-C"), set())
    assert moves(out) == {"1": ("X-B", "Beta", "gb_and_wikidata_against_ne"),
                          "2": ("X-C", "Gamma", "completes_permutation"),
                          "3": ("X-A", "Alpha", "gb_and_wikidata_against_ne")}


def test_never_merges_into_a_unit_gb_places_elsewhere():
    rows = [row("1", "X-A", "Alpha", "X-B", "Beta"), row("2", "X-B", "Beta", "X-Z", "Zeta")]
    assert propose(rows, {"1": {"X-B"}}, pts("X-A", "X-B"), set()) == []


def test_hidden_unit_gets_wikidata_or_gb_name():
    rows = [row("1", "X-A", "Brod", "X-A", "Brod"), row("2", "X-A", "Brod", "X-H", "Pozega-Slavonia")]
    p = pts("X-A") | {"X-H": [("Q1", PT, "Požega-Slavonia County", "normal")]}
    out = propose(rows, {"1": {"X-A"}, "2": {"X-H"}}, p, set())
    assert moves(out) == {"2": ("X-H", "Pozega-Slavonia", "gb_and_wikidata_against_ne")}


def test_hand_decision_rows_are_left_alone():
    rows = [row("1", "X-A", "Alpha", "X-B", "Beta")]
    assert propose(rows, {"1": {"X-B"}}, pts("X-A", "X-B"), {"1"}) == []
