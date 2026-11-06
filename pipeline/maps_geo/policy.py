"""Inclusion policy for the world (admin-0) graph — Unit 4b of the 2026-07-17
map-gallery design.

Two worlds, one code path:

- ``"un195"`` — the 193 UN member states + 2 UN observers (Vatican, Palestine).
  Every other Natural Earth unit is either **merged** into the UN member the UN
  recognises as sovereign, or **dropped** when no such state exists. The merge is
  mechanical from NE's ``SOV_A3`` for genuine dependencies (Greenland -> Denmark,
  Puerto Rico -> USA, New Caledonia -> France), with a small explicit
  ``CONTESTED_MERGE`` table for units NE marks sovereign but the UN reassigns.
- ``"natural_earth"`` — every NE *polity* as its own vertex (contested units shown
  separately). The honest companion that discloses exactly what un195 merges.

The contested table takes its politics from the UN, not from us, and the
``natural_earth`` world exists so nothing is hidden — but it is a modelling
decision with a political surface, reviewed and approved as such (2026-07-19),
not nodded through as config. It lives in ONE place, cited, on purpose.

Non-polity NE features (glaciers, reefs, no-man's-land) are dropped from **both**
worlds: they are not colourable regions, and admitting them injects spurious
borders (the "Brazilian Island" / "Southern Patagonian Ice Field" vertices that
made BRA/CHL wrong in the Phase-A oracle).
"""
from __future__ import annotations

from . import require_geo

POLICIES = ("un195", "natural_earth")
DEFAULT_POLICY = "un195"

# 193 UN members + 2 observers (Vatican, Palestine). Asserted at world-build time
# (Risk 7): the count depends on NE's 10m inventory matching the UN list after
# merging, so a build that lands on 194/196 must fail loudly rather than ship a
# quietly-wrong headline.
UN195_EXPECTED_COUNT = 195

# Uninhabited non-polity NE features (ADM0_A3). Not countries; dropped from BOTH
# worlds. Comments are the NE ADMIN name.
NON_POLITY_JUNK = frozenset({
    "BRI",  # Brazilian Island
    "SPI",  # Southern Patagonian Ice Field
    "KAS",  # Siachen Glacier
    "BRT",  # Bir Tawil (unclaimed)
    "CNM",  # Cyprus No Mans Area
    "PGA",  # Spratly Islands
    "BJN",  # Bajo Nuevo Bank (Petrel Is.)
    "SER",  # Serranilla Bank
    "SCR",  # Scarborough Reef
})

# un195 only: real polities with no UN-recognised sovereign -> dropped. Merging
# Western Sahara into Morocco would assert a sovereign the UN does not recognise;
# Antarctica has no sovereign (and dropping it also fixes the un195 layout).
UN195_DROP = frozenset({
    "SAH",  # Western Sahara — UN non-self-governing territory
    "ATA",  # Antarctica
})

# un195 only: NE marks these sovereign; the UN assigns each to a member state.
# Cited so the modelling decision is reviewable in one place.
CONTESTED_MERGE = {
    "TWN": "CHN",  # Taiwan          -> China   (UNGA Res 2758, 1971)
    "KOS": "SRB",  # Kosovo          -> Serbia  (UNSC Res 1244)
    "CYN": "CYP",  # Northern Cyprus -> Cyprus
    "SOL": "SOM",  # Somaliland      -> Somalia
}

# un195 only: UN observers/members NE files under a different SOVEREIGNT. NE sets
# Palestine's SOVEREIGNT to 'Israel', so the mechanical merge would fold PSX into
# ISR; this override keeps such units as their own vertex. (VAT is already its own
# sovereign home, listed for explicitness.)
UN195_OBSERVER_SELF = frozenset({"PSX", "VAT"})


def _require_policy(policy: str) -> None:
    if policy not in POLICIES:
        raise ValueError(
            f"unknown inclusion policy {policy!r}; expected one of {POLICIES}")


def _sovereign_home(gdf) -> dict:
    """``SOV_A3 -> member ADM0_A3``: each sovereign group's *home* unit, i.e. the
    row whose ``ADMIN == SOVEREIGNT``. Junk / contested / un195-dropped homes are
    excluded so only genuine dependencies resolve through it."""
    excluded = NON_POLITY_JUNK | UN195_DROP | set(CONTESTED_MERGE)
    home = gdf[gdf["ADMIN"].astype(str) == gdf["SOVEREIGNT"].astype(str)]
    out = {}
    for sov, adm in zip(home["SOV_A3"].astype(str), home["ADM0_A3"].astype(str)):
        if adm in excluded:
            continue
        out[sov] = adm
    return out


def world_vertex_key(adm0_a3: str, sov_a3: str, policy: str, sov_home: dict):
    """The vertex id for one NE unit under ``policy``, or ``None`` if dropped.

    ``sov_home`` is the mapping from :func:`_sovereign_home`.
    """
    adm = str(adm0_a3)
    if adm in NON_POLITY_JUNK:
        return None                                  # dropped from both worlds
    if policy == "natural_earth":
        return adm                                   # every polity its own vertex
    # un195
    if adm in UN195_DROP:
        return None
    if adm in CONTESTED_MERGE:
        return CONTESTED_MERGE[adm]
    if adm in UN195_OBSERVER_SELF:
        return adm
    return sov_home.get(str(sov_a3), adm)


def assign_world_vertices(gdf, policy: str = DEFAULT_POLICY):
    """Return a GeoDataFrame (``_key``, ``_label``, ``geometry``) ready to dissolve.

    One row per NE unit that survives ``policy``; ``_key`` is the vertex id
    (dropped rows are removed) and ``_label`` is the display name. Dissolving by
    ``_key`` downstream merges dependencies / contested units into their member.
    """
    require_geo()
    _require_policy(policy)
    sov_home = _sovereign_home(gdf)
    keys = [world_vertex_key(a, s, policy, sov_home)
            for a, s in zip(gdf["ADM0_A3"].astype(str), gdf["SOV_A3"].astype(str))]
    block = gdf.assign(_key=keys)
    block = block[block["_key"].notna()].copy()
    block["_label"] = _display_labels(block, policy)
    return block[["_key", "_label", "geometry"]]


def _display_labels(block, policy: str) -> list:
    """Display name per surviving row. natural_earth shows the unit's own name;
    un195 shows the *member's* name (a merged unit displays its sovereign)."""
    admin = block["ADMIN"].astype(str)
    if policy == "natural_earth":
        return list(admin.values)
    # un195: label = ADMIN of the row whose ADM0_A3 == _key (the member home).
    name_by_code = dict(zip(block["ADM0_A3"].astype(str), admin))
    return [name_by_code.get(str(k), str(k)) for k in block["_key"].astype(str)]


__all__ = [
    "POLICIES", "DEFAULT_POLICY", "UN195_EXPECTED_COUNT", "NON_POLITY_JUNK",
    "UN195_DROP", "CONTESTED_MERGE", "UN195_OBSERVER_SELF",
    "assign_world_vertices", "world_vertex_key",
]
