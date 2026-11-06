"""wg.decide.rule / votes: an edge follows the majority of NE, geoBoundaries and Wikidata P47."""
import pytest

from wg.decide import decide_country, rule, votes


def v(ne, gb, p47):
    return {"ne": ne, "gb": gb, "p47": p47}


@pytest.mark.parametrize("votes_,expected", [
    (v("yes", "yes", False), (True, "ne_and_gb")),
    (v("yes", None, False), (True, "ne_uncheckable")),
    (v("point", "no", True), (False, "ne_and_gb_none")),       # Four Corners diagonal
    (v("point", "yes", True), (True, "gb_and_p47")),           # NE collapsed a real border
    (v("no", "yes", True), (True, "gb_and_p47")),              # NE lost a border
    (v("yes", "apart", False), (False, "gb_and_p47_apart")),   # NE draws a border others lack
    (v("yes", "no", True), (True, "ne_and_p47")),
    (v("yes", "short", False), (True, "ne_short")),
    (v("point", "yes", False), (False, "review")),             # gB alone against NE and P47
    (v("yes", "no", False), (True, "review")),                 # gB point contact, NE border
])
def test_rules(votes_, expected):
    assert rule(votes_) == expected


def pair(**kw):
    p = {"u": "X-A", "v": "X-B", "ne_contact": "line", "ne_len_m": 5000.0, "ne_gap_m": 0.0,
         "release": None, "p47": False, "gb_len_m": 5100.0, "gb_gap_m": 0.0, "q": [1.0, 1.0]}
    p.update(kw)
    return p


def test_gb_vote_bands_subtract_point_noise():
    assert votes(pair(gb_len_m=100.0), 50.0, set())["gb"] == "no"          # a point contact
    assert votes(pair(gb_len_m=100.0, gb_gap_m=2000.0), 50.0, set())["gb"] == "apart"
    assert votes(pair(gb_len_m=400.0), 50.0, set())["gb"] == "short"
    assert votes(pair(gb_len_m=600.0), 50.0, set())["gb"] == "yes"


def test_gb_abstains_for_unidentified_or_other_vintage_units():
    assert votes(pair(q=[1.0, 0.5]), 50.0, set())["gb"] is None
    assert votes(pair(), 50.0, {"X-B"})["gb"] is None


def test_hand_decision_wins_and_stale_ones_fail():
    d = {"iso": "X", "n": 2, "gb_tol_m": 50.0, "vertices": {"X-A": "A", "X-B": "B"},
         "pairs": [pair(gb_len_m=0.0, gb_gap_m=5000.0)]}
    g, _ = decide_country(d, {})
    assert g["edges"] == []
    g, _ = decide_country(d, {("X-A", "X-B"): {"edge": True, "reason": "test"}})
    assert [e["rule"] for e in g["edges"]] == ["hand"]
    with pytest.raises(ValueError):
        decide_country(d, {("X-A", "X-C"): {"edge": True, "reason": "test"}})


def test_gb_border_over_sea_does_not_count():
    # Clare-Kerry: gB runs the county boundary down the Shannon estuary, all of it over NE's sea.
    assert votes(pair(gb_len_m=25000.0, gb_sea_m=25000.0), 50.0, set())["gb"] == "no"
    # Waterford-Wexford: most of it in the harbour, 1.4 km up the river still counts.
    assert votes(pair(gb_len_m=5800.0, gb_sea_m=4400.0), 50.0, set())["gb"] == "yes"
