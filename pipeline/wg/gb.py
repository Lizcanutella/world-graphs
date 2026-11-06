"""geoBoundaries as a second, independent geometry of Natural Earth's vertex set.

The comparison only works when gB units nest inside NE units: then every gB unit has one NE
owner, and dissolving gB units by owner redraws each NE unit from independent data. So the
preferred layer is the coarsest one at least as fine as NE (unit count >= 0.9 n). The layer
closest to n in log ratio is also kept when it differs, and the pairs stage picks whichever
nests better (wg.pairs.match_quality); the choice is recorded per country.
"""
from __future__ import annotations

import math


def _count(r) -> int:
    try:
        return int(float(r.get("admUnitCount") or 0))
    except ValueError:
        return 0


def choose_levels(records: list, n: int) -> list:
    """gB levels to download for an NE graph with n vertices, best first (at most two)."""
    cands = [r for r in records if _count(r) > 1]
    if not cands or n < 2:
        return []
    finer = sorted((r for r in cands if _count(r) >= 0.9 * n), key=_count)
    closest = min(cands, key=lambda r: abs(math.log(_count(r) / n)))
    out = [finer[0]["boundaryType"]] if finer else []
    if closest["boundaryType"] not in out:
        out.append(closest["boundaryType"])
    return out
