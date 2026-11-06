"""Stage 1: fetch external inputs into data/cache, pinned in sources.lock.json.

    uv run python -m wg.fetch gb-meta            # geoBoundaries API records, all country graphs
    uv run python -m wg.fetch gb [--iso CO ...]  # the chosen gB layers (see wg.gb.choose_levels)
    uv run python -m wg.fetch ne                 # hash the Natural Earth files in use
    uv run python -m wg.fetch wd-codes           # Wikidata items for every ISO 3166-2 code

geoBoundaries: the API's `/current/` endpoint answers with download URLs that name a git commit
of wmgeolab/geoBoundaries, so recording the URL and the file's sha256 pins the layer exactly.
Full-resolution geometry is used, never the `_simplified` files: a simplified layer collapses
short borders the same way Natural Earth does, which is the defect we are comparing against.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

from .lock import CACHE_DIR, load_lock, save_lock, sha256_file

UA = {"User-Agent": "world-graphs/0.2 (region-adjacency dataset build)"}
GB_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ALL/"
NE_DIR = "data/naturalearth"
NE_FILES = ["ne_10m_admin_0_countries", "ne_10m_admin_1_states_provinces", "ne_10m_lakes", "ne_10m_ocean"]
GB_KEEP = ("boundaryID", "boundaryType", "boundaryYearRepresented", "boundarySource",
           "boundaryLicense", "admUnitCount", "gjDownloadURL", "buildDate")


def _get(url: str, *, tries: int = 5, timeout: int = 600) -> bytes:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            err = e
        except Exception as e:  # network hiccup: back off and retry
            err = e
        print(f"  retry {attempt + 1}: {url}: {err}", file=sys.stderr)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def country_isos(maps_dir: str = "data/maps") -> dict:
    """{alpha-2: NE vertex count} for every country graph in the artifact."""
    from maps_geo.artifact import load
    _, inst = load(maps_dir)
    return {i.params["iso"]: i.n for i in inst if i.params.get("iso")}


def iso3(a2: str) -> str | None:
    import pycountry
    c = pycountry.countries.get(alpha_2=a2)
    return c.alpha_3 if c else {"XK": "XKX"}.get(a2)


def fetch_gb_meta(isos, lock: dict) -> None:
    meta = lock.setdefault("geoboundaries", {}).setdefault("meta", {})
    for a2 in sorted(isos):
        if a2 in meta:
            continue
        a3 = iso3(a2)
        try:
            recs = json.loads(_get(GB_API.format(iso3=a3), timeout=120)) if a3 else []
        except urllib.error.HTTPError:
            recs = []
        if isinstance(recs, dict):
            recs = [recs]
        meta[a2] = sorted(({k: r.get(k) for k in GB_KEEP} for r in recs
                           if str(r.get("boundaryType", "")).startswith("ADM")
                           and r.get("boundaryType") != "ADM0"),
                          key=lambda r: r["boundaryType"])
        print(a2, a3, [(r["boundaryType"], r["admUnitCount"]) for r in meta[a2]], flush=True)
        time.sleep(0.3)


def gb_path(a2: str, level: str) -> str:
    return os.path.join(CACHE_DIR, "gb", f"{a2}-{level}.geojson")


def fetch_gb(levels: dict, lock: dict, *, save) -> None:
    """Download {a2: [level, ...]} at full resolution; verify or record each sha256."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    files = lock.setdefault("geoboundaries", {}).setdefault("files", {})
    meta = lock["geoboundaries"]["meta"]
    jobs = []
    for a2 in sorted(levels):
        for level in levels[a2]:
            rec = next(r for r in meta[a2] if r["boundaryType"] == level)
            jobs.append((a2, level, rec))

    def download(job):
        a2, level, rec = job
        path = gb_path(a2, level)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = _get(rec["gjDownloadURL"])
            with open(path + ".part", "wb") as fh:
                fh.write(data)
            os.replace(path + ".part", path)
        return job

    with ThreadPoolExecutor(max_workers=6) as ex:     # downloads in parallel; hashing and the lock stay on this thread
        for fut in as_completed([ex.submit(download, j) for j in jobs]):
            a2, level, rec = fut.result()
            key, path = f"{a2}-{level}", gb_path(a2, level)
            digest = sha256_file(path)
            pinned = files.get(key)
            if pinned and pinned["sha256"] != digest:
                raise SystemExit(f"{key}: sha256 differs from sources.lock.json ({path})")
            files[key] = {"url": rec["gjDownloadURL"], "sha256": digest,
                          "bytes": os.path.getsize(path)}
            print(key, files[key]["bytes"] // 1024, "KiB", flush=True)
            save()


def hash_ne(lock: dict) -> None:
    ne = lock.setdefault("natural_earth", {})
    for stem in NE_FILES:
        ver = open(os.path.join(NE_DIR, stem + ".VERSION.txt")).read().strip()
        ne[stem] = {"version": ver,
                    **{ext: sha256_file(os.path.join(NE_DIR, f"{stem}.{ext}"))
                       for ext in ("shp", "dbf", "shx", "prj")}}


WD_SPARQL = "https://query.wikidata.org/sparql"
# Every item that has (or had: all ranks, so deprecated codes NE still uses are kept) an ISO
# 3166-2 code, with its coordinates and English label. One query, one pinned file.
WD_CODES_QUERY = """SELECT ?item ?code ?rank ?coord ?label WHERE {
  ?item p:P300 ?st . ?st ps:P300 ?code ; wikibase:rank ?rank .
  OPTIONAL { ?item wdt:P625 ?coord }
  OPTIONAL { ?item rdfs:label ?label FILTER(LANG(?label) = "en") }
}"""


def fetch_wd_codes(lock: dict, *, update: bool = False) -> None:
    """Snapshot of ISO 3166-2 code -> Wikidata item, coordinates, label (CC0)."""
    import datetime as dt
    import urllib.parse
    path = os.path.join(CACHE_DIR, "wikidata", "p300_codes.json")
    pinned = lock.get("wikidata", {}).get("p300_codes")
    if not os.path.exists(path) or update:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        body = urllib.parse.urlencode({"query": WD_CODES_QUERY, "format": "json"}).encode()
        req = urllib.request.Request(WD_SPARQL, data=body, headers={
            **UA, "Accept": "application/sparql-results+json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            rows = json.load(r)["results"]["bindings"]
        out = sorted(({k: v["value"] for k, v in row.items()} for row in rows),
                     key=lambda r: (r["code"], r["item"], r.get("coord", ""), r.get("label", "")))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=0)
        pinned = None
        fetched = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    digest = sha256_file(path)
    if pinned and pinned["sha256"] != digest:
        raise SystemExit("wikidata p300_codes: sha256 differs from sources.lock.json")
    if not pinned:
        lock.setdefault("wikidata", {})["p300_codes"] = {
            "path": path, "sha256": digest, "fetched": fetched, "query": WD_CODES_QUERY,
            "rows": len(json.load(open(path, encoding="utf-8")))}
    print("wikidata p300_codes:", lock["wikidata"]["p300_codes"]["rows"], "rows")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wg.fetch")
    ap.add_argument("what", choices=["gb-meta", "gb", "ne", "wd-codes"])
    ap.add_argument("--update", action="store_true", help="re-fetch and re-pin (wd-codes)")
    ap.add_argument("--iso", nargs="*")
    a = ap.parse_args(argv)
    lock = load_lock()
    save = lambda: save_lock(lock)
    isos = country_isos()
    if a.iso:
        isos = {k: v for k, v in isos.items() if k in a.iso}
    if a.what == "gb-meta":
        fetch_gb_meta(isos, lock)
    elif a.what == "gb":
        from .gb import choose_levels
        meta = lock["geoboundaries"]["meta"]
        fetch_gb({a2: choose_levels(meta.get(a2, []), n) for a2, n in isos.items()
                  if choose_levels(meta.get(a2, []), n)}, lock, save=save)
    elif a.what == "ne":
        hash_ne(lock)
    elif a.what == "wd-codes":
        fetch_wd_codes(lock, update=a.update)
    save()


if __name__ == "__main__":
    main()
