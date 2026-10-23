# FlatFinder — Proposed Change Plan (for approval)

> **Status:** Complete — Phases A2, B, C, D, E, F, G and H all implemented and live-checked.
> **Source of requirements:** `Lab3/CompleteUseCaseModel.pdf` (UC-01 … UC-14), `Lab3/Lab 3 Manual.pdf`, `Lab3/Lab3_3.3_AI_Project_Initialisation_Report.pdf`, plus the current codebase (post commit `d328755`).
> **Scope:** 11 original requested changes + 1 new compare feature = 12 changes. Change 1 was withdrawn (UC-08 stays as part of UC-01); Phase H is the compare feature.

---

## 0. Confirmed decisions (from the open questions)

1. **No separate block page.** Block and single-flat cards both open the flat details page, which becomes block-level when opened from Results (shared block fields once, then a read-only `(flat_type, storey_range)` table). Saved/direct links keep the single-flat details page.
2. **Past-transaction filters default to the UC-01 values but stay editable.** Users can narrow the transaction list without changing the main search.
3. **Walking path = polyline + distance/time only.** No turn-by-turn instructions.
4. **House illustration follows the brand green palette**, drawn as an inline SVG.
5. **Compare can mix results and saved flats, or saved flats alone.** Candidates are picked into a session tray from Results (a block → its best-ranked flat) and/or Saved. With a search, the tray can hold a block and saved flats together; with no search, saved flats compare directly and the user sets the weights.
6. **Comparison uses its own adjustable weight model, not the Fit Score.** Users can set/ignore an importance (0–10) for price, remaining lease, floor area, each amenity, and the search location. A block is still represented by its best-ranked matching flat; the compare page declares a winner with a plain-language "why".

---

## 1. Guiding principles

- Keep the existing 3-tier layout (boundary / control / entity) and Django monolith.
- Reuse existing services (`SearchController`, `MapController`, `AmenityController`) instead of duplicating logic.
- All search state stays in the URL (PLAN §6); bookmark state stays in the session.
- OneMap routing already returns `route_geometry` (encoded polyline) — only the gateway, API and front-end need wiring for point 6.
- No DB schema changes are anticipated; any that become necessary will be called out per change.

---

## 2. Implementation order at a glance

| Phase | Original change | Summary | Risk | Depends on |
|---|---|---|---|---|
| **A** | 10 | Verify/complete UC-07 search bar (sidebar, both views; centre map on anchor) | Low | — |
| **B** | 7 | Make the whole block card clickable | Low | — |
| **B** | 11 | Cartoon house drawing per block in list view | Low | — |
| **C** | 2 + 3 | Hide the older pin under the "Show on map"/saved teardrop; fix its format | Medium | — |
| **D** | 5 | Move amenity toggles to the top of the map | Low | — |
| **D** | 4 | Remove empty space at the bottom of the details page | Low–Med | — |
| **E** | 6 | Draw the OneMap walking path on amenity selection | Medium | C (map.js focus work) |
| **F** | 8 | Remove "View flats"; consolidate flats per block in one panel | High | B (card clickability) |
| **G** | 9 | Past transactions + filters + 7 per page | Medium | F (layout) |
| **H** | new | Compare 2–3 blocks/flats side-by-side with Fit Score breakdowns | Medium | B, F |

**Why this order**
- **Phase A** was the low-risk start: A1 is withdrawn, and A2 (sidebar search bar + map centring) is implemented.
- **Phase B** is independent, purely presentational, and point 7 is a prerequisite for point 8.
- **Phase C** groups the two pin-overlap fixes because they share the same `map.js` focus refactor; doing them together avoids touching the same code twice.
- **Phase D** is layout-only and can be verified in the browser quickly.
- **Phase E** reuses the pin-selection plumbing from Phase C, so it lands naturally after it.
- **Phase F** is the largest change and depends on point 7's card-click behaviour.
- **Phase G** extends the consolidated panel built in Phase F.
- **Phase H** is the new compare feature. It touches the result cards, so it is scheduled after Phase F so the consolidated block card is only edited once.

---

## Phase A — Low-risk cleanup and verification

### A1. Ignore UC-08 — **withdrawn**

UC-08 stays: UC-01 includes UC-08, so keeping it as a separate use case is correct. The earlier comment/doc cleanup has been reverted.

### A2. Implement/verify UC-07 Search via Search Bar — original change 10

**Goal:** Full UC-07 behaviour: geocode a postal code/place name via OneMap, set it as a proximity anchor, re-rank results; handle no-match and API failure.

**Current state:** Already implemented in `apply_search_bar()` (`views/search.py`), `SearchForm` anchor fields, `search_bar.html`, and `SearchController.set_proximity_anchor`. The search bar now sits at the top of the sidebar, so it is available in List View and Map View on both Start and Results. The anchor chip reads its state from the URL, so it works on every page with the sidebar.

**Tasks:**
- Verify each UC-07 flow against the code:
  - Match → `anchor_lat` / `anchor_lng` / `anchor_label` (+ `w_anchor`) set, redirect without `q`. ✅
  - No match → warning message (UC-07.EX.2). ✅
  - API failure → error banner, results still load (UC-07.EX.1 → UC-06). ✅
- Render `partials/search_bar.html` at the top of `partials/sidebar.html` (both views) and remove the old page-specific copies.
- Centre the browse map on the anchor in `map.js` when the URL carries `anchor_lat` / `anchor_lng` (at least at pin zoom), so a location search immediately shows the searched area.
- Add tests for the sidebar search bar in both views.

**Affected files:** `frontend/templates/partials/sidebar.html`, `partials/search_bar.html`, `results.html`, `start.html`, `frontend/static/js/map.js`, tests.
**Risk:** Low. **Tests:** extend UC-07 tests.

---

## Phase B — Card presentation

### B1. Make the whole block card clickable — original change 7 (implemented)

**Goal:** In search results, "Show on map" stays unchanged, but clicking anywhere else on the card behaves like clicking the block's address (opens the block details).

**Current state:** `block_card.html` / `block_card_compact.html` already use an overlay link (`after:absolute after:inset-0`) that covers the whole card. It currently sits above the "Show on map" button, so the button can be hard to click.

**Tasks:**
- Give "Show on map" (and any other action links) a higher stacking context (`relative z-10`) and correct pointer-events so they remain clickable above the overlay.
- Keep keyboard accessibility: the overlay link and buttons stay focusable.
- Apply the same pattern to flat cards where the whole card should open the flat details.

**Affected files:** `frontend/templates/partials/block_card.html`, `block_card_compact.html`, `flat_card.html`, `flat_card_compact.html`, `frontend/static/css/map.css`.
**Risk:** Low. **Tests:** manual click test; no server change.

### B2. Cartoon house drawing per block — original change 11 (implemented)

**Goal:** In the list view, every result card — a multi-flat block card or a single-flat card — shows the same simple cartoonish house drawing with the block's address on it.

**Tasks (implemented):**
- Add a shared `partials/house_banner.html` with an inline SVG house (roof, body, door, window) in the brand green palette.
- Include it from both `block_card.html` and `flat_card.html`, so a block with one matching flat no longer looks different; the compact map-view cards stay text-only for space.
- Overlay the address with smart length handling:
  - Short address → single centred line.
  - Long address → two-line clamp/ellipsis with the full address in a `title` tooltip.
- Keep the layout stable (fixed SVG aspect ratio, no external images). Phase F can reuse the same partial in the consolidated block view.

**Affected files:** `frontend/templates/partials/house_banner.html` (new), `block_card.html`, `flat_card.html`.
**Risk:** Low (presentational). **Tests:** `data-block-house` assertions in `tests/test_blocks.py` plus a browser check.

---

## Phase C — Map pin focus fixes

### C1. "Show on map" teardrop overlaps the older pin — original change 2 (implemented)

**Goal:** Hide the existing pin at the selected location instead of drawing the teardrop on top of it. Fix the focus pin's info to match the rest (flat type, price, storey range).

**Current state (implemented):** A shared `createFocusController(adapter)` in `map.js` owns the highlighted pin, hides the matching pin(s) through an adapter, and restores them on map click / popup close. The browse adapter tracks matching pins by location and saved pins by flat id; `displayFlatPins()` and `displayBookmarkPins()` call `focus.refresh()` after every redraw, so the pin stays hidden across pan/zoom. Clicking the focused pin itself does not count as a map click; the popup close button or a click elsewhere clears it. The popup now reads `flatType · S$price · storey range` for a flat and `N matching flats · types · S$price range · storey range` for a block.

**Tasks (implemented):**
- Find the marker in `pinMarkers` matching `lat,lng` and remove it from `pinLayer`; keep the key so it can be restored.
- Restore hidden pins when a new focus is set or when clicking elsewhere (map click / popup close).
- Re-apply the hide after `displayFlatPins()` runs on pan/zoom if a focus is still active.
- Add `data-storey` to the "Show on map" buttons; block cards get every distinct storey range from `_card`'s `storey_ranges`.
- Keep `zIndexOffset: 1000` on the focus marker.

**Affected files:** `frontend/static/js/map.js`, `partials/flat_card_compact.html`, `partials/block_card_compact.html`, `backend/core/views/search.py`, `static/css/map.css`.
**Risk:** Medium (restoration across map reloads). **Tests:** data-attribute assertions in `tests/test_blocks.py`; browser checks for focus, redraw, restore and popup text.

### C2. Same fix for saved/bookmark teardrop pin — original change 3 (implemented)

**Goal:** When focusing a saved flat, hide the underlying saved (★) pin. Also stop a saved pin and a matching pin at the same location from overlapping in normal browse.

**Tasks (implemented):**
- Extract the focus behaviour into `createFocusController(adapter)`, used by both `initBrowse()` and `initSaved()`.
- Track saved markers by flat id and location; hide every saved pin at the focused location and restore it on clear.
- Saved cards already reuse `flat_card_compact.html`, so they carry "Show on map" with `data-flat-id`, `data-summary`, `data-storey`, price and details URL; `initSaved()` now handles the button.
- `initSaved()` re-applies the hidden state after its bookmark reload, so the saved pin stays hidden.
- In browse, a saved pin takes precedence at its location: `syncSavedOverlap()` hides the matching price/count pin underneath it and restores it when the bookmark is removed or the pins redraw.

**Affected files:** `frontend/static/js/map.js`, `frontend/templates/saved.html`, saved card partial.
**Risk:** Medium (map.js refactor; behaviour of saved pins must not regress). **Tests:** browser check that the saved pin hides on focus, stays hidden after a reload, returns on clear, and replaces a matching pin at the same location in browse.

---

## Phase D — Details-page layout

### D1. Move amenity toggles to the top of the map — original change 5 (implemented)

**Goal:** The toggle-able amenity layer buttons that were under "Active map layers" in the left panel now sit in an overlay at the top of the interactive map.

**Implemented:**
- The toggle markup lives in `partials/map_panel.html` for `mode == "flat"`; the aside now keeps only "Nearest of each".
- The same `data-layer-toggle` / `data-layer-count` attributes feed the existing `map.js` toggle handler.
- The overlay starts to the right of Leaflet's top-left zoom control, sits at z-index 800 (above pins, below controls), and wraps on narrow maps.
- On blocks without coordinates the overlay is omitted; the map status explains why.

**Affected files:** `frontend/templates/details.html`, `partials/map_panel.html`, `frontend/static/css/map.css`.
**Risk:** Low. **Tests:** browser check that each toggle still shows/hides its layer and persists in MapState; `tests/test_map.py` asserts the overlay markup.

### D2. Remove empty space at the bottom of the details page — original change 4 (implemented)

**Goal:** Remove the large whitespace seen when a searched flat (with Fit Score) is opened.

**Diagnosis:** In list view, the blank was the right column below the Fit Score card. At 1083×873 the Fit Score card was 459 px tall while the left column (Flat details + Nearby amenities) was 1123 px, leaving 663 px of empty space under the sticky card.

**Implemented:**
- The first row is now a stretched Flat details card (2/3) beside the Fit Score card (1/3); the Flat details card fills the row height and ends with an "Open this flat in Map View" link that preserves the current search.
- Nearby amenities moved to a full-width second row (`lg:col-span-3`) and uses three columns on large screens, so the page ends with a full-width card and no trailing side column.
- The list-view and map-view Leaflet containers keep their `h-full` sizing; the map view layout is unchanged.

**Affected files:** `frontend/templates/details.html`, `frontend/static/css/map.css`, `backend/core/views/details.py` (`map_view_url`).
**Risk:** Low–Medium (CSS/layout only; keep the map usable). **Tests:** browser checks at 1083×873 and `tests/test_details.py` for the Map View link.

---

## Phase E — Walking path

### E1. Draw the OneMap walking path on amenity selection — original change 6

**Goal:** Selecting an amenity pin draws the walking route on the map and shows distance/time; clicking elsewhere clears the route and info.

**Status:** Implemented and live-checked. `OneMapRoutingGateway.walking_route()` keeps `route_geometry`, `walking_distance_api` returns it as `routeGeometry`, and `map.js` decodes and draws it. The cache key was bumped so pre-Phase-E cached entries without geometry are not reused.

**Tasks:**
- Backend:
  - `OneMapRoutingGateway.walking_route()`: include `route_geometry` in the returned dict.
  - `WalkingDistance.route()`: pass it through.
  - `walking_distance_api`: include the route geometry in the JSON response (raw encoded string is fine).
  - Keep the existing day-long cache (now caches geometry too).
- Frontend (`map.js` `initFlat`):
  - Add a `routeLayer` (`L.polyline`).
  - On successful walking-distance response, decode the polyline with a small (~20-line) helper and draw the route.
  - Clear the polyline and reset the distance text on popup close, another pin selection, or map click.
  - On API failure (UC-06), clear any existing route and show the existing error path.
- CSS: route line style (brand colour, ~4px, rounded).

**Affected files:** `backend/core/integrations/onemap.py`, `backend/core/services/distance.py`, `backend/core/views/map.py`, `frontend/static/js/map.js`, `frontend/static/css/map.css`, tests.
**Risk:** Medium (API response change + route lifecycle). **Tests:** mock a OneMap routing response containing `route_geometry`; assert the API exposes it.

---

## Phase F — Block-level flat details page (original change 8)

**Goal:** Remove the separate `/blocks/...` page. Clicking a block card (or a single-flat card) opens the flat details page directly, and — when opened from Results with a search — that page is block-level: shared block fields once, then a read-only table of `(flat_type, storey_range)` combinations, and the block's best flat's Fit Score with the Price row highlighted as the varying part.

**Status:** Implemented and live-checked. `block.html` and the `block_results` view/route were removed; block and flat cards both link to `flat_details`.

**Decisions (from the open questions):**
- Saved/direct links keep the single-flat details page; only Results links (with a search) render the block-level page.
- The bookmark on a block-level page saves the best-fit representative flat.
- Results block-card action text is "View details".
- Price highlight is a subtle tint + "varies by price" badge + the block's price range on that row.
- Price range and the table cover only matching flat types (the filtered set).
- Each table row's Fit Score is the best flat's score in that combination; rows are read-only.

**Backend:** `details.flat_details` re-runs the search for the block (scored on the full search's thresholds so scores match Results), builds `shared`, `variants`, `best_flat` and a `breakdown` whose Price row is `varying`. `_card` links each card to the block's best-fit flat's details URL. `back_url` drops the `block` origin.

**Affected files:** `backend/core/urls.py`, `backend/core/views/search.py` (`_card`), `backend/core/views/details.py`, `frontend/templates/details.html`, `partials/block_details_fields.html`, `partials/block_variants_table.html`, `partials/fit_breakdown.html`, block/flat card partials, `frontend/templates/results.html`. `frontend/templates/block.html` and `partials/block_variant.html` were removed.
**Tests:** `tests/test_blocks.py`, `tests/test_details.py`, `tests/test_map.py`, `tests/test_search.py`.

---

## Phase G — Past transactions

### G1. Past transactions list + filters + 7 per page — original change 9

**Goal:** At the bottom of the block panel, list all past transactions for that block with relevant fields, filters that default to the UC-01 values (editable), max 7 per page.

**Status:** Implemented and live-checked. `partials/block_transactions.html` renders at the bottom of the details page (list view) with an editable filter bar and 7-per-page pagination.

**Notes:**
- Filters (flat type, price range, minimum lease) default to the current search's values; the filter form submits a `tx_submit` marker plus `tx_*` params so an empty selection means "all", and the main search is left unchanged.
- The list is ordered by month descending (then price), and shows Month, Flat type, Storey range, Floor area, Resale price and Remaining lease.
- The table appears on the list view only (the map view side panel stays compact).

**Tasks:**
- Query all `ResaleFlat` rows for the block/street, ordered by month descending.
- Apply editable filters (flat type, price range, minimum lease) defaulted from the current search; submit via GET and keep in the URL.
- Paginate with `Paginator(..., 7)`.
- Render a table (flat type, storey range, floor area, price, month, remaining lease) in a new partial `partials/block_transactions.html`.
- Reuse existing `SearchForm` validation where possible.

**Affected files:** `backend/core/views/search.py`, `frontend/templates/block.html` (or new partial), `frontend/static/css`, optional queryset helper.
**Risk:** Medium (filter + pagination state). **Tests:** 7-per-page pagination; filters default to the search values.

---

## Phase H — Compare homes (new feature)

### H1. Compare 2–3 homes side-by-side, mixing results and saved flats — new feature

**Status:** Implemented and live-checked. A session tray (up to 3) collects homes from Results
(a block → its best flat) and/or Saved; the `/compare` page scores them with an adjustable
weight model, declares a winner, and explains why.

**Goal:** Let the user compare 2–3 homes and see which best matches their priorities. A home is
a specific flat: a result **block** is represented by its best-ranked matching flat, and a
**saved** flat compares as itself. Two entry points:
1. **From a search:** select a block (or single flat) from Results, and add saved flats from
   Bookmarks, then compare them together.
2. **Without a search:** go to Saved and compare 2–3 saved flats directly.

**Comparison model (adjustable, Fit-Score-consistent):** the compare page scores each home on
factors the user can weight (0 = ignore, 1–10 = importance): price, remaining lease, floor
area, each amenity category, and the search location (only when set).

- **With a search** (Results → Compare), price and remaining lease reuse the Fit Score's exact
  normalisation and its fixed weights (5 each); amenities and location reuse the search's
  weights; floor area is a new factor that defaults to **ignored (0)**. So by default the
  compare total **equals the Fit Score**, and turning up floor area is the only deviation.
- **Without a search** (Saved → Compare), price, remaining lease and floor area use absolute
  reference scales (cheaper/longer/larger is better: `1 − price/1.5M`, `lease/99`,
  `area/150 m²`), so a small difference stays a small score difference rather than being
  exaggerated by min–max; every factor defaults to weight 5.

Each home's total is `100 × Σ(weight × score) / Σ weight` over the non-ignored factors. The
winner is the highest total (ties: lower price, then longer lease).

**How it works (UX):**
- A **compare tray** in the session holds up to 3 flat ids. Results cards and Saved cards each
  get an "Add to compare"/"Remove" toggle; a sticky bar on both pages shows "Compare (n)" and
  a "Compare" button (enabled at 2–3).
- The compare page (`/compare`) reads the tray, renders one column per home (address, flat
  type, storey, price, lease, floor area), a weight editor, and a factor-by-factor breakdown
  with per-cell 0–1 scores and points; the best value in each row is highlighted.
- The winner (highest total; ties → cheaper, then longer lease) is marked with a star and a
  "wins" banner. Changing a weight resubmits (GET, weights in the URL so Back/share works).
- "Clear" empties the tray.
**Implementation notes:**
- New route `compare` and `POST /api/compare/toggle`; new `backend/core/views/compare.py`,
  `frontend/templates/compare.html`, `frontend/templates/partials/compare_tray.html`,
  `frontend/templates/partials/compare_toggle.html`.
- A shared scorer `backend/core/services/compare.py` computes the per-factor scores and total
  from a list of flats + a weight vector; it does **not** reuse `calculate_fit_score` (that
  formula is unchanged and stays for Results/Details).
- The tray is stored under `request.session["compare_ids"]`; `_card` already resolves a block
  to its best flat, so the toggle just takes a flat id.
- `compare.js` (optional enhancement) toggles the tray via fetch like `bookmarks.js`; a no-JS
  POST form fallback keeps it working without JS.

**Affected files:** `backend/core/urls.py`, `backend/core/views/compare.py` (new), `backend/core/services/compare.py` (new), `backend/core/views/bookmarks.py` (or compare.py) for the toggle, `frontend/templates/compare.html` (new), result/saved card partials, `results.html`, `saved.html`, `frontend/static/js/compare.js` (new), tests.
**Risk:** Medium (new page + session tray + scoring). **Tests:** new `tests/test_compare.py`: 2/3-home tables, winner by total + tie-breaks, points add up, weight ignore/adjust, saved-only compare with no search, block compares its best flat, tray capped at 3, query/from preserved.

---

## 3. Cross-cutting concerns

- **No DB migrations expected.** If an index is needed for transaction queries, add a migration in `database/migrations/`.
- **Tests:** run `pytest` after each phase and keep the suite green (currently 217 passed). New coverage: UC-07 start bar, walking route geometry, consolidated block payload, transaction pagination, compare tray/score/page.
- **Docker:** code is bind-mounted, so Python/template/JS edits reload automatically. No dependency changes are planned, so no rebuild should be required.
- **OneMap:** point 6 relies on `route_geometry`, which is already returned by the live API (verified). No new credentials needed.
- **Documentation:** update `docs/CROSS_CHECK.md` for the UC-08 coverage row and any new behaviour; keep `README.md` accurate if the UI flow changes in Phase F or H.

---

## 4. Definition of done

- All 217 tests pass.
- New tests for the walking route, consolidated block view, transaction pagination and compare page pass.
- Manual browser checks:
  - No overlapping pins when "Show on map" is used (single-flat block, block with several flats, saved flat).
  - Walking route appears/disappears correctly.
  - Details page has no trailing empty space.
  - Amenity toggles work from the map overlay.
  - Block cards are fully clickable and show the house illustration.
  - Block view is consolidated with past transactions paginated at 7.
  - Search bar works on both Start and Results pages.
  - Comparing 2–3 homes (results blocks and/or saved flats) shows aligned, weight-adjustable breakdowns and a clear winner.

---

**Please approve this reordered plan (or request changes) before implementation begins.**