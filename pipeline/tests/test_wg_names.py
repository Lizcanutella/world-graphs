"""wg.pairs.same_name: decides whether a code disagreement is a code error or a label error."""
import pytest

pytest.importorskip("shapely")
from wg.pairs import name_key, same_name  # noqa: E402


@pytest.mark.parametrize("a,b", [
    ("Paktika", "Paktika"),
    ("River Cess", "Rivercess"),
    ("Lékoumou", "Lekoumou Department"),
    ("Zadarska", "Zadar County"),              # Croatian adjective vs English county name
    ("Bogota", "Bogota Capital District"),
    ("Tungurahua", "Provincia de Tungurahua"),
])
def test_same_unit_different_spelling(a, b):
    assert same_name(a, b)


@pytest.mark.parametrize("a,b", [
    ("Cuyuni-Mazaruni", "Pomeroon-Supenaam"),
    ("Brodsko-Posavska", "Požega-Slavonia"),
    ("Qina", "Luxor Governate"),
])
def test_different_units(a, b):
    assert not same_name(a, b)


@pytest.mark.xfail(strict=True, reason="known limit: Paktika and Paktia are different provinces "
                   "one letter apart, while Paktia/Paktya is one province spelt two ways. No string "
                   "rule separates them, so code-vs-label is a hint; wg.labels (Wikidata points) "
                   "decides.")
def test_near_identical_names_of_different_units():
    assert not same_name("Paktika", "Paktia")


def test_generic_words_and_accents_are_ignored():
    assert name_key("Región de Ñuble") == name_key("nuble")
    assert name_key(None) == "" and not same_name(None, "X")
