"""Pinned, reviewed corrections to Natural Earth, applied by the maps build.

The build's rules (geometry is necessary, curated data only corroborates) cannot fix a
defect in NE itself: two polygons carrying each other's names, a real border NE digitised
as a single point, or two units NE joins across an estuary. Those are corrected here, from
a committed file in which every entry names its reason and evidence, so each correction is
reviewable and diffable and the build records which ones it applied. The file is written
by hand from the edge review (evidence in data/maps/review/; the 2026-09-27 results note
it cites stayed in the earlier research repository); nothing writes it automatically.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

OVERRIDES_PATH = "data/maps/overrides.json"


@dataclass
class Overrides:
    relabel: list = field(default_factory=list)       # [{"ne_id", "set": {col: value}, ...}]
    add_edges: list = field(default_factory=list)     # [{"iso", "u", "v", "reason", ...}]
    remove_edges: list = field(default_factory=list)  # [{"iso", "u", "v", "reason", ...}]
    sha256: str | None = None

    def edges_for(self, iso: str) -> tuple:
        """(add, remove) as sorted code pairs for one country."""
        def pairs(entries):
            return sorted(tuple(sorted((e["u"], e["v"]))) for e in entries if e["iso"] == iso)
        return pairs(self.add_edges), pairs(self.remove_edges)

    def reason(self, iso: str, u: str, v: str) -> str:
        for e in self.add_edges + self.remove_edges:
            if e["iso"] == iso and {e["u"], e["v"]} == {u, v}:
                return e["reason"]
        raise KeyError((iso, u, v))


def load_overrides(path: str = OVERRIDES_PATH) -> Overrides:
    with open(path, "rb") as fh:
        raw = fh.read()
    blob = json.loads(raw)
    return Overrides(relabel=blob.get("relabel", []), add_edges=blob.get("add_edges", []),
                     remove_edges=blob.get("remove_edges", []),
                     sha256=hashlib.sha256(raw).hexdigest())


def apply_relabels(gdf, overrides: Overrides | None):
    """Copy of the NE admin-1 frame with each `relabel` entry's columns set on its `ne_id` row.

    Fails loudly when an entry's row is missing or no longer carries the values it
    corrects (`was`), which means NE changed underneath the override.
    """
    if overrides is None or not overrides.relabel:
        return gdf
    out = gdf.copy()
    ids = out["ne_id"].astype(str)
    for e in overrides.relabel:
        rows = ids == str(e["ne_id"])
        if rows.sum() != 1:
            raise ValueError(f"relabel override: ne_id {e['ne_id']} matches {rows.sum()} rows")
        for col, was in (e.get("was") or {}).items():
            if str(out.loc[rows, col].iloc[0]) != str(was):
                raise ValueError(f"relabel override: ne_id {e['ne_id']} has {col}="
                                 f"{out.loc[rows, col].iloc[0]!r}, expected {was!r}")
    for e in overrides.relabel:          # set after checking, so swaps don't see each other
        rows = ids == str(e["ne_id"])
        for col, val in e["set"].items():
            out.loc[rows, col] = val
    return out


def apply_edge_overrides(codes, edges, iso: str, overrides: Overrides | None):
    """(edges, applied) after the pinned additions and removals for `iso`.

    `edges` are index pairs over `codes`. An addition must be absent and a removal present,
    and both endpoints must exist; otherwise the build fails, because the override no
    longer describes this graph.
    """
    if overrides is None:
        return edges, []
    add, remove = overrides.edges_for(iso)
    if not add and not remove:
        return edges, []
    idx = {c: i for i, c in enumerate(codes)}
    cur = {tuple(sorted((codes[u], codes[v]))) for (u, v) in edges}
    applied = []
    for op, pairs in (("add", add), ("remove", remove)):
        for (u, v) in pairs:
            if u not in idx or v not in idx:
                raise ValueError(f"{iso} edge override {u}-{v}: unknown vertex")
            if (op == "add") == ((u, v) in cur):
                raise ValueError(f"{iso} edge override: cannot {op} {u}-{v} "
                                 f"({'already' if op == 'add' else 'not'} an edge)")
            (cur.add if op == "add" else cur.discard)((u, v))
            applied.append({"op": op, "u": u, "v": v, "reason": overrides.reason(iso, u, v)})
    out = sorted((min(idx[u], idx[v]), max(idx[u], idx[v])) for (u, v) in cur)
    return out, applied
