"""world-graphs pipeline, second generation.

Stages (each a module, each reading only pinned inputs):

  fetch   download every external input into data/cache and record it in sources.lock.json
  pairs   per country: correct NE's rows where gB and Wikidata agree against it (wg.units),
          then measure every candidate pair in every independent geometry, in metres, and
          check every label against Wikidata's points (wg.labels)
  decide  turn each pair's votes (NE, gB, Wikidata P47) into an edge by fixed rules, plus the
          hand decisions in data/maps/decisions.json; list what no rule settles in
          data/audit/review.csv
  export  write the release (data/, manifest.json) from data/build/graphs, and
          data/audit/diff_previous.csv against the release it replaces

Reports: wg.audit (NE vs gB per country), wg.labels (label disputes).

The release is written by wg.export from 0.2.0 on. The first-generation build (maps_geo) is
still imported for NE vertex construction (country_units, naming), and its artifact
(data/maps/instances.jsonl) lists the countries wg.fetch downloads.
"""
