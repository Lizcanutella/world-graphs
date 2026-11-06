"""CLI: build the `maps` artifact from Natural Earth.

    python -m maps_geo build --data data/naturalearth \
        --out data/maps --eps 100
"""
from __future__ import annotations

import argparse


from .adjacency import DEFAULT_EPS_M
from .artifact import load, write
from .audit import audit_maps, render_report
from .build import build_maps
from .curated import SNAPSHOT_PATH, load_snapshot, refresh_snapshot
from .landmask import DEFAULT_MIN_LAKE_AREA_KM2, water_mask
from .naturalearth import country_geographs, world_geograph
from .overrides import OVERRIDES_PATH, load_overrides
from .policy import POLICIES


def _cmd_build(args) -> int:
    eps = args.eps
    policies = args.policies or list(POLICIES)
    water = None if args.no_clip else water_mask(args.data, min_area_km2=args.min_lake_km2)
    curated = None if args.no_curated else load_snapshot(args.curated)
    overrides = None if args.no_overrides else load_overrides(args.overrides)
    worlds = {} if args.no_world else {
        p: world_geograph(args.data, eps=eps, policy=p, water=water, curated=curated)
        for p in policies}
    countries = {} if args.no_countries else country_geographs(
        args.data, eps=eps, min_units=args.min_units, water=water, curated=curated,
        overrides=overrides)
    curated_meta = None
    if curated is not None:
        import json
        with open(args.curated, encoding="utf-8") as fh:
            blob = json.load(fh)
        curated_meta = {k: blob[k] for k in ("fetched", "sha256", "n_pairs")}
    manifest, instances = build_maps(
        worlds, countries, eps=eps,
        data_source="Natural Earth 10m admin-0 / 10m admin-1 / 10m lakes",
        curated_meta=curated_meta,
        min_lake_km2=None if water is None else args.min_lake_km2,
        overrides_meta=None if overrides is None else {
            "sha256": overrides.sha256, "relabel": len(overrides.relabel),
            "add_edges": len(overrides.add_edges), "remove_edges": len(overrides.remove_edges)})
    write(args.out, manifest, instances)
    print(f"built maps: {manifest.n_instances} instances -> {args.out}")
    print(f"  by family: {manifest.counts}")
    return 0


def _cmd_audit(args) -> int:
    water = None if args.no_clip else water_mask(
        args.data, min_area_km2=args.min_lake_km2)
    curated = None if args.no_curated else load_snapshot(args.curated)
    proposed = country_geographs(args.data, eps=args.eps, water=water,
                                 curated=curated)
    _, committed = load(args.against)
    report = audit_maps(proposed, committed, review_rate=args.review_rate)
    text = render_report(report)
    print(text)
    if args.out:
        import json
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
        with open(args.out.rsplit(".", 1)[0] + ".txt", "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


def _cmd_refresh_curated(args) -> int:
    blob = refresh_snapshot(args.out, timeout=args.timeout)
    print(f"curated snapshot: {blob['n_pairs']} pairs, sha256 {blob['sha256'][:12]} "
          f"-> {args.out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m maps_geo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the maps artifact")
    b.add_argument("--data", required=True, help="Natural Earth data dir (fetched if absent)")
    b.add_argument("--out", required=True, help="output dataset directory")
    b.add_argument("--eps", type=float, default=DEFAULT_EPS_M,
                   help="min geodesic shared-border length (metres)")
    b.add_argument("--min-units", type=int, default=2, dest="min_units")
    b.add_argument("--policy", action="append", dest="policies", choices=POLICIES,
                   help="inclusion policy to build a world for (repeatable; "
                        "default: both un195 and natural_earth)")
    b.add_argument("--no-world", action="store_true")
    b.add_argument("--no-countries", action="store_true")
    b.add_argument("--curated", default=SNAPSHOT_PATH)
    b.add_argument("--min-lake-km2", type=float, default=DEFAULT_MIN_LAKE_AREA_KM2,
                   dest="min_lake_km2")
    b.add_argument("--no-clip", action="store_true")
    b.add_argument("--no-curated", action="store_true")
    b.add_argument("--overrides", default=OVERRIDES_PATH,
                   help="pinned NE corrections (relabels, edge adds/removes)")
    b.add_argument("--no-overrides", action="store_true")
    b.set_defaults(func=_cmd_build)

    a = sub.add_parser("audit", help="report-only diff against a committed maps artifact")
    a.add_argument("--data", required=True)
    a.add_argument("--against", required=True, help="committed artifact dir to diff against")
    a.add_argument("--out", default=None, help="write report JSON (and .txt) here")
    a.add_argument("--eps", type=float, default=DEFAULT_EPS_M)
    a.add_argument("--curated", default=SNAPSHOT_PATH)
    a.add_argument("--min-lake-km2", type=float, default=DEFAULT_MIN_LAKE_AREA_KM2,
                   dest="min_lake_km2")
    a.add_argument("--review-rate", type=float, default=0.5, dest="review_rate")
    a.add_argument("--no-clip", action="store_true")
    a.add_argument("--no-curated", action="store_true")
    a.set_defaults(func=_cmd_audit)

    r = sub.add_parser("refresh-curated", help="re-fetch the Wikidata P47 snapshot")
    r.add_argument("--out", default=SNAPSHOT_PATH)
    r.add_argument("--timeout", type=float, default=120.0)
    r.set_defaults(func=_cmd_refresh_curated)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
