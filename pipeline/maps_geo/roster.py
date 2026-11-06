"""Official ISO 3166-2 vertex rosters.

Pure: no geometry, no network. This module reports what the standard says.
Which roster entries actually become vertices is decided in `build.py`, the only
place that knows the geometry — see the spec's "Roster scope, restated".
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


class RosterUnavailable(RuntimeError):
    """Raised when pycountry (part of the [geo] extra) is not installed."""


@dataclass(frozen=True)
class RosterUnit:
    code: str      # ISO 3166-2, e.g. "US-CA"
    name: str      # official English name
    type: str      # ISO's own level, e.g. "State" / "Province" / "Outlying area"


def country_roster(alpha2: str) -> list[RosterUnit]:
    """Every ISO 3166-2 entry for `alpha2`, sorted by code."""
    try:
        import pycountry
    except Exception as e:  # noqa: BLE001 — absent extra, not a bug
        raise RosterUnavailable(
            "pycountry is required for the ISO 3166-2 roster — "
            "install it with:  uv pip install pycountry") from e
    subs = pycountry.subdivisions.get(country_code=alpha2) or []
    units = [RosterUnit(code=str(s.code), name=str(s.name), type=str(s.type))
             for s in subs]
    return sorted(units, key=lambda u: u.code)


def dominant_type(units: list[RosterUnit]) -> str | None:
    """The modal subdivision type, or None when nothing is populated.

    A reported signal, not a hard filter: filtering on it alone deletes real
    mainland units (the Northern Territory, DC, Distrito Federal). Ties break by
    count descending then type name ascending, so the result never depends on
    dict ordering.
    """
    vals = [u.type for u in units if u.type and u.type.strip()]
    if not vals:
        return None
    counts = Counter(vals)
    return min(counts, key=lambda t: (-counts[t], t))


# Natural Earth admin-1 `type_en` singular -> the plural label shown on the
# Gallery card. Unknown types are reported as-is (lowercased) rather than
# guessed — Unit 7 must never invent an administrative level.
_GRANULARITY_PLURALS = {
    "state": "states", "province": "provinces", "municipality": "municipalities",
    "district": "districts", "region": "regions", "county": "counties",
    "department": "departments", "territory": "territories", "canton": "cantons",
    "prefecture": "prefectures", "governorate": "governorates", "parish": "parishes",
    "oblast": "oblasts", "republic": "republics", "voivodeship": "voivodeships",
}


def admin1_granularity_label(type_values) -> str | None:
    """A single administrative-granularity label from a country's `type_en` values.

    Uses the most common non-empty `type_en` (Natural Earth's admin level, e.g.
    "State"/"Province"/"Municipality"). Returns a clean plural for known levels,
    the lowercased raw value for unknown ones, and None when nothing is populated
    — so an absent field omits the label rather than fabricating one.
    """
    # pandas represents a missing type_en cell as float NaN, whose str() is the
    # truthy string "nan" — treat that (and "none") as missing, never as a level.
    _MISSING = {"", "nan", "none"}
    vals = [str(v).strip() for v in type_values
            if v is not None and str(v).strip().lower() not in _MISSING]
    if not vals:
        return None
    dominant = Counter(vals).most_common(1)[0][0]
    key = dominant.lower()
    return _GRANULARITY_PLURALS.get(key, key)
