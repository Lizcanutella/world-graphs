# Region adjacency graphs

Land-border adjacency graphs for the countries of the world and their first-level subdivisions
(states, provinces, regions, counties…). Every border edge records the sources that support
it.

- **213 graphs:** 211 countries (admin-1 units as vertices) plus two world maps (countries as
  vertices, under two inclusion policies).
- **Vertices** are Natural Earth 10m units, identified by their ISO 3166-2 code (or ISO 3166-1 /
  ADM0_A3 for the world). They carry the unit's name, its Wikidata item where it could be
  resolved, and a representative point (lon/lat).
- **An edge** means the two units share a *land* border longer than 100 m, measured geodesically
  after removing lakes over 500 km². Units meeting at a single point (the US Four Corners) and
  units facing each other only across water (Michigan–Illinois) are **not** adjacent.
- **Provenance:** each edge lists the independent sources that support it (Natural Earth,
  geoBoundaries, Wikidata) and the rule that made it an edge. See [METHODOLOGY.md](METHODOLOGY.md).

Status: **v0.2, pre-release.** 13% of country edges (1,158 of 8,775) rest on Natural Earth alone,
with no second source. They are flagged `corroborated: false`. See
[KNOWN_ISSUES.md](KNOWN_ISSUES.md), which also lists what changed from v0.1.

## Files

```
data/countries/<ISO>.json      one graph per country (alpha-2 code, e.g. US.json)
data/countries/<ISO>.graphml   the same graph as GraphML (networkx, igraph, Gephi, …)
data/world/un195.json          193 UN members + Vatican + Palestine
data/world/natural_earth.json  every Natural Earth admin-0 polity
data/nodes.csv, data/edges.csv every graph in two flat tables
manifest.json                  versions, counts, per-file sha256
validate.py                    stdlib-only integrity check
pipeline/                      the code that builds the graphs, its pinned inputs and audit reports
```

To browse the graphs, open [lizcanomateo.com/world-graphs](https://lizcanomateo.com/world-graphs),
an interactive visualization of this dataset. It shows the world graph on a globe; pick a country
to fly to it and see its subdivision graph, and export any graph as PNG, SVG, TikZ, CSV or JSON.
Every graph there has a **Report a problem with this graph** link to a prefilled issue in this
repository.

A country graph file (schema `region-adjacency/2`):

```json
{
 "schema": "region-adjacency/2", "id": "EC", "kind": "country", "name": "Ecuador",
 "level": "provinces", "n": 24, "m": 54, "verified": false,
 "nodes": [{"code": "EC-A", "name": "Azuay", "wikidata": "Q220451", "lon": -79.20677, "lat": -3.06886}, …],
 "edges": [{"u": "EC-A", "v": "EC-F", "rule": "ne_and_gb", "ne_border_m": 143422,
            "sources": [{"source": "natural_earth"}, {"source": "geoboundaries"}, {"source": "wikidata_p47"}],
            "corroborated": true}, …],
 "relabels": [{"ne_id": "1159310001", "was": {"iso_3166_2": "EC-N", "name": "Napo"},
               "set": {"iso_3166_2": "EC-T", "name": "Tungurahua"}, "rule": "gb_and_wikidata_against_ne"}, …],
 "geoboundaries": {"boundaryID": "ECU-ADM1-780006", "level": "ADM1", "year": "2011", "license": "CC0 1.0 …"}
}
```

`sources` values:

| source | meaning |
|---|---|
| `natural_earth` | the units share more than 100 m of border in Natural Earth |
| `geoboundaries` | geoBoundaries, an independently digitised boundary set, has at least 500 m of land or river border between the matching units |
| `wikidata_p47` | Wikidata "shares border with" (P47) lists the pair |
| `hand` | a decision in `pipeline/data/maps/decisions.json`, with its reason |

An edge is `corroborated` when a hand decision or at least two sources support it. `rule` names
the rule that made it an edge (see [METHODOLOGY.md](METHODOLOGY.md#edges)). Some edges also carry
`prior_evidence` from the v0.1 review (Wikipedia URLs, Wikidata items, enclaves): information only,
not counted. `relabels` lists the Natural Earth units whose code or name was corrected.

Country edges in v0.2 by sources: 4,981 Natural Earth, geoBoundaries and Wikidata;
2,008 Natural Earth and geoBoundaries; 556 Natural Earth and Wikidata; 40 geoBoundaries and
Wikidata (borders Natural Earth collapsed); 32 hand decisions; and 1,158 Natural Earth alone.

The two world graphs are carried over from v0.1 and keep schema `region-adjacency/1` (sources
`wikidata_code`, `wikidata_item`, `geoboundaries`, `wikipedia`, `review`, `geometry_enclave`,
`override`; corroborated when any source is listed).

`verified` is `true` when a maintainer has checked the whole graph against the map and found it
correct. Such graphs also carry `"verification": {"date": …, "note": …}`, and `manifest.json` lists
them under `verified`. The tag is pinned to the exact graph that was checked: if a later build
changes the graph, the export refuses to publish the stale tag. Verified so far: Colombia (`CO`).

## Quick start

```python
import json, networkx as nx
g = json.load(open("data/countries/US.json"))
G = nx.Graph([(e["u"], e["v"]) for e in g["edges"]])
G.add_nodes_from(n["code"] for n in g["nodes"])   # keep isolated units (islands, exclaves)
print(G.number_of_nodes(), G.number_of_edges())
```

## Licence and attribution

Data: [CC BY 4.0](LICENSE). Please cite via [CITATION.cff](CITATION.cff) and credit the upstream
sources in [SOURCES.md](SOURCES.md). The graphs derive from Natural Earth (public domain) and
Wikidata (CC0). geoBoundaries (licence per country) and Wikipedia (CC BY-SA) were used only as
evidence: no geometry or article text is redistributed, only which sources agree and a URL.

## Scope and politics

The boundaries are Natural Earth's de facto view, not an endorsement. Disputed areas follow
Natural Earth's assignment (for example, Crimea and Sevastopol appear on the Russia map), as
listed in [METHODOLOGY.md](METHODOLOGY.md#disputed-territories). Subdivision codes are Natural
Earth's vintage (v5.1.1) and predate several reforms (Norway 2020, Latvia 2021, Iran's 2020
renumbering…).
