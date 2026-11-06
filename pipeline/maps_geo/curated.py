"""Curated adjacency from Wikidata, pinned to a committed snapshot.

Wikidata is live and community-edited. Reading it at build time would make
builds irreproducible and let an upstream edit silently change a published
graph, so the build replays a committed snapshot and `--refresh`
is an explicit, reviewable, diffable act. Wikidata content is CC0.

The curated layer NEVER adds an edge: P47 ("shares border with") is maritime-
inclusive — it lists Michigan-Illinois across Lake Michigan — so letting it add
edges would reintroduce the exact defect this pipeline removes. It corroborates,
and its disagreements are recorded. See the spec's "Arbitration rules".
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

SNAPSHOT_PATH = "data/maps/curated_adjacency.json"
ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "world-graphs-research/1.0 (academic research; contact via repo)"

# P300 = ISO 3166-2 code (subdivisions); P297 = ISO 3166-1 alpha-2 (countries).
SUBDIVISION_QUERY = """SELECT ?ia ?ib WHERE {
  ?a wdt:P300 ?ia . ?a wdt:P47 ?b . ?b wdt:P300 ?ib . }"""
COUNTRY_QUERY = """SELECT ?ia ?ib WHERE {
  ?a wdt:P297 ?ia . ?a wdt:P47 ?b . ?b wdt:P297 ?ib . }"""


@dataclass
class CuratedAdjacency:
    pairs: set = field(default_factory=set)      # {(code_u, code_v)}, u < v

    def pairs_for(self, codes) -> set:
        """Curated pairs with BOTH endpoints inside `codes`.

        The both-endpoints rule is what keeps a cross-border neighbour out of a
        country map: P47 lists Michigan-Ontario, which is true and irrelevant.
        """
        s = set(codes)
        return {(u, v) for (u, v) in self.pairs if u in s and v in s}

    def covers(self, codes) -> bool:
        """Whether any curated pair touches this roster at all."""
        s = set(codes)
        return any(u in s or v in s for (u, v) in self.pairs)


def canonical_pairs(rows) -> set:
    """Sorted, de-duplicated, self-pair-free code pairs."""
    out = set()
    for u, v in rows:
        u, v = str(u), str(v)
        if u and v and u != v:
            out.add((u, v) if u < v else (v, u))
    return out


def load_snapshot(path: str = SNAPSHOT_PATH) -> CuratedAdjacency:
    with open(path, encoding="utf-8") as fh:
        blob = json.load(fh)
    return CuratedAdjacency(pairs=canonical_pairs(blob.get("pairs") or []))


def _sparql(query: str, *, timeout: float) -> list:
    url = ENDPOINT + "?format=json&query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        payload = json.load(fh)
    return [(r["ia"]["value"], r["ib"]["value"])
            for r in payload["results"]["bindings"]]


def refresh_snapshot(path: str = SNAPSHOT_PATH, *, timeout: float = 120.0) -> dict:
    """Re-fetch Wikidata and rewrite the pinned snapshot. Explicit, never implicit."""
    rows = _sparql(SUBDIVISION_QUERY, timeout=timeout)
    rows += _sparql(COUNTRY_QUERY, timeout=timeout)
    pairs = sorted(canonical_pairs(rows))
    body = [list(p) for p in pairs]
    digest = hashlib.sha256(
        json.dumps(body, separators=(",", ":")).encode("utf-8")).hexdigest()
    blob = {
        "fetched": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "endpoint": ENDPOINT,
        "queries": {"subdivision": SUBDIVISION_QUERY, "country": COUNTRY_QUERY},
        "sha256": digest,
        "n_pairs": len(pairs),
        "pairs": body,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(blob, fh, indent=1, sort_keys=False)
        fh.write("\n")
    return blob
