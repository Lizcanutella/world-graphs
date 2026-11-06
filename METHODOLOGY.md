# Methodology

From v0.2 the graphs are built in four stages (`pipeline/wg/`), each reading only pinned inputs:

1. **fetch** downloads every source and pins it by sha256 in `pipeline/sources.lock.json`.
2. **pairs** builds each country's vertices, corrects mislabelled Natural Earth units, and measures
   every candidate pair of units in every source, in metres.
3. **decide** turns each pair's measurements into votes and the votes into an edge, by fixed rules.
   What no rule settles is listed for review, and the few hand decisions are in
   `pipeline/data/maps/decisions.json`, each with its reason.
4. **export** writes this release and a diff against the previous one.

Every correction is a rule applied to every country, not a patch for one pair. Hand decisions are
the exception: 35 edges and two swapped pairs of codes.

## Vertices

Country graphs take the Natural Earth (NE) 10m admin-1 units filed under the country's
`iso_a2`, keyed by NE's ISO 3166-2 code.

- Rows with the same code **and** name are pieces of one unit and are merged.
- Rows sharing a code under different names stay separate as `CODE:Name`, for example
  `AU-NSW:Lord Howe Island` beside `AU-NSW`.
- Unnamed fragments with no ISO entry are dropped.
- A name NE repeats is repaired when the code's current ISO name differs (NE ships Wirral as a
  second "Halton"). True namesakes are told apart by NE's unit type, then by code.

World graphs take NE admin-0 units (key `ADM0_A3`) under one of two policies:

- `un195`: non-member units are merged into their UN-recognised sovereign.
- `natural_earth`: every polity is its own vertex.

The world graphs are outside the v0.2 pipeline and are carried over from v0.1 unchanged.

### Label corrections

NE has units with the wrong code or name: swapped pairs, shuffles of a whole country's regions, and
units hidden under a neighbour's code. A row is relabelled only when two independent sources agree
against NE:

- **geoBoundaries:** the gB unit holding at least half of the row carries another code.
- **Wikidata:** a point of the item holding that other code lies in the row, while every point of
  NE's own code lies elsewhere. NE's code must have a point at all, so that a capital city NE
  draws as its own vertex is never folded into its province.

A relabel that would merge two units is dropped, and a row whose code another relabel takes over is
relabelled when that completes a permutation. The rule finds 25 rows: Guyana (8 regions shuffled),
Eritrea (4), Afghanistan (Paktika and Paktya swapped, and Panjshir and Daykundi hidden under
Parwan and Uruzgan), Croatia (Požega-Slavonia hidden under Brod-Posavina), Ecuador (Napo and
Tungurahua swapped), and code-only fixes such as Bogotá (`CO-DC`). Slovenia's
Podčetrtek–Bistrica ob Sotli swap is a hand decision, because Slovenia's gB layer has no codes, and
so is Moscow: NE gives Moscow Oblast the city's code (`RU-MOW`) and the city the oblast's
(`RU-MOS`), but Wikidata's point for the oblast lies in the city, so the rule cannot see it.
Each relabelled graph lists what changed under `relabels`, with NE's original values.

## Edges

Every pair of units that comes within 2 km of each other, in NE or in gB, is measured. Three
sources each give a vote:

- **Natural Earth:** *yes* when the shared boundary is longer than **100 m**, measured
  geodesically on WGS84 after **clipping out NE lakes larger than 500 km²**. A point contact
  (the Four Corners) or a gap is *no*.
- **geoBoundaries** (gbOpen, the level that matches NE's units best): the length of gB border
  between the matching units, less the part lying over sea, less a 100 m allowance for
  generalisation. *Yes* from 500 m, *no* up to 100 m (*apart* when the units are also 1 km apart),
  *short* in between. gB abstains for a unit it does not identify (match quality under 0.8) and
  for a unit it draws as a different version of the unit (area off by more than half, or a
  shape overlap under 0.5). This is the case for 19% of NE's borders, mostly where gB uses
  newer units than NE.
- **Wikidata P47** ("shares border with", pinned snapshot): whether it lists the pair. P47
  includes maritime neighbours and is incomplete, so it only breaks ties between the two maps.

The rules, first match wins:

| rule | votes | result | edges |
|---|---|---|---|
| `hand` | a decisions.json entry | as decided | 32 |
| `ne_and_gb` | NE yes, gB yes | edge | 6,989 |
| `ne_uncheckable` | NE yes, gB abstains | edge, on NE's word | 1,688 |
| `ne_and_gb_none` | NE no, gB no or abstains | no edge | |
| `gb_and_p47` | NE no, gB yes, P47 yes: NE collapsed or lost a border | edge | 40 |
| `gb_and_p47_apart` | NE yes, gB apart, P47 no: a border only NE draws | no edge | |
| `ne_and_p47` | NE yes, gB no or short, P47 yes | edge | 16 |
| `ne_short` | NE yes, gB short, P47 no | edge, NE stands | 6 |
| `review` | anything else | NE stands, listed for review | 4 |

### Water

Borders along rivers count, and borders across estuaries, firths and sea do not. NE's 10m coastline
(its ocean layer) decides which water is sea. NE's own admin-1 borders never run over its ocean,
but gB often extends a boundary out into an estuary, so the part of gB's border over NE's ocean
or a lake over 500 km² is discounted before gB votes. As a result, Clare–Kerry (the Shannon
estuary) and Nunavut–Québec (the Hudson Bay islands) are not edges, while Kent–Thurrock and the
London boroughs facing each other along the Thames are. So are Cádiz–Huelva on the Guadalquivir,
pairs on the Mekong branches, and Flevoland with Gelderland, North Holland and Utrecht across the
border lakes, which are smaller than 500 km².

### Hand decisions

`pipeline/data/maps/decisions.json` holds the decisions no rule can make, each with its reason:
the two code swaps above and 35 edges.

- **Collapsed borders (25 edges added).** NE and usually gB reduce these to a point, at a four-way
  point or a short diagonal. Each was added on a Wikipedia neighbour list or another quote.
  Examples: Boyacá–Meta, Distrito Federal–Minas Gerais, Encamp–Ordino, and Barnsley–Derbyshire.
- **Rivers (4 edges).** Kent–Thurrock, Bexley–Havering, Bexley–Thurrock and Greenwich–Newham.
  v0.1 removed Kent–Thurrock as a water contact. Under the river rule it is a border.
- **Land borders the rules miss (3 edges).** Delaware owns land on the New Jersey shore at Finns
  Point (New Jersey v. Delaware, 1934). Mangrove Cay–South Andros and Istanbul–Kırklareli also stay.
- **Borders NE draws that are not there (3 removed).** La Massana–Sant Julià de Lòria and
  Nimba–Sinoe, which gB shows apart and Wikipedia's neighbour lists omit, and Nunavut–Ontario,
  which is shoreline where NE's ocean stops short of the coast.

## Corroboration

An edge lists the sources that support it: `natural_earth`, `geoboundaries`, `wikidata_p47`, and
`hand` with its reason. It is **corroborated** when a hand decision or at least two sources
support it. 1,158 of the 8,775 country edges rest on Natural Earth alone and are flagged
`corroborated: false`. This is stricter than v0.1, which counted looser geoBoundaries matches and
Wikipedia evidence that are not inputs of this pipeline.

That earlier evidence is kept as `prior_evidence`, which is information only and does not
count towards corroboration:

- `wikipedia`: a border sentence in the unit's article names the other unit, matched by script.
- `review`: a fact-checking agent's verbatim quote, machine-checked against the cited page.
- `wikidata_item`: P47 between the units' own Wikidata items, resolved from GeoNames, HASC and
  other identifiers.
- `geometry_enclave`: one unit lies inside the other.

Wikipedia is recorded as a URL only, because its text is CC BY-SA. 268 uncorroborated edges carry
such evidence.

## Disputed territories

NE's de facto assignment is kept unchanged:

- Crimea and Sevastopol (`UA-43`, `UA-40`) are on the Russia map.
- Kosovo is its own country.
- Taiwan is its own country.
- Western Sahara is its own world vertex under `natural_earth`.
- `un195` follows UN membership.

Users who need a different view should re-assign these vertices. Their codes make them easy to
find.
