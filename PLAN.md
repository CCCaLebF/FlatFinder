# FlatFinder: Build Plan for the Prototype

This plan is for the agent that builds the FlatFinder prototype. It covers the requirements, the design decisions already made, and the order to build in. **Don't change the decisions in §2 without asking the user.**

## 0. Source documents (read these first)

All paths are relative to `C:\NTU\NTU Y2S1\SC2006 SOFTWARE ENGINEERING\`.

| Document | Path | Use it for |
|---|---|---|
| SRS (FRs, NFRs, data dictionary, UC-01 to UC-14, UI mockups, dataset links) | `2006-SCSC-F4/Lab3/Lab2Updated.pdf` | **The source of truth** for features and names |
| Dialog map | `2006-SCSC-F4/Lab3/DialogMap.png` (editable copy: `DialogMap.drawio`) | Pages, navigation and UI states |
| Lab 3 to-do list | `Lab/Lab 3 Summary.md` | Context on the design work still outstanding |
| Class diagram | Image supplied by the user (Visual Paradigm). §5 lists every class. | Class names and responsibilities |

**The UI mockups (SRS pp. 22–24) are a visual guide only.** Copy their layout and look: the header with the List/Map toggle and the Saved counter, the left sidebar of filters, the result cards and the map panels. **Don't copy their wording.** Take names, amenity categories and data fields from the SRS and this plan. For example, the mockups say "Schools" and "Parks", but the app uses *Child Care Centres*, and there is no Parks category.

## 1. What to build

A Django web app that runs locally. Users set a budget, flat types, a minimum remaining lease, walking-distance limits and importance weights for each amenity category. The app returns HDB resale flats ranked by a **Fit Score** and shows them as a list or on a map. Users can open a flat's details, see amenities within 1 km and get the walking distance to one. They can also bookmark flats for the session.

The amenity categories are, everywhere: **Bus Stops, MRT Stations, Child Care Centres, Hawker Centres, CHAS Clinics.** Bus Stops and MRT Stations are the transport nodes; the other three are amenities.

**Out of scope:**
- Geocoding resale flats (see §2, decision 6).
- Deployment, since the app runs locally for the demo.
- User accounts or login (NFR 4).
- Flat photos, "Preferred Towns" and "District Overview" from the mockups.

## 2. Decisions already made

| # | Topic | Decision |
|---|---|---|
| 1 | Weight scale | **1–10** for each amenity category. A category left blank is ignored (FR 1.1.6). The SRS still says 1–5 in FR 1.1.4; the team will fix that, so build for 1–10. |
| 2 | Fit Score | Use the formula in §4. **Price and lease have fixed weights.** The user's budget and lease sliders set the *thresholds*, not weights. |
| 3 | Walking-distance sliders (FR 1.1.3) | **Not decided yet.** Build the sliders and store their values in `SearchQuery`. Apply them in **one** function, `apply_walk_limits()`, which for now does a hard filter on the pre-computed straight-line distance. Mark it with `# OPEN DECISION (FR 1.1.3)` so it's easy to change. |
| 4 | Search-bar anchor (UC-07) | The geocoded location becomes a **sixth proximity sub-score**, "distance to anchor", with its own 1–10 weight slider (default 5) that only appears once an anchor is set. Results are re-ranked with the same formula. |
| 5 | Amenity source (UC-11) | Amenities and transport nodes come from **our database**, imported from the data.gov.sg datasets in §3. They never come from OneMap. |
| 6 | Flat coordinates | **Don't geocode.** The resale dataset has no coordinates, and the team will produce them separately as a CSV after the prototype works. Build the import contract and the fallback described in §3.3. |
| 7 | Which records count as "flats" | Every resale **transaction in the last 12 months**, counted back from the latest `month` in the file. Each row is one `ResaleFlat`. |
| 8 | Area counts (FR 2.1.1) | Group by the resale dataset's **`town` column**. Put one count marker at each town's centroid. |
| 9 | Database | **PostgreSQL without PostGIS**, so no GeoDjango or GDAL. Store `latitude`/`longitude` as floats. Pre-compute straight-line distances in Python with a KD-tree (`scipy.spatial.cKDTree` on 3-D unit vectors, which gives exact great-circle distances). The settings must also support **SQLite** through `DATABASE_URL`, for tests and for teammates who don't have Postgres. |
| 10 | Bookmarks | Stored in the **Django session** (session-only; UC-05 assumption) as a list of `ResaleFlat` ids. Nothing is saved to a user table. |
| 11 | Front end | **Django templates, Tailwind and Leaflet.** Load Tailwind (Play CDN is fine for the prototype) and Leaflet `1.9.4` from a CDN. Use small `fetch()` calls to JSON endpoints for map data. **No React or other SPA framework.** |
| 12 | Defaults | 20 results per page. Default sort is Fit Score, descending. The map shows area counts below **zoom 14** and flat pins from zoom 14 up. |
| 13 | Containerisation | **Docker and Docker Compose** for development, so every teammate runs the same Python, PostgreSQL and dependency versions with one command. This is for local development only; it doesn't change "no deployment" in §1. See §6a. |

## 3. Data

### 3.1 Datasets (from SRS → References → Dataset Links)

| Entity | Dataset | data.gov.sg id |
|---|---|---|
| `ResaleFlat` | Resale Flat Prices (2017 onwards) | `d_8b84c4ee58e3cfc0ece0d773c8ca6abc` |
| `Town` centroids and fallback | Planning area / town boundaries | `d_2cc750190544007400b2cfd5d7f53209` |
| `MrtStation` | LTA MRT Station Exit | `d_b39d3a0871985372d7e1637193335da5` |
| `BusStop` | LTA Bus Stop | `d_3f172c6feb3f4f92a2f47d93eed2908a` |
| `ChildCareCentre` | Child Care Services (GeoJSON) | `d_5d668e3f544335f8028f546827b773b4` |
| `HawkerCentre` | Hawker Centres (GeoJSON) | `d_4a086da0a5553be1d89383cd90d07ecd` |
| `ChasClinic` | CHAS Clinics (excludes polyclinics and hospitals) | `d_548c33ea2d99e29ec63a7cc9edcccedc` |

- Put the raw files in `data/raw/`, which is git-ignored. If downloading by script, data.gov.sg's public download API is `GET https://api-open.data.gov.sg/v1/public/api/datasets/{id}/poll-download`, which returns a temporary file URL. Check this against the live docs before relying on it. If you can't download the files, ask the user to put them in `data/raw/`.
- **Inspect each file before writing its parser.** Known quirks to check for:
  - Older data.gov.sg GeoJSON files keep their attributes in an HTML table inside a `Description` property. Parse the name and postal code out of it.
  - The LTA bus stop and MRT exit files may use **SVY21 (EPSG:3414)** rather than WGS84. If so, convert with `pyproj`.
  - The MRT file has **one row per exit**. Store one `MrtStation` row per exit, with `exit_code`, so distances use the nearest exit. When listing nearby stations, show each station name once.
  - The town boundary file uses planning-area names. Map these to the resale `town` values with an explicit dictionary, e.g. `KALLANG/WHAMPOA` → `KALLANG`, and `CENTRAL AREA` → the central planning areas. Log any names that don't match.

### 3.2 Parsing the resale data

- The columns are `month, town, flat_type, block, street_name, storey_range, floor_area_sqm, flat_model, lease_commence_date, remaining_lease, resale_price`. There's no id column, so use a surrogate primary key.
- Keep the last 12 months only (decision 7).
- Store `remaining_lease` in **decimal years as of the import date**, calculated as `99 − (years since lease_commence_date)`. Also keep the raw dataset string for display, so the FR 2.2.3.1.8 field can be shown either way.
- `flat_type` values match FR 1.1.2: 1 ROOM … EXECUTIVE, MULTI-GENERATION.

### 3.3 Coordinates contract (decision 6)

- `ResaleFlat.latitude` and `longitude` are **nullable**. `ResaleFlat.coords_approximate` is a boolean.
- Management command `import_flat_coordinates <csv>`:
  - Reads columns `block,street_name,latitude,longitude`.
  - Matches rows on normalised (`upper`, trimmed) block and street name.
  - Sets `coords_approximate=False`.
  - Reports how many flats matched and how many didn't.
- **Development fallback**, opt-in only: `assign_approximate_coords`.
  - Gives every flat without coordinates its town's centroid from the boundary dataset and sets `coords_approximate=True`. **Don't add random jitter or invent coordinates in any other way.**
  - The UI shows "Approximate location (town centre)" on any flat with `coords_approximate=True`.
- Flats with no coordinates still appear in list results, with proximity sub-scores of 0. They don't appear as map pins.
- Command `compute_proximity` builds `FlatProximity` (§5). Run it again after coordinates change.

### 3.4 Import pipeline

`DataLoader` is the start-up class from the class diagram. Implement it as management commands, which can run one at a time or together through `load_all`:

1. `import_towns`
2. `import_flats`
3. `import_transport` (bus stops and MRT exits)
4. `import_amenities` (child care, hawker and CHAS)
5. `import_flat_coordinates` (optional), or `assign_approximate_coords` (dev only)
6. `compute_proximity`

Every command must be safe to re-run. Use `update_or_create`, or truncate and reload inside a transaction.

## 4. Fit Score (decision 2)

Every sub-score runs from 0 to 1. `d` is a straight-line distance in metres, pre-computed in `FlatProximity`.

```
proximity_c = max(0, 1 − d_c / 1000)        for each category c, where d_c is the distance to the nearest one within 1 km.
                                             0 if there is none within 1 km, or if the flat has no coordinates.
price       = clamp((maxBudget − price) / (maxBudget − minBudget), 0, 1)
lease       = clamp((remaining − minLease) / (99 − minLease), 0, 1)
anchor      = max(0, 1 − d_anchor / ANCHOR_RADIUS_M)        only when an anchor is set (decision 4)

total = round(100 × Σ(w_i × s_i) / Σ w_i, 1)
```

- **Weights:**
  - `price` and `lease` each use `FIT_SCORE_FIXED_WEIGHTS = {"price": 5, "lease": 5}` in settings.
  - Each amenity category uses the user's 1–10 weight. Leave out any category the user left blank.
  - The anchor uses its own 1–10 weight.
- **Unconstrained thresholds (FR 1.1.6):**
  - If the budget is blank, use the minimum and maximum `resale_price` of the filtered set.
  - If the minimum lease is blank, use the lowest remaining lease in the filtered set.
  - If the max and min are equal, the sub-score is 1.
- `ANCHOR_RADIUS_M = 3000` goes in settings.
- `FitScore` holds `total`, `priceScore`, `leaseScore`, the five category scores and `anchorScore`. The details page shows the breakdown.
- **Performance (NFR 1, 5 s):**
  - Filter in SQL.
  - Pull the matching rows and their `FlatProximity` values in one query, using `select_related`.
  - Score them with numpy arrays.
  - About 25k rows should take well under a second. Add a test that times this.

**Filtering (UC-08) is separate from scoring.** The budget range, flat types and minimum lease are hard filters. `apply_walk_limits()` follows decision 3.

## 5. Mapping the class diagram to code

Organise the code by the diagram's stereotypes. There's one Django app, `core`, with these layers:

```
FlatFinder/
  manage.py
  requirements.txt            # Django 5.x, psycopg[binary], requests, numpy, scipy, pyproj, python-dotenv,
                              # dj-database-url, pytest, pytest-django, responses
  .env.example                # DATABASE_URL, ONEMAP_EMAIL, ONEMAP_PASSWORD (never commit .env)
  .gitignore                  # .env, data/raw/, __pycache__, *.sqlite3, .venv/
  Dockerfile                  # see §6a
  docker-compose.yml          # services: web, db
  .dockerignore               # .env, .venv/, data/raw/, __pycache__, *.sqlite3, .git/
  docker/entrypoint.sh        # wait for db, run migrations, then exec the command
  flatfinder/                 # settings.py, urls.py
  core/
    entity/                   # Django models + plain dataclasses
    control/                  # services (controllers), distance strategies, error handler
    boundary/
      ui/                     # views (one module per UI class), forms
      gateways/               # OneMap gateways
    management/commands/      # DataLoader commands
    templates/core/           # base.html, start.html, results.html, details.html, saved.html, partials/
    static/core/js/           # map.js (MapUI), bookmarks.js (BookmarkUI), mapstate.js (MapState)
  tests/
  data/raw/
```

`core/models.py` re-exports the classes in `core/entity/` so Django can find them.

| Diagram class | Code | Notes |
|---|---|---|
| **Entity** | | |
| `ResaleFlat` | model | Has the FR 2.2.3.1 fields, plus `town`, `latitude`/`longitude` (nullable) and `coords_approximate`. Indexed on `town`, `flat_type`, `resale_price`, `latitude` and `longitude`. |
| `TransportNode` → `BusStop`, `MrtStation` | **abstract** base model, plus 2 concrete models | Fields: `id`, `name`, `type`, `latitude`, `longitude`. `BusStop` adds `stop_code`; `MrtStation` adds `exit_code`. |
| `Amenity` → `ChildCareCentre`, `HawkerCentre`, `ChasClinic` | **abstract** base model, plus 3 concrete models | Fields: `id`, `name`, `type`, `postal_code`, `address`, `latitude`, `longitude`. |
| `Town` *(new)* | model | Fields: `name` (the resale town value), `centroid_lat`, `centroid_lng`. Needed for FR 2.1.1. |
| `FlatProximity` *(new)* | model, one-to-one with `ResaleFlat` | Fields: `nearest_bus_stop_m`, `nearest_mrt_station_m`, `nearest_child_care_centre_m`, `nearest_hawker_centre_m`, `nearest_chas_clinic_m` (nullable floats). Holds the pre-computed straight-line distances. |
| `SearchQuery` | dataclass, built from GET parameters | Fields: `minBudget`, `maxBudget`, `flatTypes`, `maxWalkBus`, `maxWalkMrt`, `minRemainingLease`, **five separate `int` weights** (`busStopWeight` … `chasClinicWeight`; `None` means ignored), `anchorLat`, `anchorLng`, `anchorLabel`, `anchorWeight`. Methods: `+isUnconstrained(field)`, `+setAnchor(lat, lng, label)`. |
| `FitScore`, `SearchResult`, `SortOrder` | dataclasses | `SortOrder.field` is one of `price`, `remaining_lease`, `floor_area`, `fit_score`. `direction` is `asc` or `desc`. |
| `Bookmark` | dataclass, stored in the session | Fields: `session_id`, `flat_id`, `timestamp`. |
| `MapState` | client-side JS (`mapstate.js`) in `localStorage` | Holds `centre`, `zoom`, `visibleLayers` and `viewMode`. Implements UC-13. |
| **Control** | | |
| `SearchController` | `control/search.py` | `filter_flats(query)`, `apply_walk_limits(qs, query)`, `calculate_fit_score(flat, query, bounds)`, `rank_flats(...)`, `sort_results(result, order)`, `set_proximity_anchor(query, text)` (uses `OneMapSearchGateway`). |
| `MapController` | `control/map.py` | `get_area_counts(query)` returns `[{town, lat, lng, count}]`. `get_pins_in_view(bounds, query, limit=500)`. **Has no rendering methods**; rendering is `MapUI`'s job. |
| `AmenityController` | `control/amenity.py` | `find_nearest_amenities(flat, radius_m=1000)` returns the amenities grouped by category, sorted by distance. It uses a bounding-box query on the latitude/longitude indexes, then haversine. |
| `BookmarkController` | `control/bookmark.py` | `toggle_bookmark(session, flat_id)`, `is_bookmarked(session, flat_id)`, `get_bookmarks(session)`. Use `session_id` as the spelling everywhere. |
| `ErrorHandler` | `control/errors.py` | `log_error(endpoint, timestamp, code)` writes to Python `logging` (UC-06 step 2). `to_response(exc)` turns a `OneMapError` into JSON `{"error": "<user message>"}` with HTTP 502. |
| `DistanceStrategy` *(new, an interface)* | `control/distance.py` | An ABC with `distance_m(origin, target) -> float`. |
| `StraightLineDistance` | the same module | Haversine. Used by `compute_proximity` and `AmenityController`. |
| `WalkingDistance` | the same module | Calls `OneMapRoutingGateway`. Used only on demand (UC-04). |
| `DataLoader` *(new)* | management commands in §3.4 | |
| **Boundary: UI** | | |
| `SearchUI` | `boundary/ui/search.py` + `start.html` / `results.html` | Sidebar form, results list, sort control, search bar, no-results state. |
| `MapUI` | `static/core/js/map.js` + map partials | Leaflet map, area counts and pins, amenity layers, walking-distance popup, error banner, restoring the last map state. |
| `FlatDetailsUI` | `boundary/ui/details.py` + `details.html` | Flat fields, Fit Score breakdown, nearby amenity list. Selecting an amenity happens on the map, through `MapUI`. |
| `BookmarkUI` | `boundary/ui/bookmarks.py` + `saved.html` + `bookmarks.js` | Bookmark toggle icon, Saved counter, Saved Flats page with an empty state. |
| **Boundary: gateways** | `boundary/gateways/onemap.py` | Each gateway raises `OneMapError` on a timeout or a non-2xx response. Use a 5 s timeout. |
| `MapGateway` | settings value and JS config | Base-map tile URL template. OneMap's basemap is expected to be `https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png`, and it needs OneMap's attribution. Check both. |
| `OneMapSearchGateway` | class | `geocode(text) -> (lat, lng, label)` or `None`. |
| `OneMapRoutingGateway` | class | `walking_distance_m(origin, destination) -> float`, using `routeType=walk`. |
| Token handling | a shared helper in the same module | Gets the token from `ONEMAP_EMAIL`/`ONEMAP_PASSWORD`, caches it and refreshes it before it expires. **Check the OneMap API docs for which endpoints need a token.** Routing is expected to need one; search and tiles may not. **The token must never reach the browser.** |

## 6. Pages, URLs and the dialog map

Follow `DialogMap.png`. All search state lives in **GET parameters**, so Back, refresh and links all work. These include `view=list|map` and `page`.

| URL | Dialog-map state | What it shows |
|---|---|---|
| `/` | Start Page | The sidebar filter form (budget range, flat-type chips, minimum lease, bus and MRT walk sliders, five 1–10 weight sliders with an "ignore" option each, **Find Matching Flats**). In List View, an intro panel. In Map View, area counts below zoom 14 and flat pins from zoom 14 up. Clicking a pin opens a popup with **View details**, which goes to `/flats/<id>/?from=start&view=map`. |
| `/results?...` | Results Page | The same sidebar, plus the search bar (UC-07), the sort control (UC-10), 20 cards per page with a bookmark icon each (UC-05), and a List/Map toggle. Map View shows a side list and pins. **0 matches** shows the No Results state ("Adjust your requirements", NFR 2.2). **No geocoding match** shows a dismissible "No matching location found" message. |
| `/flats/<id>/?from=start\|results\|saved&...` | Property Details Page | List View shows the FR 2.2.3.1 fields, the Fit Score breakdown, the bookmark icon and the nearby amenities list. Map View shows the flat plus amenity pins within 1 km, with layer toggles (UC-12). Clicking an amenity pin calls the walking-distance API and shows the result in the pin's popup (UC-04). **Back** follows the `from` guard: it returns to Start, Results (with the original query string) or Saved. |
| `/saved/` | Saved Flats | The bookmarked flats, each with a remove icon, or the empty state "No saved flats yet" (UC-14). **Back** returns to the last Browsing page, using the `HTTP_REFERER` or a stored "last page". |

The header on every page has the logo, the **List View / Map View** toggle and **Saved (n)**. The view mode carries over between pages: use the `view` parameter, with `localStorage` as the default.

**JSON endpoints, for `MapUI` and `BookmarkUI`:**
- `GET /api/flats/area-counts?<query>`
- `GET /api/flats/in-bounds?south=&west=&north=&east=&<query>`
- `GET /api/flats/<id>/amenities`
- `GET /api/walking-distance?flat_id=&lat=&lng=` returns `{metres, minutes}`, or `{error}` with HTTP 502.
- `POST /api/bookmarks/<flat_id>/toggle` returns `{saved, count}`. It's CSRF-protected.

**API errors (UC-06 and UC-13):**
- Any OneMap failure shows a **dismissible banner**, e.g. "OneMap service currently unavailable".
- The rest of the page keeps working.
- If tiles fail to load, `MapUI` restores the last `MapState` from `localStorage`, or shows a blank map with the banner if none is saved.

## 6a. Docker development setup (decision 13)

The goal is that a teammate can clone the repo, copy `.env.example` to `.env`, run `docker compose up`, and get a working app at `http://localhost:8000`. They shouldn't need to install Python or PostgreSQL themselves.

**`Dockerfile` (the `web` image):**
- Base image `python:3.12-slim`, with the exact tag pinned. Using 3.12 rather than 3.13 is deliberate: numpy, scipy and pyproj all have prebuilt wheels for it.
- Install `requirements.txt` with `pip install --no-cache-dir`. Copy `requirements.txt` before the source code, so the dependency layer stays cached between builds.
- Set `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1`. Run as a non-root user.
- The default command is `python manage.py runserver 0.0.0.0:8000`. That's the development server, which matches the local-only scope.

**`docker-compose.yml`:**
- **`db`:** the official `postgres:16` image (plain PostgreSQL, no PostGIS; decision 9).
  - Takes `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD` from `.env`.
  - Uses a named volume, `pgdata`, so the imported data survives restarts.
  - Has a healthcheck using `pg_isready`.
  - Only publish port 5432 to the host if a teammate needs a DB client. Make that an opt-in override file, `docker-compose.override.example.yml`, rather than a default.
- **`web`:**
  - Built from the `Dockerfile`, with `depends_on: db` set to `condition: service_healthy`.
  - Publishes `8000:8000` and reads `env_file: .env`.
  - Sets `DATABASE_URL=postgres://<user>:<password>@db:5432/<db>`, using the service name `db` as the host.
- **Bind mounts on `web`:**
  - `./` to `/app`, so code changes reload live without rebuilding.
  - `./data/raw` to `/app/data/raw`, so the datasets stay on the host and are never copied into the image.

**`docker/entrypoint.sh`:**
- Waits for the database.
- Runs `python manage.py migrate --noinput`.
- Then runs the container command (`exec "$@"`).
- It must **not** run the data import automatically, because that's slow and must stay a deliberate step.

**`.env.example` must list every variable with safe placeholder values:** `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=1`, `ONEMAP_EMAIL` and `ONEMAP_PASSWORD`.

**Commands to document in the README:**

| Task | Command |
|---|---|
| Start everything | `docker compose up --build` |
| Import the data (§3.4) | `docker compose exec web python manage.py load_all` |
| Load the coordinates CSV | `docker compose exec web python manage.py import_flat_coordinates data/raw/<file>.csv` |
| Run the tests | `docker compose exec web pytest` |
| Open a Django shell | `docker compose exec web python manage.py shell` |
| Reset the database | `docker compose down -v`. This **deletes the imported data**; say so in the README. |

**Rules:**
- The app must still run **without Docker**, using a local venv and the SQLite fallback through `DATABASE_URL`. Docker is the recommended path, not the only one.
- Tests must pass both inside the container (on Postgres) and outside it (on SQLite).
- Never bake `.env`, credentials or `data/raw/` into the image. `.dockerignore` must exclude them.
- Pin exact image tags and package versions. Don't use `latest`.
- The team develops on Windows, so check that the bind mount and live reload work with Docker Desktop on Windows. Make sure `entrypoint.sh` uses **LF line endings**, enforced with `.gitattributes`: `*.sh text eol=lf`. A CRLF entrypoint fails inside Linux containers.

## 7. Build order

Finish each phase before starting the next. Each phase ends with passing tests and a short note to the user on what was done.

1. **Scaffold.**
   - Create the Django project and the `core` layers from §5, `requirements.txt`, `.env.example`, `.gitignore` and settings (`DATABASE_URL`, with SQLite as the fallback).
   - Add pytest and pytest-django.
   - Add the Docker setup from §6a (`Dockerfile`, `docker-compose.yml`, `.dockerignore`, `docker/entrypoint.sh` and `.gitattributes`). The phase is done when `docker compose up --build` serves the empty app on `localhost:8000` and `docker compose exec web pytest` passes.
   - Write the models, dataclasses and empty controller and gateway classes, all with **docstrings that name the diagram class and the UC/FR numbers**. This also gives the team their Lab 3 skeleton.
2. **Data import** (§3).
   - Write the commands and run them on the real files.
   - Tests use small fixture files in `tests/fixtures/`: one GeoJSON file with the HTML `Description` format, and one SVY21 sample if one exists.
3. **UC-01/08/09: Search, Filter and Rank.**
   - Build `SearchQuery` parsing, `filter_flats`, `apply_walk_limits` (provisional), the Fit Score and ranking.
   - Build the Start and Results pages in List View, with pagination and the No Results state.
   - Unit-test the formula, including the unconstrained bounds, ignored categories and missing coordinates. Add the NFR 1 timing test.
4. **UC-10 Sort** and **UC-05/14 Bookmarks**, including the Saved page and counter.
5. **UC-02/11: Details and Nearest Amenities.** Build the details page with the `from` guards on Back.
6. **UC-03/12/13: Map.** Build `map.js`, the area counts and in-bounds pins, the List/Map toggle on every page, layer toggles and `MapState` caching.
7. **UC-04/07/06: OneMap features.**
   - Build the routing and search gateways, the token helper, the walking-distance popup, the search-bar anchor and re-ranking, and the error banner.
   - Test the gateways with `responses` mocks for success, timeout and 401. Don't call the real API in tests.
8. **Polish.**
   - Match the mockups' look (green/teal palette, cards, chips, sliders).
   - Check that all search controls fit without scrolling at 1366×768 (NFR 3.2).
   - Write a README covering setup **with Docker first** (the §6a command table), then the non-Docker venv setup, the import order, the coordinates CSV contract and how to run tests.

## 8. Rules for the building agent

- **Don't geocode the resale flats** or invent coordinates. The only exception is the opt-in town-centroid fallback in §3.3.
- **Don't commit or print secrets.** OneMap credentials go in `.env` only.
- Keep names traceable to the class diagram and the SRS. If you must leave the diagram's design, list the change under "Design changes" in the README so the team can update the diagram. The changes already approved are `Town`, `FlatProximity`, `DistanceStrategy`, `DataLoader`, the five separate weights, `anchorScore`/`anchorWeight`, `Bookmark.session_id`, and `MapController` having no rendering methods.
- **Ask the user** instead of guessing in these cases:
  - Decision 3 (walk limits) needs anything beyond the provisional filter.
  - A dataset can't be downloaded or parsed.
  - The OneMap API behaves differently from what §5 expects.
- Don't edit the SRS or the files in `2006-SCSC-F4/`.

## 9. Open items for the team (not for the build agent)

- **Decision 3:** how the walking-distance sliders work. Today they're a provisional straight-line hard filter.
- **Update the SRS** to match: the 1–10 scale in FR 1.1.4, Child Care Centres everywhere, CHAS Clinics in the UC-01/09/12 lists, UC-11 querying the database (so UC-06 no longer extends UC-11), and the 12-month data window.
- **Update the class diagram** with the approved changes in §8.
- **Produce the coordinates CSV** (`block,street_name,latitude,longitude`), then run `import_flat_coordinates` and `compute_proximity`.
