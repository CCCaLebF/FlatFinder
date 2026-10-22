# Plan: geocoding resale-flat addresses into the coordinates CSV

This plan is for the agent that builds and runs the one-off geocoding tool. Read `PLAN.md` first, especially decision 6, §3.3 and §10. Then read `README.md` §3–4.

## 1. Why this exists

The resale dataset has no coordinates. Until flats have real coordinates, every location feature runs on town-centre placeholders: the Fit Score's proximity scores, the walking-distance sliders, nearest amenities, walking distance and the map pins. `PLAN.md` §10.4 lists this as the top-priority open item.

Decision 6 says **the app must not geocode**. The team supplies a CSV of coordinates instead, which `import_flat_coordinates` loads. This tool is how the team produces that CSV:
- **It is a separate management command** that a person runs once, offline.
- **It writes a CSV file, never the database.** Loading still goes through `import_flat_coordinates`, unchanged.
- **The running app never calls OneMap for flat locations.**

## 2. Facts already checked (15 Oct 2026)

**The data:**
- About **8,080 unique (block, street_name) pairs** fall in the current 12-month window.
- `ResaleFlat.block` and `ResaleFlat.street_name` are already upper-case, trimmed and single-spaced. `import_flat_coordinates` normalises CSV rows the same way when it matches them.
- Street names use HDB abbreviations: `AVE`, `ST`, `RD`, `JLN`, `BT`, `C'WEALTH`, `NTH`, `UPP` and others.

**The OneMap search API:**
- **Endpoint:** `GET https://www.onemap.gov.sg/api/common/elastic/search`, with parameters `searchVal`, `returnGeom=Y`, `getAddrDetails=Y` and `pageNum=1`.
- **Token:** not needed. Credentials aren't needed either.
- **Each result** has `BLK_NO`, `ROAD_NAME` (full words, e.g. `ANG MO KIO AVENUE 10`), `POSTAL`, `LATITUDE`, `LONGITUDE`, `BUILDING` and `SEARCHVAL`.
- **No match** returns `found: 0`.

**A trial of 5 addresses**, spaced 3 s apart, matched 4 exactly on block number:

| Query | Result |
|---|---|
| `406 ANG MO KIO AVE 10` | Matched: block 406, ANG MO KIO AVENUE 10, postal 560406 |
| `1G CANTONMENT RD` | Matched: block 1G, CANTONMENT ROAD |
| `55 JLN BAHAGIA` | Matched: block 55, JALAN BAHAGIA |
| `201 BT BATOK ST 21` | Matched: block 201, BUKIT BATOK STREET 21 |
| `10 C'WEALTH AVE` | **No match.** Abbreviations need expanding. |

**The rate limit:**
- About 4 calls within about 2 s returned **HTTP 429**. The limit reset within a minute.
- Calls 3 s apart were fine.
- The exact limit is unknown.

## 3. What to build

### 3.1 Gateway method

In `backend/core/integrations/onemap.py`, add a method to `OneMapSearchGateway`:

```python
def search_addresses(self, text: str) -> list[dict]:
    """Raw results (page 1) for an address search; [] when nothing matches."""
```

Build it on the existing `_call()`, so it gets the 5 s timeout and raises `OneMapError` on a timeout, network error or non-2xx response. `OneMapError.code` is `429` when rate-limited. Leave the existing `geocode()` method unchanged.

### 3.2 Management command `geocode_flat_addresses`

Put it in `backend/core/management/commands/geocode_flat_addresses.py`.

```
python manage.py geocode_flat_addresses [--out database/data/flat_coordinates.csv] [--rate 1.0]
                                        [--limit N] [--retry-unmatched]
```

**Input:** the distinct `(block, street_name)` pairs from `ResaleFlat`, sorted for a stable order. Don't read the raw CSV.

**Outputs.** Put them in `database/data/`, not `database/data/raw/`. `database/data/raw/` is git-ignored; `database/data/` is not, so the team can choose to commit the files.
- **`database/data/flat_coordinates.csv`**, with columns:
  - `block,street_name,latitude,longitude`: exactly what `import_flat_coordinates` needs
  - `postal,onemap_road_name,match_method,query`: for checking by hand; `import_flat_coordinates` ignores extra columns
- **`database/data/flat_coordinates_unmatched.csv`**, with columns `block,street_name,reason,candidates`. `candidates` holds up to 3 results, as `BLK_NO ROAD_NAME (POSTAL)` separated by ` | `.

**Matching, for each pair, in this order:**
1. **Raw query:** `"{block} {street_name}"`, exactly as stored.
2. **Accept a result only if `BLK_NO` equals `block`,** comparing upper-case, trimmed values.
3. **Then check the road:** expand the abbreviations in `street_name` (§3.3) and compare the result with `ROAD_NAME`.
   - If they're equal, accept with `match_method=exact`.
   - Otherwise, if exactly one result has the same block and a road that is similar enough (`difflib.SequenceMatcher` ratio ≥ 0.85), accept with `match_method=fuzzy`.
4. **If nothing was accepted,** query again with the expanded street name: `"{block} {expanded}"`. Apply the same rules, but record `match_method=expanded` or `expanded_fuzzy`.
5. **If there is still no match,** write the pair to the unmatched file with `reason` set to one of `no_results`, `block_mismatch`, `road_mismatch` or `ambiguous`.
6. **Validate every accepted coordinate.** It must fall inside `import_flat_coordinates.SG_BOUNDS`. If it's more than 6 km from the town centroid (`Town`), still accept it but add `far_from_town` to `match_method`, so someone can check it by hand.

**Pacing and failures:**
- **One request at a time.** Never run requests in parallel.
- **Pace:** at most `--rate` requests per second (default `1.0`).
- **On a 429 or a timeout,** wait 10 s, then 30 s, then 60 s, then 120 s. After the first 429, halve the rate for the rest of the run, but never go below 0.25 per second. After 5 failed retries in a row, stop cleanly with a message; the run can be resumed.

**Resuming:**
- **Write each row and flush it straight away.** If the run is stopped, nothing already looked up is lost.
- **On start,** read both output files and skip any pair already in either.
- **`--retry-unmatched`** tries the unmatched pairs again, removing each one from the unmatched file if it now succeeds.

**Progress:**
- Every 100 pairs, log the number done, the matched %, the current rate and an estimated finish time.
- At the end, print a summary: matched (by method), unmatched (by reason), how many were flagged `far_from_town`, and the elapsed time.

**Never** print or log `.env` values. The command doesn't need them.

### 3.3 Abbreviation table

Expand whole words only. A starting table:

| Abbrev. | Full | Abbrev. | Full | Abbrev. | Full |
|---|---|---|---|---|---|
| AVE | AVENUE | ST | STREET | RD | ROAD |
| DR | DRIVE | CRES | CRESCENT | CL | CLOSE |
| PL | PLACE | CTRL | CENTRAL | NTH | NORTH |
| STH | SOUTH | UPP | UPPER | LOR | LORONG |
| JLN | JALAN | BT | BUKIT | KG | KAMPONG |
| TG | TANJONG | C'WEALTH | COMMONWEALTH | TER | TERRACE |
| HTS | HEIGHTS | PK | PARK | GDNS | GARDENS |
| SQ | SQUARE | CTR | CENTRE | MKT | MARKET |

**Don't trust this table blindly.** Before the pilot:
1. List every word in the distinct street names that isn't a number.
2. Print the words that aren't in the table and aren't ordinary words.
3. Add any real abbreviations you find.

**Watch out for `ST`.** It usually means STREET, but `ST.` (or `ST` before a saint's name, as in `ST. GEORGE'S`) means SAINT. Check which street names actually contain it.

## 4. Tests

Add `tests/test_geocode.py`. Mock OneMap with `responses`, as `tests/test_onemap.py` does; **never call the real API in tests**. Cover:
- an exact match on the first query
- a miss on the raw query that succeeds with the expanded query (the `C'WEALTH` case)
- a result with the right road but the wrong block is **rejected**
- a fuzzy match: exactly one candidate, ratio ≥ 0.85
- two similar candidates are written to unmatched as `ambiguous`
- a 429 followed by success, with the backoff and the halved rate (patch `time.sleep` so the test runs fast)
- resuming: pairs already in either output file are not requested again
- `--retry-unmatched` moves a pair from the unmatched file to the output once it succeeds
- **the output CSV loads with `import_flat_coordinates`**, and the flats get `coords_approximate=False`
- an out-of-bounds coordinate is rejected, and a coordinate far from the town is flagged

All existing tests must still pass on SQLite and in Docker (`pytest`, `docker compose exec web pytest`).

## 5. Steps

1. **Build** §3 and §4. Run the full test suite.
2. **Pilot:** `python manage.py geocode_flat_addresses --limit 50 --out data/pilot_coordinates.csv`
   - **Stop and report to the user:** the match rate by method, every unmatched pair with its reason, any 429s, the request rate that worked, and a **projected time for the full run**.
   - **Wait for the user's go-ahead** before step 3.
3. **Full run, in the background** (expected 1–3 hours at about 1 request/s; about 7 hours if it has to slow to 1 every 3 s):
   - Docker: `docker compose exec web python manage.py geocode_flat_addresses`. The project folder is bind-mounted, so the output lands on the host.
   - Local: `python manage.py geocode_flat_addresses`
   - If it stops, run the same command again to resume.
4. **Review:**
   - Give the user the summary and the unmatched file.
   - Try `--retry-unmatched` once.
   - Leave the remaining misses for the user to fix by hand, by adding rows to `database/data/flat_coordinates.csv`.
   - Spot-check 10 random `exact` rows and every `far_from_town` row on the OneMap website.
5. **Load**, locally and in Docker:
   ```
   python manage.py import_flat_coordinates database/data/flat_coordinates.csv
   python manage.py compute_proximity
   ```
   Confirm in the browser:
   - the map shows one pin per block, not one per town
   - single flats show price tags
   - flats in the same town now have different distances and Fit Scores
6. **Update the docs:**
   - `PLAN.md` §10.4: tick the coordinates item and record the match rate and date.
   - `README.md` §4: add the `geocode_flat_addresses` command and how to resume it.
   - `PLAN.md` §10.2: note that the CSV was produced with this tool.

## 6. Rules

- **Don't make the app geocode at runtime,** and don't write coordinates into the database from this command. `import_flat_coordinates` stays the only way coordinates get in (decision 6).
- **Don't invent, jitter or guess coordinates.** A pair that can't be matched goes to the unmatched file.
- **Don't run the full job before the user approves the pilot.**
- **Don't send requests in parallel** or try to discover OneMap's limit by flooding it. This is the team's account.
- **Don't commit the output CSVs** until the user decides whether they belong in the repo.
- **Don't print secrets.** The command needs no credentials.

## 7. Decisions for the user, before the full run

1. **Commit the CSV?** If `database/data/flat_coordinates.csv` (about 400 KB) is committed, teammates load it directly and don't need to geocode. **Default: don't commit until the user says so.**
2. **Check an official dataset first?** data.gov.sg's "HDB Existing Building" footprints might give block locations with no API calls, if they link to street names; this hasn't been checked. If the user wants that, spend at most 15 minutes on it, report back, and continue with this plan only if it doesn't work out. **Default: go straight to this plan.**
3. **Geocode beyond the 12-month window?** Only needed if `import_flats` is later widened. **Default: current window only.** The tool's resume behaviour means a later run only looks up new addresses.

## 8. Done when

- [ ] The command and its tests are merged, and every test passes on SQLite and in Docker.
- [ ] The pilot was reported to the user and approved.
- [ ] `database/data/flat_coordinates.csv` covers at least 95% of pairs automatically, and the rest are listed in the unmatched file.
- [ ] Coordinates are loaded and `compute_proximity` has run, locally and in Docker.
- [ ] Checked in the browser: one pin per block, and different distances within a town.
- [ ] `PLAN.md` and `README.md` are updated.
