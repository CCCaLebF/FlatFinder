# FlatFinder

FlatFinder helps buyers find HDB resale flats that fit them. You set a budget, flat types, a minimum remaining lease, walking-distance limits and how much each nearby amenity matters (1–10). FlatFinder then ranks the last 12 months of resale transactions by a **Fit Score** and shows them as a list or on a map. For any flat you can:

- see the amenities within 1 km
- get the walking distance to one of them (via OneMap)
- rank the results by distance to a place you search for
- save the flat for the session

The amenity categories are **Bus Stops, MRT Stations, Child Care Centres, Hawker Centres and CHAS Clinics**.

The app is built with Django 5.2, PostgreSQL (or SQLite), Tailwind and Leaflet, with OneMap for the base map, walking routes and place search, and data.gov.sg datasets.

> This is a local prototype for SC2006. There's no deployment and there are no user accounts.

---

## 1. Run it with Docker (recommended)

You need **Docker Desktop**. You don't need to install Python or PostgreSQL.

```powershell
git clone https://github.com/CCCaLebF/FlatFinder.git
cd FlatFinder
copy .env.example .env        # macOS/Linux: cp .env.example .env
```

Edit `.env`:
- Set `POSTGRES_PASSWORD` and `DJANGO_SECRET_KEY` to any values.
- Add the team's OneMap account (`ONEMAP_EMAIL`, `ONEMAP_PASSWORD`) if you need walking distances and place search. Register at https://www.onemap.gov.sg/apidocs/register.

> **If a value contains `$`, wrap it in single quotes**, e.g. `ONEMAP_PASSWORD='pa$$word'`. Without the quotes, Docker Compose reads `$name` as a variable and silently changes the value.

| Task | Command |
|---|---|
| Start everything | `docker compose up --build` → open http://localhost:8000 |
| Import the data (§3), with real flat coordinates | `docker compose exec web python manage.py load_all --coords database/data/flat_coordinates.csv` |
| Reload only the coordinates (§4) | `docker compose exec web python manage.py import_flat_coordinates database/data/flat_coordinates.csv` then `docker compose exec web python manage.py compute_proximity` |
| Run the tests | `docker compose exec web pytest` |
| Open a Django shell | `docker compose exec web python manage.py shell` |
| Pick up `.env` changes | `docker compose up -d --force-recreate web` |
| Reset the database | `docker compose down -v`. **This deletes the imported data.** Run `load_all` again afterwards. |

How the Docker setup works:
- Database migrations run automatically when the `web` container starts. The data import doesn't, because it's slow, so run it yourself as shown above.
- Code changes reload automatically: the project folder is mounted into the container.
- The raw datasets stay on your machine in `database/data/raw/` and are never built into the image.
- The database is only reachable on your machine if you opt in: copy `docker-compose.override.example.yml` to `docker-compose.override.yml` to expose port 5432.

## 2. Run it without Docker

Python 3.12 or 3.13 works.

```powershell
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # leave DATABASE_URL empty to use SQLite (db.sqlite3)
python manage.py migrate
python manage.py load_all --coords database/data/flat_coordinates.csv
python manage.py runserver      # http://127.0.0.1:8000
pytest
```

To use your own PostgreSQL instead of SQLite, set `DATABASE_URL=postgres://user:password@localhost:5432/flatfinder` in `.env`.

## 3. Data import

The raw files go in `database/data/raw/`, which git ignores. `load_all` downloads any that are missing from data.gov.sg. You can also download them on their own:

```powershell
python manage.py download_datasets            # all seven, skipping files already there
python manage.py download_datasets --force    # download again
```

`load_all` runs these steps in order. Each one can also run on its own, and every step is safe to re-run.

| # | Command | What it does |
|---|---|---|
| 1 | `import_towns` | Gets each town's centre from the planning-area boundaries. `KALLANG/WHAMPOA` maps to Kallang. `CENTRAL AREA` combines Downtown Core, Outram and Rochor. |
| 2 | `import_flats` | Imports the resale transactions from the **last 12 months**, counted back from the latest month in the file: about 24k flats. Remaining lease is stored in decimal years as of the import date, and the dataset's original text is kept too. |
| 3 | `import_transport` | Imports bus stops and MRT/LRT **station exits**: one row per exit, so distances use the nearest exit. |
| 4 | `import_amenities` | Imports child care centres, hawker centres (skipping any "Under Construction") and CHAS clinics (from an HTML table inside the file). |
| 5 | `import_flat_coordinates <csv>` or `assign_approximate_coords` | Gives flats their locations (see §4). |
| 6 | `compute_proximity` | Works out each flat's straight-line distance to the nearest place in each category (`FlatProximity`). |

`load_all` options:
- `--coords <csv>`: run step 5 with a coordinates CSV. Use `database/data/flat_coordinates.csv`, which is in the repo.
- `--approximate`: run step 5 with the town-centre fallback (development only, when the CSV isn't available)
- `--no-download`: don't fetch missing files

**After re-running `import_flats`, run `compute_proximity` again.** Re-importing creates new flat rows (locations are kept), which clears the proximity table.

## 4. Flat coordinates

The resale dataset has **no coordinates**, and the app deliberately doesn't geocode flats. They're loaded from a CSV, `database/data/flat_coordinates.csv`, which is committed to the repo and was produced offline by `geocode_flat_addresses`. `load_all --coords database/data/flat_coordinates.csv` (§1, §2) loads it, so a normal setup never needs the geocoding tool.

**Load the coordinates:**
```
python manage.py import_flat_coordinates database/data/flat_coordinates.csv
python manage.py compute_proximity
```
In Docker, prefix both with `docker compose exec web`.

**Produce or extend the CSV** (only needed if you don't have the file, or after `import_flats` brings in new addresses):
```
python manage.py geocode_flat_addresses [--out database/data/flat_coordinates.csv] [--rate 1.0] [--limit N] [--retry-unmatched]
```
- **What it does:** looks up every distinct block and street name on the OneMap search API (no token needed). A result is accepted only if its block number matches and its road matches the street name with HDB abbreviations written out (`AVE` → `AVENUE`, `C'WEALTH` → `COMMONWEALTH`, …). It never writes to the database.
- **Outputs:** matched rows go to `database/data/flat_coordinates.csv`. Addresses it can't match go to `database/data/flat_coordinates_unmatched.csv`, with a reason and up to three candidates. Fix those by hand by adding rows to the main CSV.
- **Speed:** one request at a time, at most `--rate` per second. About 2¼ hours for the ~8,000 addresses at 1/s. If OneMap returns 429, it backs off (10 s, 30 s, 60 s, 120 s) and halves the rate.
- **Resuming:** every row is saved as it's written. If the run stops, run the same command again: addresses already in either file are skipped, so a later run only looks up new addresses. `--retry-unmatched` tries the unmatched file again.
- **Check by hand:** rows whose `match_method` ends in `far_from_town` are more than 6 km from their town's centre.

**CSV format:** a header row `block,street_name,latitude,longitude`, with WGS84 decimal degrees. Extra columns are ignored.

```csv
block,street_name,latitude,longitude
123,ANG MO KIO AVE 3,1.369000,103.845000
```

**What the import does:**
- **Matching:** rows match flats on block and street name, ignoring case and extra spaces.
- **Bad rows:** coordinates outside Singapore are rejected, which catches swapped latitude and longitude.
- **Report:** the command reports how many flats matched, how many CSV rows matched nothing, and how many flats still have no coordinates.
- **After loading:** run `compute_proximity`.

**Development fallback:** `assign_approximate_coords` places every flat without coordinates at its town's centre, with no random offsets. The UI labels these flats "Approximate location (town centre)". Every flat in a town then has the same distances, so use it only when the CSV isn't available. Loading the CSV afterwards replaces these placeholders.

Flats without coordinates still appear in list results, with proximity scores of 0. They don't appear on the map, and a walking-distance limit filters them out.

## 5. How results are ranked (Fit Score)

Every part of the score is between 0 and 1. `d` is a straight-line distance in metres.

```
proximity = max(0, 1 − d / 1000)         per category; 0 if nothing is within 1 km or the flat has no location
price     = clamp((maxBudget − price) / (maxBudget − minBudget), 0, 1)
lease     = clamp((remaining − minLease) / (99 − minLease), 0, 1)
anchor    = max(0, 1 − d_anchor / 3000)  only when a search-bar location is set
total     = round(100 × Σ(weight × score) / Σ weight, 1)
```

- **Weights:** price and lease always have weight 5. Each amenity category uses the user's 1–10 weight, and a category marked **Ignore** is left out.
- **Blank criteria:** a blank budget or minimum lease takes its value from the matching flats themselves (FR 1.1.6).
- **Where it's set:** the constants are in `backend/config/settings.py` (`FIT_SCORE_FIXED_WEIGHTS`, `ANCHOR_RADIUS_M`).

## 6. Tests

```powershell
pytest                                # SQLite, outside Docker
docker compose exec web pytest        # PostgreSQL, inside Docker
```

Both runs have the same 160 tests:
- **OneMap is always mocked** with `responses`, so the tests never call the real API.
- **NFR 1:** a timing test ranks 25,000 flats in under a second.

**Rehearsing an API failure (UC-06):** start the server with OneMap pointed at an address that doesn't respond. The error banner appears, and the rest of the app keeps working.

```powershell
$env:ONEMAP_BASE_URL="http://127.0.0.1:9"; $env:MAP_TILE_URL="http://127.0.0.1:9/{z}/{x}/{y}.png"; python manage.py runserver
```

## 7. Code layout (class diagram → code)

The repository is split into `frontend/`, `backend/` and `database/`. Inside the backend, the folders still map one-to-one onto the class diagram's Boundary / Control / Entity layers:

```
backend/
  config/              Django project: settings.py, urls.py, wsgi.py
  core/                the Django app (app label "core")
    models/            ResaleFlat, TransportNode→BusStop/MrtStation, Amenity→ChildCareCentre/HawkerCentre/ChasClinic,
                       Town, FlatProximity (Django models); SearchQuery, SortOrder, FitScore, SearchResult, Bookmark (dataclasses)
    services/          SearchController, MapController, AmenityController, BookmarkController, ErrorHandler,
                       DistanceStrategy → StraightLineDistance / WalkingDistance
    views/             SearchUI (search.py, forms.py), FlatDetailsUI (details.py), BookmarkUI (bookmarks.py),
                       MapUI server side (map.py: the JSON endpoints)
    integrations/      onemap.py: OneMapSearchGateway, OneMapRoutingGateway, token handling, OneMapError
    management/        DataLoader (the §3 commands)
    templatetags/, urls.py, apps.py
frontend/
  templates/           pages + partials/ (one file per reusable piece: card, sidebar, slider…)
  static/js/           map.js (MapUI), mapstate.js (MapState), bookmarks.js (BookmarkUI),
                       search.js (SearchUI), errors.js (the UC-06 banner)
  static/css/          app.css (sliders), map.css (map look: pins, colours, legend)
database/
  migrations/          schema migrations (wired in with MIGRATION_MODULES)
  data/                flat_coordinates.csv (committed); raw/ holds the data.gov.sg downloads (git-ignored)
tests/
```

| Folder | Diagram layer |
|---|---|
| `frontend/templates/`, `frontend/static/` | «boundary» UI, client side (and the `MapState` entity) |
| `backend/core/views/` | «boundary» UI, server side |
| `backend/core/integrations/` | «boundary» gateways |
| `backend/core/services/` | «control» |
| `backend/core/management/` | «control» «startup» DataLoader |
| `backend/core/models/` | «entity» |
| `database/` | PostgreSQL / SQLite schema and the data the DataLoader reads |

**JSON endpoints:**

| Endpoint | What it returns |
|---|---|
| `GET /api/flats/area-counts` | Matching flats per town |
| `GET /api/flats/in-bounds` | Matching flats in the visible map area |
| `GET /api/flats/<id>/amenities` | Everything within 1 km of a flat |
| `GET /api/walking-distance` | Walking distance from a flat to a point |
| `GET /api/bookmarks` | The session's saved flats |
| `POST /api/bookmarks/<id>/toggle` | Saves or unsaves a flat |

**Changing the look:**
- **Colours:** the whole palette is one `tailwind.config` block in `frontend/templates/base.html` (`brand-*`), plus the matching `--ff-*` variables at the top of `frontend/static/css/map.css`.
- **Page pieces:** the reusable parts are in `frontend/templates/partials/`.

## 8. Design changes (for updating the class diagram)

These differ from the original class diagram. **[docs/CROSS_CHECK.md](docs/CROSS_CHECK.md) has the full checklist**: every difference from the diagram and the SRS, and a coverage table for every FR, NFR and use case.

**Approved in `PLAN.md` §8:**
- new classes `Town`, `FlatProximity`, `DistanceStrategy` and `DataLoader`
- five separate weights in `SearchQuery`, plus `anchorLabel`, `anchorWeight` and `FitScore.anchorScore`
- `Bookmark.session_id` instead of `user_id`
- `MapController` has no rendering methods

**Added while building:**
- **`OneMapTokenProvider` and `OneMapError`.** Only routing needs a OneMap token; search and map tiles don't. That's tested against the live API.
- **`ScoreBounds`:** the price and lease thresholds, so a flat scores the same on the details page as in the list.
- **`NearbyAmenity`:** an amenity plus its distance from the flat.
- **`SearchResult` holds result ids rather than whole flats,** along with the Fit Scores, the sort order and the bounds. A page only loads the 20 flats it shows.
- **`GET /api/bookmarks`,** so saved flats can be drawn on the map (UC-03.AC.1). The Saved page also has a Map View.
- **Browsing maps reopen where you left them,** using `MapState`.
- **`search.js` and `errors.js`,** client-side pieces of `SearchUI` and `ErrorHandler`.

## 9. Open decisions and known limits

- **Walking-distance sliders (FR 1.1.3), an open decision:** for now they're a hard filter on straight-line distance, in `SearchController.apply_walk_limits`, marked `OPEN DECISION (FR 1.1.3)`.
- **Waiting on the team** (see `docs/CROSS_CHECK.md` §2):
  - C3: what Fit Score to show with no search
  - C4: a budget range slider or number boxes
  - C5: drawing town borders on the map
- **Data notes:**
  - The bus stop dataset has no names, so stops show as "Bus Stop 54621".
  - LRT stations count as MRT Stations.
  - CHAS clinics include dental clinics.
- **Bookmarks last for the browser session.** Re-running `import_flats` also clears them, because flat ids change.
- **The Tailwind Play CDN and Google Fonts need an internet connection.** That's fine for the demo; a real deployment would bundle them.
