# world-graphs pipeline

Builds the region-adjacency graphs and exports the release that lives one level up (`../data`,
`../manifest.json`). Run everything from this directory (`uv run ...`); paths are
relative to it. Setup: `uv sync`.

From v0.2 the release is built by `wg/`, in four stages (see `wg/__init__.py` and
[`../METHODOLOGY.md`](../METHODOLOGY.md)):

```
uv run python -m wg.fetch            # download every input into data/cache, pinned in sources.lock.json
uv run python -m wg.pairs --jobs 4   # per country: label rule, pair measurements -> data/audit/pairs/
uv run python -m wg.decide           # votes -> edges -> data/build/graphs/, data/audit/review.csv
uv run python -m wg.export           # the release, and data/audit/diff_previous.csv
```

`wg.pairs` is the slow stage (Canada alone takes 30 minutes and 3 GB, Russia 6 minutes);
`--iso RU CA` reruns single countries. The other stages take a minute or two.

`wg.export --viz DIR` also writes the globe viewer's data (`graphs.json`, `outlines/`, `borders/`)
into `DIR`, which must already hold the previous `graphs.json` (the world graphs' entries are
carried over from it). The viewer itself is not part of this repository.

Inputs a maintainer edits:

- `data/maps/decisions.json`: hand decisions (relabels and edges), each with its reason and
  evidence. A decision for a pair that is no longer a candidate fails the build.
- `data/maps/verified.json`: graphs a maintainer has checked end to end. Each entry pins the hash
  of the checked graph, and the export fails if a rebuild changes it.

Reports in `data/audit/`: `review.csv` (pairs no rule settles), `diff_previous.csv` (changes against
the previous release), `labels.csv` (labels Wikidata still disputes), and `countries.csv`,
`units.csv` (Natural Earth against geoBoundaries per country, `wg.audit`).

`maps_geo/` is the first-generation build library. `wg` still uses it to turn NE rows into vertices
(`country_units`, naming), and its artifact (`data/maps/instances.jsonl`) lists the countries
`wg.fetch` downloads. The two world graphs were built by it for v0.1 and are carried over unchanged.
`data/maps/review/` is the archived evidence of the v0.1 edge review, which the export publishes as
`prior_evidence` and which `decisions.json` and `overrides.json` cite.

Tests: `uv run pytest`; set `WG_RUN_GEO_BUILD=1` to include the real Natural Earth builds.

History: the code was written inside an earlier research repository and moved here on 2026-09-30;
its earlier history is not included.
