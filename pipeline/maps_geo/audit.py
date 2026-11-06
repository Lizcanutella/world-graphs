"""Report-only diff of the proposed pipeline against the committed artifact.

Writes nothing to data/maps: the blast radius of a pipeline change is reviewed
before the committed artifact is rebuilt.
"""
from __future__ import annotations

DEFAULT_REVIEW_RATE = 0.5      # provisional; set from the measured distribution


def _edges_of(inst) -> list:
    """Edge list of a GeoGraph or an artifact Instance (both carry `.edges`)."""
    return list(getattr(inst, "edges", None) or [])


def _committed_by_iso(committed) -> dict:
    out = {}
    for inst in committed:
        iso = (getattr(inst, "params", {}) or {}).get("iso")
        if iso:
            out[str(iso)] = inst
    return out


def audit_maps(proposed: dict, committed, *, review_rate: float = DEFAULT_REVIEW_RATE) -> dict:
    """Per-country before/after report plus the countries needing hand review."""
    before = _committed_by_iso(committed)
    countries, needs_review = {}, []
    for iso in sorted(proposed):
        g = proposed[iso]
        adj = g.adjacency or {}
        roster = adj.get("roster", {})
        old = before.get(iso)
        units = roster.get("units") or 0
        rate = float(adj.get("geometry_only_rate") or 0.0)
        countries[iso] = {
            "n_before": old.n if old else None,
            "n_after": g.n,
            "edges_before": len(_edges_of(old)) if old else None,
            "edges_after": len(g.edges),
            "curated_only_dropped": adj.get("counts", {}).get("curated_only", 0),
            "geometry_only": adj.get("counts", {}).get("geometry_only", 0),
            "geometry_only_rate": rate,
            "join_rate": (roster.get("matched", 0) / units) if units else 0.0,
            "not_in_current_iso": len(roster.get("not_in_current_iso", [])),
            "source": adj.get("source"),
        }
        if rate > review_rate:
            needs_review.append(iso)
    gone = sorted(set(before) - set(proposed))
    return {"countries": countries, "needs_review": needs_review,
            "disappeared": gone,
            "totals": {"countries": len(countries),
                       "needs_review": len(needs_review),
                       "disappeared": len(gone)}}


def render_report(report: dict) -> str:
    """Plain-text table, one row per country."""
    head = (f"{'iso':<5}{'n_before':>9}{'n_after':>8}{'e_before':>9}{'e_after':>8}"
            f"{'drop_cur':>9}{'geo_only':>9}{'join':>7}{'stale':>7}")
    lines = [head, "-" * len(head)]
    for iso, r in sorted(report["countries"].items()):
        lines.append(
            f"{iso:<5}{str(r['n_before']):>9}{r['n_after']:>8}"
            f"{str(r['edges_before']):>9}{r['edges_after']:>8}"
            f"{r['curated_only_dropped']:>9}{r['geometry_only']:>9}"
            f"{r['join_rate']:>7.2f}{r.get('not_in_current_iso', 0):>7}")
    lines.append("")
    lines.append(f"totals: {report['totals']}")
    if report.get("needs_review"):
        lines.append(f"NEEDS REVIEW (geometry_only_rate high): {report['needs_review']}")
    if report.get("disappeared"):
        lines.append(f"DISAPPEARED from the artifact: {report['disappeared']}")
    return "\n".join(lines)
