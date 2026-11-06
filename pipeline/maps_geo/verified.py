"""Graphs a maintainer has checked end to end and found correct.

Verification is a human attestation, not something the build can derive, so it lives in a
committed file like the overrides. Each entry pins the graph it was checked against (a hash of
its vertex codes and edges): if a later build changes a verified graph, the export fails
instead of carrying the tag over to a graph nobody checked. Re-check the graph, then update
or drop its entry.
"""
from __future__ import annotations

import hashlib
import json

VERIFIED_PATH = "data/maps/verified.json"


def graph_sha256(codes, edges) -> str:
    """Hash of a graph's vertex codes and edges, independent of their order.

    `edges` are (code, code) pairs.
    """
    blob = {"nodes": sorted(codes), "edges": sorted(sorted(e) for e in edges)}
    return hashlib.sha256(json.dumps(blob, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_verified(path: str = VERIFIED_PATH) -> dict:
    """{graph id: entry} from the committed file."""
    with open(path, encoding="utf-8") as fh:
        blob = json.load(fh)
    out = {}
    for e in blob.get("graphs", []):
        if e["id"] in out:
            raise ValueError(f"verified: {e['id']} listed twice")
        out[e["id"]] = e
    return out


def verification(verified: dict, gid: str, codes, edges) -> dict | None:
    """The published `verification` record for one graph, or None if it isn't verified.

    Fails when the graph differs from the one that was verified.
    """
    e = verified.get(gid)
    if e is None:
        return None
    got = graph_sha256(codes, edges)
    if got != e["graph_sha256"]:
        raise ValueError(f"verified: {gid} changed since it was verified on {e['date']} "
                         f"(graph_sha256 {got[:12]}, pinned {e['graph_sha256'][:12]}); "
                         f"re-check it and update {VERIFIED_PATH}")
    return {"date": e["date"], "note": e["note"]}
