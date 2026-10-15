# FlatFinder: Cross-check of code, SRS and class diagram

**Date:** 15 Oct 2026. **Code state:** build phases 1–7 done (phase 8, polish and README, still to come).

**Compared against:**
- the SRS, `2006-SCSC-F4/Lab3/Lab2Updated.pdf`: all FRs, NFRs and UC-01 to UC-14
- the updated class diagram (Visual Paradigm image)
- the build plan, `PLAN.md`

The UI mockups (SRS pp. 22–24) were not checked here; that happens in phase 8.

## Summary

- Every FR and every use case has working code behind it.
- **The code has 3 gaps against the SRS** (§1). Two of them need decisions (§2).
- **Most mismatches with the class diagram are on the diagram's side** (§3).
  - It doesn't yet include the changes already approved in `PLAN.md` §8.
  - It contradicts the live OneMap API in three places. These were tested: search and map tiles need no token; routing does.
- **The SRS contradicts itself in a few places** (§4).

Tick items off as they're resolved.

---

## 1. Code gaps against the SRS (to fix in code)

- [ ] **C1: the side panel in Map View leaves out required fields.**
  - **Requirement:** FR 2.2.3 says recommended flats are listed on a side panel. FR 2.2.3.1 says each one is shown "in the same format", with all of FR 2.2.3.1.1–2.2.3.1.9.
  - **Problem:** the Results page's Map View side list uses compact cards, and they leave out **storey range**, **lease commence date** and **remaining lease**.
  - **Fix:** add the three fields to `partials/flat_card_compact.html`.
- [ ] **C2: the details page's Map View hides the flat's details.**
  - **Requirement:** UC-02's postconditions are (1) a details panel on the side panel, **and** (2) the map centred on the flat with its amenities plotted.
  - **Problem:** in Map View, the map replaces the "Flat details" section, so the user never sees both together.
  - **Fix:** keep a condensed details panel next to the map, above the Fit Score breakdown.
- [ ] **C3: no Fit Score when there's no search.** *Needs a decision* (see §2).
  - **Requirement:** FR 2.2.3.1.9 says the Fit Score is part of every flat's displayed details. UC-02's second entry point lets the user open a flat from a map pin without searching first.
  - **Problem:** with no search in the URL, the details page shows "Start a search" instead of a score.

## 2. Decisions needed

| # | Question | Options |
|---|---|---|
| C3 | What Fit Score should a flat show when the user hasn't searched? | **(a)** A baseline score from price and lease only, compared with all flats and clearly labelled. This meets FR 2.2.3.1.9. *(Recommended.)* **(b)** Keep "Start a search". Arguably more honest, but it doesn't meet the FR. |
| C4 | UC-08 step 1 asks for a "budget range **slider**". The app uses two number boxes (minimum and maximum). | **(a)** Switch to a two-handle range slider. **(b)** Keep the number boxes, which are more precise for SGD amounts, and change the SRS wording. |
| C5 | The SRS dataset references say the town-boundary file is used to "highlight areas and draw borders around" towns on the map. The app only uses it for town centres. | **(a)** Draw town borders on the map. Optional, since no FR requires it. **(b)** Drop the sentence from the SRS. |

---

## 3. Class diagram vs code (mostly diagram updates)

### 3.1 Approved changes not yet in the diagram

`PLAN.md` §8 lists these as approved. The code follows them; the diagram doesn't yet.

- [ ] Add `Town` (entity): `name`, `centroid_lat`, `centroid_lng`. It's used for the per-town flat counts on the map (FR 2.1.1).
- [ ] Add `FlatProximity` (entity, one-to-one with `ResaleFlat`). It holds the pre-computed straight-line distance from each flat to the nearest bus stop, MRT station, child care centre, hawker centre and CHAS clinic.
- [ ] Add `DistanceStrategy` (interface), with `StraightLineDistance` and `WalkingDistance` as its two implementations (generalisation arrows).
- [ ] Add `DataLoader` (control): the start-up import of the data.gov.sg datasets.
- [ ] `SearchQuery`:
  - replace `amenityWeights: Map<AmenityType, int>` with five separate weights: `busStopWeight`, `mrtStationWeight`, `childCareCentreWeight`, `hawkerCentreWeight`, `chasClinicWeight` (int; empty means ignored)
  - add `anchorLabel: String` and `anchorWeight: int`
- [ ] `FitScore`: add `anchorScore: float`.
- [ ] `Bookmark`: rename `user_id` to `session_id`. The diagram's own `BookmarkController` already uses `session_id`.
- [ ] `MapController`: remove the rendering methods (`RenderMap`, `DropLocationPins`, `PanZoom`, `ToggleLayer`, `RestoreLastMapState`). That work belongs to `MapUI`. In the code, `MapController` has `getAreaCounts(query)` and `getPinsInView(bounds, query, limit)`.

### 3.2 Where the diagram contradicts the real OneMap API

Tested against the live API on 15 Oct 2026.

| Class | In the diagram | Actual OneMap behaviour | Change the diagram to |
|---|---|---|---|
| `MapGateway` | `-token`, `-refreshToken()` | Map tiles load **without** a token | Remove `token` and `refreshToken`. Keep `baseUrl` and `getTileUrl`. |
| `OneMapSearchGateway` | `-token`, `-refreshToken()` | Search works **without** a token | Remove `token` and `refreshToken`. `geocode(query)` returns `(lat, lng, label)` or nothing. |
| `OneMapRoutingGateway` | Empty | The **only** endpoint that needs a token (a 401 without one). Tokens last 3 days. | Add `walkingRoute(origin, destination)`, which returns metres and seconds, and the token handling. |

- [ ] Optionally add `OneMapTokenProvider`, the shared token helper that gets, caches and refreshes tokens, and `OneMapError`, the failure that `ErrorHandler` handles.

### 3.3 Layering problems (control classes doing display work)

In the BCE layering, control classes shouldn't display anything; that's the boundary's job.

- [ ] **`ErrorHandler`:**
  - `DisplayErrorMessage` duplicates `MapUI.displayErrorMessage`; remove it from `ErrorHandler`.
  - `PreserveLastMapState` happens in the browser, through `MapUI` and `MapState`.
  - `-errorLog`: failures are written to the server log, not kept in a list.
  - The code's methods are `logError(endpoint, timestamp, code)` and `toResponse(error)`. `toResponse` turns a OneMap failure into the "OneMap service currently unavailable" message (HTTP 502).
- [ ] **`AmenityController`:**
  - `DisplayNearestAmenities()` is boundary work; `FlatDetailsUI` and `MapUI` do it.
  - The five `Fetch*()` methods are one method in the code: `findNearestAmenities(flat, radiusM): Map<category, List<Amenity>>`. It searches our database within 1 km and lists each MRT station once (its nearest exit).
- [ ] **`MapState`:**
  - It's stored in the browser, so only `MapUI` can read or write it. Replace the `MapController <<write>> MapState` and `ErrorHandler <<read>> MapState` arrows with `MapUI <<write>>/<<read>> MapState`.
  - Rename `visiblePins` to `visibleLayers`, and add `viewMode` (list or map).

### 3.4 Signatures and attributes that differ

- [ ] `SearchController`:
  - `calculateFitScore(flat, query, bounds): FitScore` returns the whole breakdown, not a float.
  - `filterFlats(query)` returns the matching flats.
  - Add `applyWalkLimits(flats, query)`. It is the provisional walking-distance filter, an open decision for FR 1.1.3.
  - Add `boundsFor(query)`. It gives the price and lease thresholds, so a single flat's score matches the results list.
  - `rankFlats(flats, query): SearchResult`.
  - `sortResults(result, order: SortOrder)` takes a `SortOrder` instead of two strings.
  - `setProximityAnchor(query, text): boolean` returns false when there's no match (UC-07.EX.2).
- [ ] `SearchQuery.setAnchor(location: Location)`: `Location` isn't defined anywhere in the diagram. Either define it or use `setAnchor(lat, lng, label)`, as the code does. Also, `minRemainingLease` is a float in the code (decimal years).
- [ ] `SearchResult`:
  - in the code it holds `flatIds` (in display order), `fitScores` (a FitScore for each flat id), `sortOrder` and `bounds`
  - add `count` and `isEmpty`
  - this still fits the existing associations (1 to many with `ResaleFlat` and with `FitScore`, 1 to 1 with `SortOrder`)
- [ ] `StraightLineDistance`: `EstimateDistance(flat, amenity)` and `EstimateAmenityDistances(flat)` are `distanceM(origin, target)` and `nearestM(origins, targets)` in the code. The second one bulk-computes the nearest distances for the `FlatProximity` import.
- [ ] `WalkingDistance`: `CalculateWalkingDistance(flat, amenity)` and `QueryOneMapRouting(origin, destination)` are `distanceM(origin, target)` and `route(origin, target)` in the code.
- [ ] `ResaleFlat`:
  - rename `floor_area` → `floor_area_sqm`, `lease_commencement_date` → `lease_commence_date`, `flat_id` → `id`
  - add `town` (needed for FR 2.1.1), `month`, `flat_model`, `remaining_lease_raw` (the dataset's original text) and `coords_approximate`
- [ ] Add `BusStop.stop_code` and `MrtStation.exit_code`. There's one `MrtStation` row per station exit.
- [ ] Fix the typo `SearchUI.sumbitSearchBar` → `submitSearchBar`.
- [ ] Use one naming style for methods throughout. The control classes use PascalCase (`ToggleBookmark`); everything else uses camelCase.
- [ ] Optional helper classes: `ScoreBounds` (price and lease thresholds) and `NearbyAmenity` (an amenity plus its distance from the flat).

### 3.5 Code changes that make the code match the diagram more closely

- [ ] **C6:** `SearchController` calculates the search-location (anchor) distance with its own haversine function. Route it through `StraightLineDistance` instead, to match the diagram's `SearchController <<use>> StraightLineDistance` and remove the duplicate formula.
- [ ] **C7:** rename the functions in `static/core/js/map.js` to the diagram's `MapUI` method names, so each one is easy to find:
  - `displayMap`, `displayAreaCounts`, `displayFlatPins`, `displayBookmarkPins`, `displayAmenityPins`
  - `selectFlatPin`, `selectAmenityPin`, `displayWalkingDistance`, `toggleLayer`
  - `displayErrorMessage`, `displayBlankMap`

  The behaviour already exists; only the names change.

---

## 4. Problems in the SRS (for the team)

- [ ] **FR 1.1.4** says importance weights run from 1 to 5. The data dictionary (User, Search Query, Fit Score) says 1 to 10, and the app uses 1 to 10 (`PLAN.md` decision 1).
- [ ] **"Schools" / "pre-schools"** should read **Child Care Centres** in the mission statement, UC-01 step 2, UC-09 step 1, UC-11 step 2, UC-12 step 1 and FR 2.3.3.
- [ ] **CHAS Clinics are missing** from the weight lists in UC-01 step 2 and UC-09 step 1.
- [ ] **UC-11** still says amenities come from the OneMap API. They come from our own database, imported from data.gov.sg (`PLAN.md` decision 5). So UC-11.EX.1 no longer applies, and UC-06 doesn't extend UC-11.
- [ ] **The 12-month data window** (`PLAN.md` decision 7) isn't stated anywhere.
- [ ] **FR 1.1.x numbering is garbled** in the PDF: "1.1.5" sits on the wrong line and "1.1.6" is empty. The code uses:
  - **FR 1.1.4**: importance weights
  - **FR 1.1.5**: minimum remaining lease
  - **FR 1.1.6**: a blank criterion means no limit
  - **FR 1.1.7**: search-bar location (anchor)

  Please confirm, and fix the PDF.
- [ ] **UC-09 step 1** cites FR 1.1.3 (walking distances) for the importance weights; it should cite FR 1.1.4.
- [ ] **The dataset references** cite "FR3.2" (MRT) and "FR3.3" (bus stops), which don't exist. They should probably be FR 2.3.2 and FR 2.3.1.
- [ ] **UC-08 step 1:** "budget range slider" (see C4).

---

## 5. Requirement coverage

| Requirement | Status | Where |
|---|---|---|
| FR 1.1.1 Budget | ✅ (two number boxes, see C4) | Sidebar |
| FR 1.1.2 Flat types | ✅ | Sidebar chips |
| FR 1.1.3 Walking-distance sliders | ✅ provisional | `apply_walk_limits`: open decision (`PLAN.md` decision 3) |
| FR 1.1.4 Importance weights | ✅ uses 1–10 | Sidebar sliders with "Ignore" |
| FR 1.1.5 Minimum lease | ✅ | Sidebar |
| FR 1.1.6 Blank means no limit | ✅ | Thresholds come from the matching flats |
| FR 1.1.7 Search-bar location | ✅ | Results page search bar, plus a "Near location" slider |
| FR 1.2 / 1.2.1 Walking distance via OneMap | ✅ | Amenity pin popup |
| FR 1.2.1.1 Error message | ✅ | Dismissible banner |
| FR 1.2.1.2 Keep the last map state | ✅ | `MapState`; returns to the last view whose tiles loaded |
| FR 2.1 Pan and zoom | ✅ | Leaflet map with OneMap tiles |
| FR 2.1.1 Counts per area | ✅ | Town counts below zoom 14 |
| FR 2.1.2 Flats when zoomed in | ✅ | Pins from zoom 14 |
| FR 2.2.1 Flats as pins | ✅ | |
| FR 2.2.2 / 2.2.2.1 Fit Score, weighted | ✅ | `PLAN.md` §4 formula |
| FR 2.2.3 Side panel | ⚠️ C1 | Map View side list is missing fields |
| FR 2.2.3.1.1–2.2.3.1.9 Flat fields | ⚠️ C1, C3 | List View complete |
| FR 2.2.3.2 Default order | ✅ | Fit Score, highest first |
| FR 2.2.3.3 Re-sort | ✅ | "Sort by" dropdown |
| FR 2.2.4.1 / 2.2.4.2 Bookmarks | ✅ | Bookmark icon, Saved page and counter |
| FR 2.3 / 2.3.1–2.3.5 Amenities within 1 km | ✅ | Details page, list and map |
| FR 2.3.6 Layer toggles | ✅ | No new request when toggling |
| NFR 1: results within 5 s | ✅ | About 0.23 s for all 24k flats; covered by a test |
| NFR 2.1: error message when OneMap fails | ✅ | The app doesn't call data.gov.sg while running; datasets are imported in advance |
| NFR 2.2: no-results prompt | ✅ | "Adjust your requirements" |
| NFR 3.1: first-time users finish in 2 minutes | ⬜ | Needs user testing, not code |
| NFR 3.2: controls fit without scrolling at 1366×768 | ✅ | Recheck in phase 8 |
| NFR 4: no personal information | ✅ | No accounts; the OneMap login stays on the server |

| Use case | Status | Notes |
|---|---|---|
| UC-01 Search | ✅ | |
| UC-02 View Flat Details | ⚠️ C2, C3 | Both entry points work |
| UC-03 Display Map (incl. AC.1 saved-flat pins) | ✅ | |
| UC-04 Walking Distance | ✅ | Cached; only to points within 1.5 km of the flat |
| UC-05 Bookmark | ✅ | From the results, details and Saved pages |
| UC-06 Handle API Failure | ✅ | Logged with endpoint, time and code |
| UC-07 Search Bar (incl. EX.1, EX.2) | ✅ | |
| UC-08 Filter | ✅ | See C4 |
| UC-09 Rank | ✅ | Uses straight-line distances stored in the database |
| UC-10 Sort | ✅ | |
| UC-11 Nearest Amenity | ✅ | From the database, not OneMap (see §4) |
| UC-12 Toggle Layers | ✅ | |
| UC-13 Last Map State (incl. EX.1 blank map) | ✅ | |
| UC-14 Saved Flats (incl. AC.1 empty state) | ✅ | List and map |
