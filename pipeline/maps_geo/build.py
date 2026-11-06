"""GeoDataFrame -> GeoGraph, and the offline `maps` artifact builder."""
from __future__ import annotations

from collections import Counter

from . import GeoGraph, require_geo
from .artifact import Instance, Manifest, instance_id
from .adjacency import DEFAULT_EPS_M, geo_adjacency, normalize_positions
from .landmask import clip_units
from .overrides import apply_edge_overrides
from .reconcile import reconcile
from .roster import admin1_granularity_label, dominant_type

# Bumped when a pipeline change invalidates a previously-committed maps artifact.
# "iso-roster-reconciled" = admin-1 vertices are NE units keyed on their ISO
# 3166-2 code (same-code same-name pieces dissolved), geometry lake-clipped,
# edges classified against a pinned Wikidata P47 snapshot (fetched 2026-09-18,
# see curated_adjacency.json; the pipeline change itself dates from 2026-09-26).
# "stable-id-keys" (2026-07-17) and unversioned artifacts predate the change.
# "+overrides" (2026-09-27) = plus the pinned NE corrections in overrides.json.
PIPELINE_VERSION = "iso-roster-reconciled+overrides"


def ordered_geoms(gdf, *, key: str):
    """(keys, {vertex_id: geometry}) — one dissolved geometry per distinct `key`,
    vertex ids assigned by sorted key so ordering matches `gdf_to_geograph`."""
    require_geo()
    merged = gdf.dissolve(by=key)                 # multipart per key -> one row
    keys = sorted(str(k) for k in merged.index)
    geom_by_key = {str(k): merged.loc[k, "geometry"] for k in merged.index}
    geoms = {i: geom_by_key[k] for i, k in enumerate(keys)}
    return keys, geoms


def gdf_to_geograph(gdf, *, key: str, eps: float = DEFAULT_EPS_M,
                    label: str | None = None) -> GeoGraph:
    """One vertex per distinct `key`; edges where shared border exceeds `eps` METRES.

    `key` must be a STABLE UNIT ID, never a display name: vertices are dissolved
    by it, so two distinct units sharing a key silently merge into one. `label`
    names the column shown to users and defaults to `key`; labels may repeat.
    `eps` is a geodesic distance in metres (see `geo_adjacency`).
    """
    keys, geoms = ordered_geoms(gdf, key=key)
    edges = geo_adjacency(geoms, eps=eps)
    reps = [geoms[i].representative_point() for i in range(len(keys))]
    positions = normalize_positions([(p.x, p.y) for p in reps])
    labels = keys if label is None else _labels_for(gdf, key=key, label=label, keys=keys)
    return GeoGraph(n=len(keys), edges=edges, positions=positions, labels=labels)


def _labels_for(gdf, *, key: str, label: str, keys: list) -> list:
    """Display label per vertex, in `keys` order. First value wins for a
    multi-part unit (its rows carry the same label)."""
    lookup = (gdf[[key, label]].astype({key: str, label: str})
              .drop_duplicates(subset=[key]).set_index(key)[label].to_dict())
    return [lookup[k] for k in keys]


def _reconciled_adjacency(codes, geoms, *, eps, curated, curated_key=None):
    """(index edges, ReconcileResult) for vertices keyed by `codes`.

    Shared by the country and world paths: run the unchanged metric predicate on
    already lake-clipped `geoms`, then classify each edge against the curated
    snapshot. Curated data
    never adds or removes an edge (see `reconcile`). `curated_key` maps a vertex
    code to the code space the snapshot uses (identity for ISO 3166-2; ADM0_A3 ->
    alpha-2 for the world); a code it maps to None has no curated counterpart.
    """
    key = curated_key or (lambda c: c)
    idx = {c: i for i, c in enumerate(codes)}
    raw = geo_adjacency({idx[c]: geoms[c] for c in codes}, eps=eps)
    geo_pairs = [(codes[u], codes[v]) for (u, v) in raw]

    cur = {c: key(c) for c in codes}
    back = {}
    for c, k in cur.items():
        if k is not None:
            back.setdefault(k, []).append(c)
    curated_pairs, available = set(), False
    if curated is not None:
        mapped = {k for k in back}
        available = curated.covers(mapped)
        for (a, b) in curated.pairs_for(mapped):
            for u in back[a]:
                for v in back[b]:
                    curated_pairs.add((u, v))
    rec = reconcile(geo_pairs, curated_pairs, curated_available=available)
    edges = sorted((min(idx[u], idx[v]), max(idx[u], idx[v])) for (u, v) in rec.edges)
    return edges, rec


def _provenance(rec, *, eps, water) -> dict:
    return {"source": rec.source, "eps_m": eps, "land_clipped": water is not None,
            "counts": rec.counts,
            "curated_only_dropped": [list(p) for p in rec.curated_only_dropped],
            "geometry_only_kept": [list(p) for p in rec.geometry_only_kept],
            "geometry_only_rate": round(rec.geometry_only_rate, 6)}


def _missing(v) -> bool:
    return v is None or str(v).strip().lower() in {"", "nan", "none"}


def _unit_keys(block, by_code=None) -> list:
    """Vertex key per NE row: its ISO 3166-2 code, plus the name when needed.

    Rows sharing a code AND a name are pieces of one unit and dissolve into one
    vertex — the reported defect (Chitipa, Parwan, Uruzgan, Rezina, Pomoravski
    each arriving as two touching vertices). Rows sharing a code under DIFFERENT
    names are distinct units NE files under one code (Madagascar's 22 regions
    under 6 old province codes, Bosnia's cantons under BA-BIH, Bogota under
    Cundinamarca's code, Tehran with Alborz), so they stay apart, keyed
    `CODE:Name` to keep keys unique — except the one whose name is the code's
    current ISO name, which keeps the bare code (New South Wales stays `AU-NSW`
    beside `AU-NSW:Lord Howe Island`). A nameless row takes the name of its
    code's other rows when those agree.
    """
    by_code = by_code or {}
    names = {}
    for code, nm in zip(block["iso_3166_2"].astype(str), block["name"]):
        if not _missing(nm):
            names.setdefault(code, set()).add(str(nm).strip())
    keys = []
    for code, nm in zip(block["iso_3166_2"].astype(str), block["name"]):
        known = names.get(code, set())
        if _missing(nm):
            keys.append(code if len(known) == 1 else None)
        else:
            nm = str(nm).strip()
            official = by_code[code].name if code in by_code else None
            keys.append(code if len(known) == 1 or nm == official else f"{code}:{nm}")
    return keys


def country_units(gdf, units, *, water=None):
    """(codes, {code: lake-clipped geometry}, keyed block, dropped fragments).

    The single definition of a country map's vertices, shared by the build and
    the Gallery overlay (`outlines.py`) so the two can never disagree.
    """
    by_code = {u.code: u for u in units}
    block = gdf.copy()
    block["_key"] = _unit_keys(block, by_code)
    unnamed = block["_key"].isna()
    fragments = sorted(set(block.loc[unnamed, "iso_3166_2"].astype(str)) - set(by_code))
    block.loc[unnamed, "_key"] = block.loc[unnamed, "iso_3166_2"].astype(str)
    block = block[~block["_key"].isin(fragments)]
    codes, geoms_by_index = ordered_geoms(block, key="_key")
    geoms = clip_units({codes[i]: g for i, g in geoms_by_index.items()}, water)
    return codes, geoms, block, fragments


def world_units(block, *, water=None):
    """(codes, {code: lake-clipped geometry}) for a policy-assigned admin-0 block."""
    codes, geoms_by_index = ordered_geoms(block, key="_key")
    return codes, clip_units({codes[i]: g for i, g in geoms_by_index.items()}, water)


def roster_geograph(gdf, units, *, eps=DEFAULT_EPS_M, water=None, curated=None,
                    overrides=None, iso=None) -> GeoGraph:
    """One vertex per Natural Earth unit, identified by its ISO 3166-2 code.

    See `_unit_keys` for how NE rows become vertices. The vertex set comes from
    NE's OWN codes, not an intersection with `units` (pycountry's current ISO
    roster): NE's codes are an older ISO vintage, so that intersection matched
    zero units for PL, CZ, GT, KE, KZ, ... and deleted whole countries (see the
    2026-09-26 amendment in the spec). `units` only names vertices NE leaves
    unnamed, derives the granularity, and reports how many codes are current. A
    nameless row with no roster entry is an unidentified fragment (Antarctica's
    `AQ-X02~`) and is dropped, recorded.

    Geometry is lake-clipped before adjacency, and the edges are classified
    against `curated`, which never adds or removes an edge. Only the pinned,
    reviewed `overrides` for `iso` do (see `overrides.py`); each one applied is
    recorded in `adjacency.overrides`.
    """
    require_geo()
    by_code = {u.code: u for u in units}
    codes, geoms, block, fragments = country_units(gdf, units, water=water)
    edges, rec = _reconciled_adjacency(
        codes, geoms, eps=eps, curated=curated,
        curated_key=lambda c: c.split(":", 1)[0])
    edges, applied = apply_edge_overrides(codes, edges, iso, overrides)

    reps = [geoms[c].representative_point() for c in codes]
    positions = normalize_positions([(p.x, p.y) for p in reps])
    labels = [_ne_label(block, c) or (by_code[c].name if c in by_code else c)
              for c in codes]
    labels = _disambiguate(labels, codes, by_code, block)

    iso_codes = {c.split(":", 1)[0] for c in codes}
    current = sorted(iso_codes & set(by_code))
    dom = dominant_type([by_code[c] for c in current])
    g = GeoGraph(n=len(codes), edges=edges, positions=positions, labels=labels,
                 codes=list(codes))
    if dom:
        g.granularity = admin1_granularity_label([dom])
    elif "type_en" in block.columns:
        g.granularity = admin1_granularity_label(block["type_en"].tolist())
    g.adjacency = _provenance(rec, eps=eps, water=water)
    if applied:
        _record_overrides(g.adjacency, applied)
    g.adjacency["roster"] = {
        "units": len(units), "matched": len(current),
        "unmatched_roster": sorted(set(by_code) - iso_codes),
        "not_in_current_iso": sorted(iso_codes - set(by_code)),
        "dropped_unnamed": fragments,
        "dominant_type": dom}
    return g


def _record_overrides(adj, applied) -> None:
    """Keep the provenance lists true to the published edges after pinned overrides.

    An added edge leaves `curated_only_dropped` (it is published now); a removed one
    leaves `geometry_only_kept`. Both are listed under `overrides` with their reason.
    """
    added = {tuple(sorted((a["u"], a["v"]))) for a in applied if a["op"] == "add"}
    removed = {tuple(sorted((a["u"], a["v"]))) for a in applied if a["op"] == "remove"}
    key = lambda p: tuple(sorted(p))
    adj["curated_only_dropped"] = [p for p in adj["curated_only_dropped"] if key(p) not in added]
    kept = {key(p) for p in adj["geometry_only_kept"]}
    adj["geometry_only_kept"] = [p for p in adj["geometry_only_kept"] if key(p) not in removed]
    c = adj["counts"]
    c["both"] -= len(removed - kept)
    c["curated_only"] = len(adj["curated_only_dropped"])
    c["geometry_only"] = len(adj["geometry_only_kept"])
    c["override"] = len(added)
    n_pub = c["both"] + c["geometry_only"] + c["override"]
    adj["geometry_only_rate"] = round(c["geometry_only"] / n_pub, 6) if n_pub else 0.0
    adj["overrides"] = applied


def _disambiguate(labels, codes, by_code, block) -> list:
    """Make repeated labels distinguishable, touching only the repeats.

    A repeat is sometimes an NE naming error — Rasinski okrug (RS-19) ships as a
    second "Pomoravski", Wirral (GB-WRL) as a second "Halton" — so a repeated
    vertex whose code has a DIFFERENT current ISO name takes that name. Genuine
    namesakes (Veszprém city and county, Tashkent city and region) then get
    NE's unit type appended, and any still-repeated label its code. Unrepeated labels keep NE's name: the roster is not
    trusted wholesale because stale codes can name a different unit (Iran's
    2020 renumbering).
    """
    out = list(labels)
    counts = Counter(out)
    for i, c in enumerate(codes):
        u = by_code.get(c)
        if counts[labels[i]] > 1 and u is not None and u.name != labels[i]:
            out[i] = u.name
    counts = Counter(out)
    types = {}
    if "type_en" in block.columns:
        for k, t in zip(block["_key"], block["type_en"]):
            if not _missing(t):
                types.setdefault(k, str(t).strip())
    out = [f"{x} ({types[c]})" if counts[x] > 1 and c in types else x
           for x, c in zip(out, codes)]
    counts = Counter(out)
    return [f"{x} ({c})" if counts[x] > 1 else x for x, c in zip(out, codes)]


def _ne_label(block, key):
    """Natural Earth's display name for vertex `key`, or None when NE has none.

    Every row under a key shares one name by construction (`_unit_keys`), except
    nameless pieces, which are skipped.
    """
    for v in block.loc[block["_key"] == key, "name"].tolist():
        if not _missing(v):
            return str(v).strip()
    return None


def _instance(g, *, family, params):
    return Instance(
        id=instance_id(family, g.n, params), family=family, n=g.n, params=params,
        edges=[(int(u), int(v)) for (u, v) in g.edges], positions=list(g.positions),
        labels=list(g.labels), codes=list(g.codes), adjacency=dict(g.adjacency))


def build_maps(worlds, countries, *, eps, data_source, curated_meta=None,
               min_lake_km2=None, overrides_meta=None):
    """Per-policy world GeoGraphs + per-country GeoGraphs -> (Manifest, [Instance]).

    `worlds` maps an inclusion policy name (`"un195"`/`"natural_earth"`, see
    `maps_geo.policy`) to its admin-0 GeoGraph; each becomes a separate `map_world`
    instance tagged `params={"policy": policy}`. Each country becomes a `map_country`
    instance from its 10m admin-1 graph, tagged with its ISO code and, when known, its
    administrative granularity (states/provinces/...).
    """
    instances = [_instance(worlds[p], family="map_world", params={"policy": p})
                 for p in sorted(worlds or {})]
    for iso in sorted(countries):
        g = countries[iso]
        params = {"iso": iso}
        if g.granularity:
            params["granularity"] = g.granularity
        instances.append(_instance(g, family="map_country", params=params))

    manifest = Manifest(
        version="maps-v2", generator="maps_geo", n_instances=len(instances),
        counts=dict(Counter(i.family for i in instances)),
        extra={"eps": eps, "eps_unit": "metres", "data_source": data_source,
               "pipeline": PIPELINE_VERSION,
               "curated_snapshot": curated_meta, "min_lake_km2": min_lake_km2,
               "overrides": overrides_meta,
               "adjacency": "geodesic shared-border length (WGS84) > eps metres, "
                            "after clipping lakes > min_lake_km2; one vertex per "
                            "unit; multipart dissolved; curated corroborates, "
                            "never adds"})
    return manifest, instances
