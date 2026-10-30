# Demo video handoff (SC2006 deliverable 3.3.1)

This is a handoff for a Claude session that can reach OneMap. It explains how to record and assemble FlatFinder's 5–7 minute demo video. The storyboard, recorder, voiceover and assembly scripts are written and tested; what's left is running them against the real app with real data and the live OneMap map.

Everything referenced here is in `scripts/demo/`. Nothing in this handoff, or in those scripts, contains credentials.

## 1. What to deliver

| | |
|---|---|
| Deliverable | A 5–7 minute demo of the working product, with voiceover |
| Target length | About 5:40 (4.5 s title card + about 5:32 recording + 5 s end card). Must stay between 5:00 and 7:00. |
| Video | MP4, H.264, 1920×1080, 30 fps, `yuv420p`, CRF 18 |
| Audio | AAC 192 kb/s, 48 kHz, voiceover only (no music), loudness-normalised to −16 LUFS |
| Extras | `.srt` subtitles generated next to the MP4 |
| Voice | Kokoro TTS (open source, runs locally), voice `af_heart`, speed 1.0, US English |

Before recording, confirm with the user that an AI voiceover is allowed for their course. Some courses require team members to narrate. If so, deliver the silent recording, the script (`narration.json`) and `scenes.json` so they can record their own voices against it.

## 2. Status: what's done and what isn't

**Done and tested** (in a sandbox that could not reach OneMap or data.gov.sg):
- 18-scene storyboard and narration covering every use case in the use-case document: UC-01 to UC-15, plus the UC-01 no-results exception.
- `record_demo.py`. It drives a headless Chromium through the demo and records the browser's own frames to H.264. It also draws a visible cursor with click ripples, holds each scene at least as long as its narration, and writes `scenes.json` with every scene's start and end time. Five full test runs were made; the last had no failed scenes.
- `tts.py`, which voices every scene and records each clip's length.
- `assemble.py`. It adds the title card, a use-case label at the start of each scene, the voiceover placed at each scene's start, fades and the end card, then writes the final MP4 and `.srt`.

**Not done.** The test runs used synthetic flats (`dev/seed_dev.py` on the repo's real block coordinates), a grey placeholder map, and faked OneMap responses for walking routes and place search (`dev/devroutes.py`). Nobody has yet seen:
- the real OneMap base map behind the pins,
- real walking routes (UC-04),
- the search bar resolving "Bishan MRT" through OneMap (UC-07),
- the scenes with the real data.gov.sg data.

Those are what the recording run in this session must produce and check.

## 3. Environment

**Hosts the app needs** (the browser and the Django server both make these calls):

```
www.onemap.gov.sg        base-map tiles, place search, walking routes (token login)
api-open.data.gov.sg     dataset downloads for load_all (it may redirect downloads to another host; allow that too if it shows up)
cdn.tailwindcss.com      Tailwind Play CDN (styles)
unpkg.com                Leaflet 1.9.4
fonts.googleapis.com     Inter font CSS
fonts.gstatic.com        Inter font files
```

Also needed: pip/PyPI (`playwright`, `kokoro-onnx`, `soundfile`, `imageio-ffmpeg`), and GitHub release downloads for the Kokoro model files (`tts.py` fetches them, about 355 MB). Check reachability first:

```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://www.onemap.gov.sg/api/common/elastic/search?searchVal=bishan%20mrt&returnGeom=Y&getAddrDetails=N"
```

**Credentials.** Walking routes need a OneMap account in `.env` (`ONEMAP_EMAIL`, `ONEMAP_PASSWORD`). Ask the user for their `.env`, or for those two values. Never commit `.env`, never print the values, and never write them into any file under `scripts/` or `docs/`. Place search and map tiles need no token.

## 4. Steps

From the repo root.

**4.1 Run the app with real data** (SQLite is fine; Docker also works, see README §1):

```bash
pip install -r requirements.txt
cp /path/to/user-supplied/.env .env         # from the user; set DATABASE_URL= (empty) for SQLite
python manage.py migrate
python manage.py load_all --coords database/data/flat_coordinates.csv
python manage.py runserver 127.0.0.1:8000   # leave running
```

Spot-check `http://127.0.0.1:8000/` in a browser: the map shows OneMap tiles, a search returns flats, and a walking route draws in a flat's Map View.

**4.2 Voiceover:**

```bash
pip install kokoro-onnx soundfile
python scripts/demo/tts.py                  # writes scripts/demo/vo/*.wav and vo/durations.json
```

`record_demo.py` reads `vo/durations.json` when it exists, so each scene is held for its clip's real length. If `narration.json` changes, re-run `tts.py` before recording. To re-voice only some scenes: `python scripts/demo/tts.py af_heart 1.0 s13_browse,s15_compare`.

**4.3 Record:**

```bash
pip install playwright imageio-ffmpeg && python -m playwright install chromium
cd scripts/demo
FF_URL=http://127.0.0.1:8000 FF_OUT=out python record_demo.py
```

It takes about 6 minutes and prints one line per scene. It finishes with `done. failed scenes: none`. Outputs go to `scripts/demo/out/`: `recording.mp4`, `scenes.json`, `log.txt`, and `failed_<scene>.png` for any step that failed. A failed step doesn't stop the run: the scene is still held for its full narration, so check the log.

`FF_PLACE` changes the search-bar place (default `Bishan MRT`). The narration of `s06_searchbar` says "Bishan MRT", so keep them in sync. Do **not** set `FF_DEV` for the real recording.

**4.4 Check the recording before assembling** (see §7). Re-record if a scene is wrong.

**4.5 Assemble:**

```bash
python scripts/demo/assemble.py scripts/demo/out FlatFinder_demo.mp4 --team "Team name / members"
```

This takes about 2–3 minutes and writes `FlatFinder_demo.mp4` and `FlatFinder_demo.srt`. `--team` adds a line under the title card; ask the user what to put there. It needs `ffmpeg` and `ffprobe` on PATH.

## 5. Recording format details

- **Browser:** viewport 1440×810 at device scale factor 4/3. The page lays out like a 1440-wide laptop screen but renders at 1920×1080, so text is legible on video. Locale `en-SG`, time zone `Asia/Singapore`, fresh context (no bookmarks, no compare tray, no saved map state).
- **Capture:** Chrome DevTools `Page.startScreencast` (JPEG, quality 92). A writer thread feeds the latest frame to ffmpeg at a constant 30 fps (`libx264 -preset veryfast -crf 18`). Playwright's built-in `recordVideo` is not used, because it's fixed at 1 Mb/s VP8 and looks blurry at 1080p.
- **Cursor:** headless Chromium draws no mouse, so an init script adds an arrow cursor that follows mouse events and a green click ripple. Mouse moves use smoothstep easing.
- **Timing:** each scene runs for at least `0.6 s lead + narration + 0.9 s tail`. Holds inside a scene shrink once the scene nears that length. Actions that still run past it make the scene longer, never shorter; the extra time is silent video at the end of the scene.
- **Assembly:** a 4.5 s title card and a 5 s end card with 0.5 s fades (rendered as HTML in the app's palette). The recording fades in and out of black. Each scene's voice clip starts at scene start + 0.6 s. Use-case labels (a dark-green chip, bottom-left) appear 0.3 s into each scene for 4.7 s, with 0.35 s fades. Overview and Summary scenes have no label.

## 6. Storyboard

Times are from the last test run, measured from the start of the recording; real-data runs will differ by a few seconds. "Narration" is the voice clip's length; "scene" is how long the scene ran. Narration text is verbatim from `narration.json`.

### s01_intro: no label (Overview)
- **Timing:** 0:00, narration 22.2 s, scene 23.7 s
- **On screen:** start page (list view, empty sidebar). The cursor drifts to the FlatFinder heading, then the "Set your limits…" hint, then the max-budget box.
- **Narration:** "Buying a resale flat in Singapore means juggling a budget, the remaining lease, and how close you'll be to the places you use every day. FlatFinder brings all of that into one search. It uses the last twelve months of HDB resale transactions from data dot gov dot S G, and it needs no account and no personal details. You just open it and start."

### s02_filters: UC-08 Filter Search Results
- **Timing:** 0:24, narration 17.6 s, scene 19.1 s
- **Clicks:** type `650000` in max budget; click the **4 Room** and **5 Room** chips; untick lease **Any** and set **Lease left** to 70; untick MRT **No limit** and set the MRT slider to 800 m.
- **Narration:** "Everything is set from the sidebar. I'll cap my budget at six hundred and fifty thousand dollars, pick four-room and five-room flats, and ask for at least seventy years of remaining lease. I can also limit how far I'm willing to walk. Here, the MRT must be within eight hundred metres."

### s03_weights: UC-01 Search Resale Flats
- **Timing:** 0:43, narration 15.8 s, scene 18.4 s
- **Clicks:** hover "Priority weights"; set MRT Stations 9, Hawker Centres 8, Child Care Centres 2; click **Find Matching Flats**. The results URL is saved for later scenes.
- **Narration:** "Next are the priority weights. Each amenity gets a score from one to ten for how much being close to it matters. MRT stations and hawker centres matter most to me, and child care barely matters, so I'll turn it down. Then, Find Matching Flats."

### s04_results: UC-09 Rank Search Results
- **Timing:** 1:01, narration 23.9 s, scene 26.8 s
- **On screen:** hover the match count, the first card's FIT badge, its resale price, and its bus-stop distance chip; scroll the results down about 1000 px and back up.
- **Narration:** "In well under a second, FlatFinder filters every matching transaction and ranks them by a Fit Score out of one hundred. The score blends price, remaining lease, and the distance to each amenity, weighted by the priorities I just set. Results are grouped by block, and each card shows the price, floor area, storey, lease, and the distance to the nearest bus stop, MRT, child care centre, hawker centre and CHAS clinic."

### s05_sort: UC-10 Sort Search Results
- **Timing:** 1:28, narration 11.0 s, scene 12.5 s
- **Clicks:** set the Sort select to `price-asc` with `select_option`. Native dropdowns don't render in headless, so the cursor only hovers it. The page reloads. Hover the first card's price, then set the sort back to the first option (Fit Score).
- **Narration:** "If I'd rather see the cheapest flats first, the sort menu reorders the same results by price, lease, or floor area, without changing what matched. I'll switch back to Fit Score."

### s06_searchbar: UC-07 Search via Search Bar
- **Timing:** 1:41, narration 18.3 s, scene 19.8 s
- **Clicks:** type `Bishan MRT` in the search bar and click **Search**. Hover the "Ranking includes distance to…" chip, the new **Near location** slider, and the first card. The anchored results URL replaces the saved one.
- **Narration:** "The search bar ranks results by distance to a place that matters to me, like my workplace or my parents' home. I'll type Bishan MRT. OneMap finds the location, a chip confirms it, and a new Near location weight appears in the sidebar. Flats closer to Bishan now move up the list."
- **Check with real data:** the chip appears (OneMap resolved the place), and the top results are plausibly nearer Bishan.

### s07_details: UC-02 View Flat Details
- **Timing:** 2:00, narration 15.0 s, scene 16.5 s
- **Clicks:** click the first card (its full-card "View details" link). Hover the building drawing, the Fit Score panel, and the "Remaining lease" row. The details URL is saved.
- **Narration:** "Selecting a card opens the block's details. On the left is the block, with the storeys that have sold highlighted. On the right, the Fit Score breakdown shows exactly how many points each factor contributed, so the ranking is never a black box."

### s08_details_more: UC-11 Find Nearest Amenity
- **Timing:** 2:17, narration 10.4 s, scene 13.6 s
- **On screen:** scroll down through Typical layout, Past transactions and Nearby amenities.
- **Narration:** "Further down, there's a typical layout for the flat type, every past transaction in the block, and the amenities within one kilometre, grouped by category and sorted by distance."

### s09_bookmark: UC-05 Bookmark Resale Flat
- **Timing:** 2:31, narration 5.0 s, scene 6.5 s
- **Clicks:** scroll back to the top; click the bookmark icon; hover **Saved (1)** in the header.
- **Narration:** "I like this one, so I'll bookmark it. The Saved counter in the header updates straight away."

### s10_flatmap: UC-03 Display Interactive Map
- **Timing:** 2:37, narration 15.1 s, scene 16.6 s
- **Clicks:** click **Open this block in Map View**; wait for amenity pins. The URL is saved for s17.
- **Narration:** "Opening this block in Map View centres the OneMap base map on the flat, with a one kilometre circle around it. Every bus stop, MRT exit, child care centre, hawker centre and CHAS clinic inside the circle is plotted in its own colour."
- **Check with real data:** OneMap tiles are visible behind the circle.

### s11_layers: UC-12 Toggle Amenity Layers
- **Timing:** 2:54, narration 9.6 s, scene 11.1 s
- **Clicks:** click the **Bus Stops** and **Child Care Centres** layer chips to hide them. They stay hidden for s12.
- **Narration:** "These layer toggles show or hide each category instantly, without asking the server again. I'll hide bus stops and child care centres to clear up the map."

### s12_walking: UC-04 Calculate Walking Distance
- **Timing:** 3:05, narration 16.9 s, scene 18.4 s
- **Clicks:** click the first MRT pin and wait (up to 10 s) for the popup's walking line to finish; hold. Press Escape, then click the first hawker centre pin and wait again.
- **Narration:** "Selecting an amenity asks the OneMap routing service for the real walking route. Here's the walk to the MRT station. The distance and time appear in the popup, and the route is drawn on the map, because a straight line can be misleading. Let's check the nearest hawker centre too."
- **Check with real data:** each popup shows "Walk: N m · about M min" (not "unavailable"), and the green route line is visible and not hidden behind the popup.

### s13_browse: UC-03 Display Interactive Map
- **Timing:** 3:23, narration 23.1 s, scene 32.8 s (about +8 s; see §8)
- **Clicks:** go to the saved results URL with `view=map`; click the zoom-out control until town-count bubbles appear; click the bubble whose title contains the first word of `FF_PLACE` ("Bishan"). Click the first result's **Show on map** button; click the side-panel arrow to hide the panels, then again to show them. Hover the block pin nearest the map centre and click it, which opens that block's details (UC-02's map entry point).
- **Narration:** "Map View also works for the whole result set. Zoomed out, each town shows how many flats match. Select a town, and its blocks appear as pins coloured by their best Fit Score, from dark green for the best fits down to red. Show on map highlights a result from the list, the arrow on the edge hides the side panels for a full-screen map, and clicking any pin opens that block's details."
- **Note:** real (non-approximate) block pins navigate straight to details on click; only approximate-location pins open a popup list. The narration matches this.

### s14_saved: UC-14 View Bookmarked Flats
- **Timing:** 3:56, narration 10.9 s, scene 13.2 s
- **Clicks:** go to the saved results URL with `view=list`; bookmark the first two cards that aren't already saved; click **Saved (3)** in the header; on the Saved page, click **Remove** on the last flat (the counter drops to 2).
- **Narration:** "Back in the list, I'll bookmark two more flats. The Saved page collects everything I've bookmarked in this session. Selecting the bookmark again removes a flat, so the list stays tidy."

### s15_compare: UC-15 Compare Flats
- **Timing:** 4:09, narration 20.1 s, scene 27.9 s (about +6 s)
- **Clicks:** go to the results list; click **Compare** on the first three cards; hover the tray; click the tray's **Compare** link. Hover the "… wins." banner; set the **Price** weight (`cw_price`) to 10; click **Update**; hover the banner again.
- **Narration:** "To decide between finalists, I add up to three flats to the compare tray at the bottom of the screen, then open Compare. The flats sit side by side, factor by factor, and FlatFinder names the winner. These weights can be adjusted too. If price matters more to me, I'll raise it and update, and the comparison is recalculated."

### s16_noresults: UC-01 Exception: no results
- **Timing:** 4:37, narration 13.0 s, scene 14.5 s
- **Clicks:** go to `/`; type `200000` as max budget; click **5 Room**; click **Find Matching Flats**. Hover "No flats match…" and the suggestions.
- **Narration:** "If a search is too strict, say a budget of two hundred thousand dollars for a five-room flat, FlatFinder doesn't just show an empty page. It explains that nothing matched and suggests which requirements to relax."
- **Check with real data:** that search really returns nothing. If real 5-room flats exist at or under $200k, lower the budget in both the script and the narration.

### s17_failure: UC-06 Handle API Failure / UC-13 Render Last Saved Map State
- **Timing:** 4:52, narration 19.4 s, scene 20.8 s
- **Setup:** the script blocks OneMap in the browser. It aborts tile requests and makes `/api/walking-distance` return 502 `{"error": "OneMap service currently unavailable. Please try again later."}`. The narration says this is a simulation.
- **Clicks:** open the results in Map View: the error banner appears and the map returns to the last successfully rendered view (from `MapState`). Hover the banner. Open the s10 flat's Map View and click the MRT pin: the popup shows "Walking distance unavailable." Click **Saved** to show the rest of the app still works.
- **Narration:** "Finally, what happens when OneMap goes down? For this demo, we block OneMap in the browser. A banner tells the user the service is unavailable, the map falls back to the last view that rendered successfully, and walking distances show as unavailable. Search, details, bookmarks and compare all keep working."

### s18_outro: no label (Summary)
- **Timing:** 5:12, narration 18.1 s, scene 19.6 s
- **Setup:** remove all routes (OneMap restored).
- **On screen:** open the results list; slow scroll.
- **Narration:** "That's FlatFinder. Filter and rank flats by what matters to you, explore them on the map, check real walking routes, then save and compare your shortlist. It's built with Django, PostgreSQL, Leaflet and OneMap, and backed by one hundred and sixty automated tests. Thanks for watching."
- **Check:** the README says 160 tests. Run `pytest -q` to confirm the count is still right, and update the narration if not.

The end card reads "Thanks for watching", the feature list, the tech stack and `github.com/CCCaLebF/FlatFinder`.

## 7. What to check before handing it over

Extract frames (for example `ffmpeg -ss <t> -i recording.mp4 -frames:v 1 f.jpg`) at the midpoint and end of every scene, using `scenes.json`, and look at them:

- [ ] OneMap tiles render in s10, s12, s13 (not grey); the tiles are absent in s17 by design.
- [ ] s06: the anchor chip appears, so the search bar found the place.
- [ ] s12: both popups show a walking distance and minutes, and a route line is visible.
- [ ] s13: town bubbles appear after zooming out; pins appear after selecting the town; the scene ends on a flat details page.
- [ ] s14: the counter goes 1 → 3 → 2 and the Saved page lists the flats.
- [ ] s15: the compare page shows three flats and a winner, before and after Update.
- [ ] s16: "No flats match your requirements" appears.
- [ ] `log.txt` ends with `failed scenes: none`.
- [ ] After assembly: total length between 5:00 and 7:00; voice lines start as their scenes start (spot-check s03, s12, s17); loudness about −16 LUFS (`ffmpeg -i out.mp4 -af ebur128 -f null -`).
- [ ] What each narration says matches what's on screen. If the real data changes something (for example the top result isn't near Bishan), edit `narration.json`, re-run `tts.py` for those scenes, then re-record.

## 8. Known issues and decisions

- **Two scenes run long:** s13 by about 8 s and s15 by about 6 s, because their actions (zooming, three compare clicks, two page loads) take longer than their narration. The result is a short silent hold at the end of each. To tighten it, either lengthen those narrations a little and re-voice them, or remove an action. Don't shorten the holds below about 0.5 s or the actions become hard to follow.
- **The compare tray stays open** (3 of 3) from s15 to the end. That's intended: it shows tray state persisting. To hide it, click the tray's **Clear** at the end of s15.
- **UC-06 is simulated in the browser** with Playwright routes, not by stopping OneMap. The narration says so. The README's alternative (restart the server with `ONEMAP_BASE_URL=http://127.0.0.1:9`) would need a server restart mid-recording.
- **Bishan town bubble:** s13 clicks the bubble whose title matches the first word of `FF_PLACE`, falling back to the first bubble. If the place changes, choose one with a matching town.
- **Flats without coordinates** don't appear on the map; approximate-location pins open a popup list instead of navigating. The demo doesn't rely on either.
- **Security, not part of the video:** the committed `.env.example` contains what look like real OneMap account details. Remind the user to change that OneMap password and replace the values with placeholders. Don't copy them anywhere.

## 9. Files

| File | What it does |
|---|---|
| `scripts/demo/narration.json` | Scene ids, on-screen labels (`uc`) and narration text. This is the source of truth for the voiceover. |
| `scripts/demo/tts.py` | Kokoro TTS: downloads the model on first run, writes `vo/<scene>.wav` and `vo/durations.json`. |
| `scripts/demo/record_demo.py` | The recorder: storyboard actions, cursor overlay, screencast to H.264, `scenes.json`. Environment variables: `FF_URL`, `FF_OUT`, `FF_PLACE`, `FF_DEV` (dev only). |
| `scripts/demo/assemble.py` | Title and end cards, use-case labels, voice track, final MP4 and `.srt`. Options: `--title`, `--subtitle`, `--team`. |
| `scripts/demo/dev/devroutes.py` | Dev only: offline CDN copies, grey tiles, fake OneMap responses (`FF_DEV=1`). Not for the real recording. |
| `scripts/demo/dev/seed_dev.py` | Dev only: synthetic transactions and amenities on the real block coordinates, for when data.gov.sg is unreachable. |
| `scripts/demo/.gitignore` | Keeps models, voice clips, recordings and builds out of git. |
