# Known issues (v0.2)

## 1,158 edges on Natural Earth alone

These edges exist in Natural Earth's geometry, but neither geoBoundaries nor Wikidata P47 confirms
them. They are flagged `corroborated: false`, and 268 of them carry `prior_evidence` from the v0.1
review (see METHODOLOGY.md). Almost all are in countries where geoBoundaries uses newer or
different units from NE, so it cannot vote:

- the United Kingdom: 199
- Uganda: 141
- North Macedonia: 137
- Slovenia: 88
- Azerbaijan: 86
- Malta: 84
- the Philippines: 67
- Seychelles: 37
- Hungary: 34
- Kosovo: 32
- Hong Kong: 31

The flag means one source, not a likely error. The edges most likely to be wrong are crossings of
small bays that NE's coastline counts as inland, and slivers where NE polygons overlap slightly.

## Open review pairs

No rule settles these 34 pairs, so Natural Earth's answer stands until a hand decision settles
them. They are listed with their measurements in `pipeline/data/audit/review.csv`.

- **geoBoundaries borders between units NE keeps apart** (25 pairs, 1–190 km of gB border, no
  Wikidata P47). Most are places where gB's units are a different version from NE's, or do not
  line up with them: Buenos Aires–Corrientes, Red Sea–New Valley, Andhra Pradesh–Chhattisgarh
  (gB's India layer predates Telangana), Argyll and Bute against four Clyde councils, five Ugandan
  pairs and pairs in Côte d'Ivoire, Algeria, Guinea, Iran and Burkina Faso. A few are short
  contacts: Edinburgh–East Lothian, Oxfordshire–Wiltshire, Bilecik–Kocaeli, Maribor–Starše.
- **NE point contacts that gB reads as a short border:** Thessaly–Western Greece,
  Glogovac–Klina, Kumi–Bulambuli, Gorenja vas-Poljane–Idrija, and two Latvian pairs.
- **NE borders that gB reads as a point** (kept as edges): Gabrovo–Plovdiv (1.1 km in NE),
  Amata–Ērgļi, Drugovo–Struga and Morogoro–Manyara (27 km in NE, so probably a gB vintage
  difference).
- **Waterford–Wexford:** 1.4 km of gB border remains up the River Barrow once Waterford Harbour is
  discounted. It is not an edge in NE.

## Changes from v0.1

All are listed in `pipeline/data/audit/diff_previous.csv`.

- **28 vertices relabelled:** 26 by the label rule, including three regions that were hidden under
  a neighbour's code and are now their own vertices (Afghanistan's Panjshir and Daykundi, Croatia's
  Požega-Slavonia), and Moscow's swapped city and oblast codes by hand.
- **32 edges added**, mostly borders NE collapsed to a point that geoBoundaries and Wikidata both
  have, and river borders.
- **27 edges removed**, mostly borders only NE draws (geoBoundaries shows the units apart and
  Wikidata does not list them), estuary crossings, and the hand removals.
- **Kent–Thurrock is an edge again.** It runs along the Thames, which NE's coastline counts as
  river at that point.
- **Corroboration is stricter**, so the number of uncorroborated edges rose from 314 to 1,158.

## Other limits

- **Code vintage.** Codes and units are Natural Earth v5.1.1's. Norway (2020), Latvia (2021) and
  Iran (2020 renumbering) have since changed their subdivisions, and 29 countries have fewer than
  half their codes in the current ISO 3166-2.
- **Mixed levels.** Some countries mix levels as Natural Earth does. Bosnia and Herzegovina has
  Federation cantons beside Republika Srpska regions. Several capitals are separate city
  vertices inside their province.
- **World graphs** are carried over from v0.1 and were not rebuilt by the v0.2 pipeline.
- **Disputed territories** follow Natural Earth (see METHODOLOGY.md).
