# Singapore HDB Estate Database

A block-level database of every residential HDB block in Singapore, joined from three
official sources, plus a local HTML report.

## Quick start

```bash
python3 serve.py            # -> http://127.0.0.1:8642/
python3 serve.py -p 9000    # pick a different port
```

## Contents

| File | What it is |
|---|---|
| `data/hdb.sqlite` | SQLite database — `blocks` (one row per block) and `estates` (one row per HDB town) |
| `data/hdb_blocks.csv` | Block-level table, CSV |
| `data/hdb_estates.csv` | Estate-level rollup, CSV |
| `data/hdb_blocks.json` | Block-level table, JSON |
| `site/index.html` | The report — self-contained except for Mapbox basemap tiles |
| `site/vendor/` | Mapbox GL JS 3.25.0, vendored so the page needs no CDN |
| `site/config.js` | Generated: Mapbox token + style URLs (git-ignored) |
| `site/rail.geojson` | MRT/LRT line geometry from OpenStreetMap |
| `site/stations.geojson` | 212 MRT/LRT stations, with codes, interchange and build status |
| `site/data.json` | Dictionary-encoded payload the report loads |

## Sources

| Source | Publisher | Supplies |
|---|---|---|
| HDB Property Information (`d_17f5382f26140b1fdae0ba2ef6239d2f`) | HDB via data.gov.sg | blocks, dwelling units, flat-type mix, year completed |
| OneMap Search API | Singapore Land Authority | latitude / longitude / postal code per block |
| Master Plan 2019 Planning Area Boundary (`d_4765db0e87b9c86336792efe8a1f7a66`) | URA via data.gov.sg | planning area + region polygons |
| OpenStreetMap (Overpass API) | OSM contributors, ODbL | MRT/LRT line geometry for the map overlay |

## Pipeline

```
geocode.py     block + street -> OneMap -> data/geocode_cache.jsonl   (resumable)
build_db.py    CSV + geocodes + point-in-polygon -> sqlite / csv / json
build_site.py  -> site/data.json + site/config.js
fetch_rail.py  Overpass -> site/rail.geojson            (cached; run once)
validate.py    QA the assembled database
serve.py       -> http://127.0.0.1:<port>/
```

Rebuild everything after a source refresh:

```bash
python3 geocode.py && python3 build_db.py && python3 build_site.py
```

### Project names and listing links

OneMap returns a `BUILDING` name for many blocks — the HDB project name ("Casa Clementi",
"Bishan Ridges"). It sits inside the `ADDRESS` string between the road name and the postal
code, so `build_db.py` recovers it without re-geocoding. Two traps:

- OneMap sometimes returns a **co-located facility** instead of the project — childcare
  centres, police posts, "HDB Public Shelters" (54 blocks). Those are filtered out by pattern.
- **"Depot Heights" is a real Telok Blangah estate**, so `DEPOT` must never go in that
  filter pattern. It was the one false positive when the filter was first written.

Clicking a block opens a bubble with the project name and three PropertyGuru searches —
block, project, street — narrowest to broadest, because a single block often has no live
listing. The URL scheme, verified September 2026:

```
https://www.propertyguru.com.sg/property-for-sale?freetext=<query>&property_type=H
    &property_type_code[]=4A&property_type_code[]=4NG...
```

Returns `HDB 4 Room Flats for Sale - <location>`. The older `/singapore-property-listing/`
path now 403s. `PG_BASE` and `PG_CODES` in `index.html` are the only things to change if
PropertyGuru alters the scheme.

### Flat-type filter

Selecting a flat type filters to blocks containing that type **and** switches every count in
the report — tiles, map dot size, charts, estate table, block table — to that type's units,
so the whole page describes the stock the filter names. It also flows into the PropertyGuru
links as `property_type_code[]`.

### Rail overlay

`fetch_rail.py` pulls MRT/LRT route relations from OpenStreetMap and writes
`site/rail.geojson`, drawn under the block dots in the operators' own line colours
(identity colours riders already know, so deliberately not from the report's data palette).
Lines under construction are dashed. The raw Overpass response is cached in
`data/overpass_rail.json` — delete it to refetch.

**Stations** (212, of which 34 are interchanges and 24 still under construction) are drawn
as hollow marks — a surface-coloured centre with a line-coloured ring — so they never read as
data points. Interchanges are larger with a neutral ring, since no single line owns them.
They sit *above* the block dots: judging which blocks are near a station is the point of the
overlay, and under a dense cluster they would simply disappear. Names appear from zoom 12.5.

Stations are filtered by Singapore station-code pattern (`NS12`, `EW24`, `BP6`…), which
cleanly excludes the Sentosa Express, the Changi Skytrain and the KTM stations that the
bounding box also returns. Note the query uses a **bounding box, not `area["ISO3166-1"="SG"]`** —
the area lookup reliably times out on Overpass's dispatcher.

Two further OSM quirks the script handles, both of which silently lose data if ignored:
the Bukit Panjang and Punggol LRT are tagged `route=monorail`, not `light_rail`, so querying
light rail alone drops two of the three LRT networks; and the same query also returns the
Sentosa Express and the Changi Skytrain, which are filtered out.

### Estate names

The 27 HDB estate names are drawn as their own Mapbox symbol layer, positioned at the
**median** lat/lon of each estate's blocks — not the mean, which an outlying pocket of blocks
would drag into empty space. Larger estates win label collisions (`symbol-sort-key` on unit
count), so at full extent 24 of 27 show and the rest appear as you zoom.

While estate names are on, two basemap layers are switched off to avoid printing two sets of
names over each other: `settlement-subdivision-label` (which already labels Yishun, Bedok,
Tampines…) and `airport-label` (which prints air-base codes — WSAG, TGA, QPG — that mean
nothing in a housing report). Turning the toggle off restores both.

### Basemap

The map draws the blocks as a Mapbox GL circle layer over Mapbox Light / Dark, switched with
the report's theme. The token is read at build time from `MAPBOX_TOKEN` or `.mapbox_token`
and written to the git-ignored `site/config.js`, so it is never baked into source:

```bash
echo 'pk.your_token' > .mapbox_token && python3 build_site.py
```

A Mapbox public (`pk.`) token is necessarily visible to the browser — that is what it is for —
so restrict it by URL in your Mapbox account if the report is ever exposed beyond localhost.
**Without a token, or offline, the map falls back to a dependency-free SVG scatter** of the same
coordinates; nothing else in the report changes.

The ordinal colour ramp is reversed in dark mode on purpose. On a dark ground the *bright* end
reads as the loud one, so reversing keeps the newest estates the salient end in both themes
rather than flipping emphasis to the oldest.

`geocode.py` is resumable — it appends to `data/geocode_cache.jsonl` and skips anything
already cached, so it is safe to interrupt and restart. It paces itself against OneMap's
rate limit (adaptive: it widens the request interval on HTTP 429 and decays back down).
Set `ONEMAP_TOKEN` to use an authenticated quota, which raises the ceiling.

## Schema — `blocks`

| Column | Notes |
|---|---|
| `blk_no`, `street`, `address`, `postal` | address; `address`/`postal` come from OneMap |
| `project` | HDB project/precinct name ("Bishan Ridges") where OneMap has one — 49.9% of blocks |
| `town_code`, `town` | HDB's own estate code and name (e.g. `TAP` / Tampines) |
| `planning_area`, `region` | **URA** planning area and region, by point-in-polygon |
| `lat`, `lon`, `geocode_match` | coordinates; match is `exact` (block + road), `block`, `fuzzy`, or `missing` |
| `top_year` | year of completion, as published by HDB |
| `mop_year_est`, `mop_status` | **estimated** — see caveats |
| `age_years`, `lease_remaining_est` | derived from `top_year` |
| `max_floor_lvl`, `total_units` | height and dwelling units |
| `units_1r` … `units_exec`, `units_multigen`, `units_studio`, `units_rental` | flat-type mix |
| `has_commercial`, `has_market_hawker`, `has_mscp`, `has_pavilion` | non-residential facilities in the block |

## Caveats — read before using the derived columns

- **MOP is an estimate.** The Minimum Occupation Period runs 5 years from key collection,
  which HDB does not publish per block. `mop_year_est` uses `top_year + 5` as a proxy, so it
  can be out by a year either way. Prime and Plus flats (from 2024) carry a **10-year** MOP
  and are not separately flagged in the source data.
- **Lease remaining is approximate.** `99 - (current year - top_year)`. The 99-year lease
  commences shortly *before* completion, so this reads slightly low.
- **HDB town ≠ URA planning area.** They are different administrative geographies and the
  report carries both. HDB's "Central Area" spreads across URA's Outram, Rochor, Kallang and
  Downtown Core; URA's "Tampines" does not exactly match HDB's Tampines town.
- **`year_completed` is the block's TOP, not the estate's.** Estates are built in phases, so
  an estate's TOP range spans decades (Tampines: 1981–2026).
- **Residential blocks only.** The source lists 13,357 blocks; the 10,796 with
  `residential = Y` are kept. The rest are standalone carparks, markets and commercial blocks.
- **`total_units` includes rental flats; the `units_*` type columns do not.** HDB's flat-type
  columns count *sold* flats only, so `sold + rental = total`. Across the stock that is
  1,110,981 sold + 64,975 rental = 1,175,956. Summing the type columns alone undercounts by 5.5%.
- Counts are **dwelling units sold**, HDB's own field. Blocks under construction appear with
  their planned unit counts.
