"""Arbitrate geometric and curated adjacency into the published edge set.

Geometry is necessary; curated corroborates. The full rationale, including why
strict intersection was rejected, is in the spec's "Arbitration rules". Pure: no
I/O, no geometry, no network, so the rule deciding every published edge is
exhaustively unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReconcileResult:
    edges: list                  # published edges, sorted code pairs
    provenance: dict             # {(u, v): "both" | "geometry_only"} for published edges
    curated_only_dropped: list   # curated pairs geometry did not see (water, point contact)
    geometry_only_kept: list     # published edges no curated source corroborates
    source: str                  # "reconciled" | "geometry_only"
    counts: dict                 # {"both": int, "geometry_only": int, "curated_only": int}
    geometry_only_rate: float    # share of published edges lacking corroboration


def _canon(pairs) -> set:
    out = set()
    for u, v in pairs:
        if u != v:
            out.add((u, v) if u < v else (v, u))
    return out


def reconcile(geometry_edges, curated_edges, *, curated_available: bool) -> ReconcileResult:
    """Publish geometry's edges, classified against the curated set."""
    geo = _canon(geometry_edges)
    cur = _canon(curated_edges)
    both = sorted(geo & cur)
    geom_only = sorted(geo - cur)
    cur_only = sorted(cur - geo)
    edges = sorted(geo)
    provenance = {e: ("both" if e in cur else "geometry_only") for e in edges}
    return ReconcileResult(
        edges=edges,
        provenance=provenance,
        curated_only_dropped=cur_only,
        geometry_only_kept=geom_only,
        source="reconciled" if curated_available else "geometry_only",
        counts={"both": len(both), "geometry_only": len(geom_only),
                "curated_only": len(cur_only)},
        geometry_only_rate=(len(geom_only) / len(edges)) if edges else 0.0,
    )
