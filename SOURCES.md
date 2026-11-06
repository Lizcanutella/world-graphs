# Sources and attribution

| source | used for | licence | redistributed here? |
|---|---|---|---|
| [Natural Earth](https://www.naturalearthdata.com/) 10m admin-0, admin-1 and ocean v5.1.1, 10m lakes v5.0.0 | vertices, geometry, adjacency; the ocean layer decides which water is sea | public domain | derived graphs and representative points only |
| [Wikidata](https://www.wikidata.org/) P47, P300 with coordinates (P625), P297 | edge votes (P47), label corrections, Wikidata item IDs | CC0 | item IDs |
| [pycountry](https://github.com/pycountry/pycountry) (ISO 3166 data) | country names, current ISO codes | LGPL-2.1 (library); codes are ISO 3166 | names only |
| [geoBoundaries](https://www.geoboundaries.org/) gbOpen (Runfola et al. 2020) | edge votes and label corrections only | per country: ODbL 1.0, CC BY 2.5–4.0, CC BY 3.0 IGO, CC BY-SA 2.0/3.0, public domain and national open licences | no (only which sources support an edge) |
| [Wikipedia](https://www.wikipedia.org/) | v0.1 review evidence (`prior_evidence`) only | CC BY-SA 4.0 | no (article URLs only) |

The geoBoundaries layer and licence used for each country are listed under `geoboundaries` in its
graph file. Every input is pinned by sha256 in
[`pipeline/sources.lock.json`](pipeline/sources.lock.json).

Runfola, D. et al. (2020) *geoBoundaries: A global database of political administrative
boundaries.* PLoS ONE 15(4): e0231866.
