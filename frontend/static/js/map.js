/**
 * «Boundary» MapUI — the Leaflet map (UC-03, UC-04, UC-06, UC-11, UC-12, UC-13).
 *
 * Function names follow the MapUI class in the class diagram (displayMap, displayAreaCounts,
 * displayFlatPins, displayBookmarkPins, displayAmenityPins, selectFlatPin, selectAmenityPin,
 * displayWalkingDistance, toggleLayer, displayErrorMessage, displayBlankMap). switchToListView
 * is the header's List View link (mapstate.js remembers the choice).
 *
 * The map element's `data-map-mode` picks what is drawn:
 *  - "browse" (Start / Results, Map View): town counts below zoom 14 (FR 2.1.1), matching flats
 *    as pins from zoom 14 (FR 2.1.2), and saved flats as their own pins (UC-03.AC.1).
 *  - "flat" (Details, Map View): the flat, a 1 km circle and amenity pins, one toggleable
 *    layer per category (UC-11, UC-12; toggling never re-fetches); selecting a pin asks
 *    OneMap for the walking distance (UC-04).
 *  - "saved" (Saved, Map View): the saved flats.
 * All text from the server is inserted with textContent, never as HTML.
 */
(function () {
  "use strict";

  var el = document.getElementById("map");
  if (!el || !window.L) return;

  var FF = window.FlatFinder;
  var cfg = JSON.parse(document.getElementById("map-config").textContent);
  var SINGAPORE = L.latLngBounds([1.144, 103.535], [1.494, 104.502]);
  var DEFAULT_VIEW = { centre: [1.3521, 103.8198], zoom: 12 };
  var CATEGORY_KEYS = ["bus_stop", "mrt_station", "child_care_centre", "hawker_centre", "chas_clinic"];
  var mode = el.dataset.mapMode;

  var map = L.map(el, {
    minZoom: cfg.minZoom, maxZoom: cfg.maxZoom,
    maxBounds: SINGAPORE.pad(0.15), maxBoundsViscosity: 0.8,
  });
  // No detectRetina: on high-DPI screens it asks for one zoom level more than the map shows
  // and caps the layer one level lower, so the top zoom (19, OneMap's last) went grey.
  var tiles = L.tileLayer(cfg.tileUrl, {
    attribution: cfg.attribution, minZoom: cfg.minZoom, maxZoom: cfg.maxZoom,
  }).addTo(map);
  FF.map = map;

  // --- Small helpers --------------------------------------------------------------------

  /** Build a DOM element: h("a", {href: "/x", className: "y"}, "text", childNode, ...). */
  function h(tag, attrs) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) { node[key] = attrs[key]; });
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child === null || child === undefined || child === false) continue;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  var ACRONYMS = ["MRT", "LRT", "CHAS", "HDB", "NTUC", "PCF", "PTE", "LTD", "CC", "RC"];
  /** ALL-CAPS dataset names -> readable, matching the display_name template filter. */
  function displayName(text) {
    if (text !== text.toUpperCase()) return text;
    return text.split(/\s+/).map(function (word) {
      var core = word.replace(/[().,&'-]/g, "");
      if (ACRONYMS.indexOf(core) >= 0 || /\d/.test(core)) return word;
      return word.charAt(0) + word.slice(1).toLowerCase();
    }).join(" ");
  }

  function price(value) { return "S$" + Math.round(value).toLocaleString("en-SG"); }
  function shortPrice(value) {
    return value >= 1e6 ? "S$" + (value / 1e6).toFixed(2).replace(/\.?0+$/, "") + "M" : "S$" + Math.round(value / 1000) + "K";
  }
  /** A stable key for a location, so template data and API floats match exactly. */
  function latLngKey(lat, lng) { return Number(lat).toFixed(6) + "," + Number(lng).toFixed(6); }

  /** Decode OneMap's encoded polyline (precision 5) into [[lat, lng], ...]. */
  function decodePolyline(encoded) {
    if (typeof encoded !== "string" || !encoded) return [];
    var points = [], index = 0, lat = 0, lng = 0;
    while (index < encoded.length) {
      var shift = 0, result = 0, byte;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20);
      lat += result & 1 ? ~(result >> 1) : result >> 1;
      shift = 0; result = 0;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20);
      lng += result & 1 ? ~(result >> 1) : result >> 1;
      points.push([lat / 1e5, lng / 1e5]);
    }
    return points.filter(function (point) { return isFinite(point[0]) && isFinite(point[1]); });
  }

  function getJSON(url, signal) {
    return fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin", signal: signal })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      });
  }

  var statusBox = document.querySelector("[data-map-status]");
  function setStatus(text) {
    if (!statusBox) return;
    statusBox.textContent = text || "";
    statusBox.classList.toggle("hidden", !text);
  }

  /** The search part of the page URL (no view/page/sort/from), for API calls and detail links. */
  function searchParams() {
    var params = new URLSearchParams(window.location.search);
    ["view", "page", "sort", "from"].forEach(function (key) { params.delete(key); });
    return params;
  }

  function detailsUrl(flatId, origin) {
    var params = origin === "saved" ? new URLSearchParams() : searchParams();
    params.set("from", origin);
    params.set("view", "map");
    return "/flats/" + flatId + "/?" + params.toString();
  }

  function pinIcon(classes, label) {
    return L.divIcon({
      className: "", iconSize: [28, 28], iconAnchor: [14, 28], popupAnchor: [0, -26],
      html: '<div class="ff-pin ' + classes + '"><span>' + (label || "") + "</span></div>",
    });
  }

  var HOUSE_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>';

  /** A block pin: the pin shape with a house drawing instead of a number. */
  function houseIcon(classes) {
    return L.divIcon({
      className: "", iconSize: [28, 28], iconAnchor: [14, 28], popupAnchor: [0, -26],
      html: '<div class="ff-pin ' + classes + '">' + HOUSE_SVG + "</div>",
    });
  }

  /**
   * The colour class for a pin's best Fit Score: ff-fit-1 (dark green, best) to ff-fit-6 (red),
   * from cfg.fitBands (MAP_FIT_COLOUR_BANDS, each a band's lower bound). No score: ff-fit-none.
   */
  function fitBandClass(fit) {
    if (fit === null || fit === undefined) return "ff-fit-none";
    for (var i = 0; i < cfg.fitBands.length; i++) {
      if (fit >= cfg.fitBands[i]) return "ff-fit-" + (i + 1);
    }
    return "ff-fit-" + (cfg.fitBands.length + 1);
  }

  /** A price tag pin for a location with a single flat, as in the Results (Map View) mockup. */
  function priceTagIcon(classes, text) {
    var icon = L.divIcon({
      className: "", iconSize: null, iconAnchor: [0, 0], popupAnchor: [0, -14],
      html: '<div class="ff-price ' + classes + '"></div>',
    });
    icon.label = text;  // filled in with textContent once the marker is on the map
    return icon;
  }

  function addLabelledMarker(latlng, icon, options, layer) {
    var marker = L.marker(latlng, Object.assign({ icon: icon }, options));
    if (icon.label) {
      marker.on("add", function () { marker.getElement().firstChild.textContent = icon.label; });
    }
    return marker.addTo(layer);
  }

  function flatLine(flat, origin) {
    return h("li", {},
      flat.fit !== null && flat.fit !== undefined ? h("span", { className: "ff-fit", title: "Fit Score" }, flat.fit.toFixed(1)) : null,
      h("a", { href: detailsUrl(flat.id, origin) }, "Blk " + flat.block + " " + displayName(flat.street)),
      h("p", {}, displayName(flat.flatType) + " · " + price(flat.price) + (flat.storey ? " · storey " + flat.storey.toLowerCase() : "")));
  }

  // --- MapUI operations (class diagram names) ----------------------------------------------

  /** displayMap(centreLat, centreLng, zoom) */
  function displayMap(centreLat, centreLng, zoom) {
    map.setView([centreLat, centreLng], Math.max(zoom, cfg.minZoom));
  }

  /** displayErrorMessage(message): the UC-06 banner; the rest of the page keeps working. */
  function displayErrorMessage(message) {
    if (FF.showError) FF.showError(message);
  }

  /** displayBlankMap(): UC-13.EX.1 — no saved state to fall back on, so drop the broken tiles. */
  function displayBlankMap() {
    if (map.hasLayer(tiles)) map.removeLayer(tiles);
  }

  /**
   * createFocusController(adapter): the shared "Show on map" focus pin (UC-09 / PLAN §11).
   * The adapter hides the pin(s) already at the selected location so the teardrop never
   * sits on top of one, and puts them back when the focus clears or the pins redraw:
   *   adapter.hide({lat, lng, flatId})  hide the matching pins
   *   adapter.restore()                 restore them
   *   adapter.refresh()                 hide them again after a redraw
   */
  function createFocusController(adapter) {
    var focusMarker = null;
    var active = null;

    function clearCardFocus() {
      document.querySelectorAll(".ff-card--focus").forEach(function (card) {
        card.classList.remove("ff-card--focus");
      });
    }

    function clear() {
      var marker = focusMarker;
      focusMarker = null;  // before removeLayer, so its popupclose does not clear twice
      if (marker) map.removeLayer(marker);
      if (active) {
        adapter.restore();
        active = null;
      }
      clearCardFocus();
    }

    function refresh() {
      if (active) adapter.refresh();
    }

    function select(button) {
      var d = button.dataset;
      var lat = parseFloat(d.lat), lng = parseFloat(d.lng);
      if (isNaN(lat) || isNaN(lng)) return;
      clear();
      active = { lat: lat, lng: lng, flatId: d.flatId || null };
      adapter.hide(active);

      var isBlock = d.kind === "block";
      var card = button.closest("[data-flat-card], [data-block-card]");
      if (card) card.classList.add("ff-card--focus");

      var priceText = price(parseFloat(d.price))
        + (isBlock && d.priceMax !== d.price ? " – " + price(parseFloat(d.priceMax)) : "");
      var detail = [d.summary, priceText, d.storey].filter(Boolean).join(" · ");

      var icon = L.divIcon({
        className: "", iconSize: [40, 40], iconAnchor: [20, 40], popupAnchor: [0, -38],
        html: '<div class="ff-focus"><div class="ff-pin ff-pin--focus"><span></span></div></div>',
      });
      icon.label = shortPrice(parseFloat(d.price));
      displayMap(lat, lng, Math.max(map.getZoom(), 16));
      focusMarker = L.marker([lat, lng], { icon: icon, title: d.label, zIndexOffset: 1000, keyboard: true })
        .bindPopup(h("div", { className: "ff-popup" },
          h("h3", {}, isBlock ? "Selected block" : "Selected flat"),
          h("ul", {}, h("li", {},
            d.fit ? h("span", { className: "ff-fit", title: isBlock ? "Best Fit Score" : "Fit Score" },
              d.fit) : null,
            h("a", { href: d.detailsUrl }, d.label),
            h("p", {}, detail))),
          isBlock ? h("p", { className: "ff-note" }, h("a", { href: d.detailsUrl }, "View details")) : null),
          { maxWidth: 300 });
      focusMarker.on("add", function () {
        var element = focusMarker.getElement();
        element.querySelector(".ff-pin span").textContent = icon.label;
        // Clicking the focused pin itself must not reach the map's preclick, which would
        // close its popup and clear the focus.
        element.addEventListener("click", function (event) { event.stopPropagation(); });
      });
      focusMarker.addTo(map).openPopup();
    }

    map.on("click", clear);
    map.on("popupclose", function (event) {
      if (focusMarker && event.popup === focusMarker.getPopup()) clear();
    });

    return { select: select, clear: clear, refresh: refresh };
  }

  // --- UC-06 / UC-13: base-map tiles from OneMap ----------------------------------------
  // A view is saved to MapState only once its tiles have rendered (see below), so MapState
  // always holds the last *successfully rendered* map (FR 1.2.1.2). If tiles fail, show the
  // banner and go back to that view once (its tiles may still be in the browser cache);
  // with no saved view, show a blank map with the banner (UC-13.EX.1).
  // OneMap answers 200 with an empty body where it has no map (open sea, outside Singapore),
  // which the browser reports as a tile error too. So failed tiles alongside loaded ones are
  // normal; if none loaded, re-fetch one failed tile (OneMap allows CORS) and only a network
  // failure or an error status counts as OneMap being unavailable.
  var tileErrors = 0;
  var tilesLoaded = 0;
  var failedTileUrl = null;
  var restoring = false;
  var rememberView = mode === "browse";
  tiles.on("loading", function () { tileErrors = 0; tilesLoaded = 0; failedTileUrl = null; });
  tiles.on("tileerror", function (e) {
    tileErrors += 1;
    failedTileUrl = failedTileUrl || e.tile.src;
  });
  tiles.on("tileload", function () { tilesLoaded += 1; });
  tiles.on("load", function () {
    if (tileErrors === 0 || tilesLoaded > 0) return tilesRendered();
    fetch(failedTileUrl, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        tilesRendered();
      })
      .catch(tilesUnavailable);
  });

  function tilesRendered() {
    restoring = false;
    if (rememberView) {
      var c = map.getCenter();
      FF.MapState.save({ centre: [c.lat, c.lng], zoom: map.getZoom() });
    }
  }

  function tilesUnavailable() {
    displayErrorMessage("OneMap service currently unavailable. The map may not display correctly.");
    var last = rememberView ? FF.MapState.lastView() : null;
    if (last && !restoring) {
      restoring = true;
      displayMap(last.centre[0], last.centre[1], last.zoom);
    } else if (!last) {
      displayBlankMap();
    }
  }

  // --- Side panels: hide them so the map fills the window -------------------------------
  // The panels beside the map (filters, results or saved list, flat details) carry
  // data-side-panel. A round handle sits on their edge, halfway down: its arrow points left
  // to hide them and right to show them. The choice is kept in MapState, across pages.
  if (document.querySelector("[data-side-panel]")) {
    var root = document.documentElement;
    var panelToggle = h("button", { type: "button", className: "ff-panel-toggle" },
      h("span", { className: "ff-panel-toggle__icon" }));
    panelToggle.addEventListener("click", function () { setPanelsHidden(!root.dataset.panelsHidden); });
    el.parentElement.appendChild(panelToggle);  // beside #map, so it can overlap the panel edge

    var updatePanelToggle = function () {
      var label = root.dataset.panelsHidden ? "Show side panels" : "Hide side panels to see the whole map";
      panelToggle.setAttribute("aria-label", label);
      panelToggle.title = label;
      panelToggle.setAttribute("aria-expanded", String(!root.dataset.panelsHidden));
    };
    var setPanelsHidden = function (hidden) {
      if (hidden) root.dataset.panelsHidden = "1"; else delete root.dataset.panelsHidden;
      FF.MapState.save({ panelsHidden: hidden });
      updatePanelToggle();
      map.invalidateSize();  // the map's box changed; this also reloads pins for the new area
    };
    updatePanelToggle();
  }

  // --- Browse: area counts, flat pins, saved flats ----------------------------------------

  function initBrowse() {
    var origin = el.dataset.origin || "start";
    var search = searchParams();
    var areaLayer = L.layerGroup().addTo(map);
    var pinLayer = L.layerGroup().addTo(map);
    var savedLayer = L.layerGroup().addTo(map);
    var areaCache = null;
    var pending = null;
    var timer = null;

    var last = FF.MapState.lastView() || DEFAULT_VIEW;
    displayMap(last.centre[0], last.centre[1], last.zoom);

    /** displayAreaCounts(counts): FR 2.1.1 — matching flats per town, at its centre. */
    function displayAreaCounts(data) {
      areaLayer.clearLayers();
      data.areas.forEach(function (area) {
        var size = Math.min(72, 34 + Math.sqrt(area.count) * 1.1);
        var icon = L.divIcon({
          className: "", iconSize: [size, size],
          html: '<div class="ff-area" style="width:' + size + "px;height:" + size + 'px"><div></div></div>',
        });
        var marker = L.marker([area.lat, area.lng], { icon: icon, title: displayName(area.town), keyboard: true });
        marker.on("add", function () {
          var inner = marker.getElement().querySelector(".ff-area > div");
          inner.appendChild(document.createTextNode(area.count.toLocaleString("en-SG")));
          inner.appendChild(h("small", {}, displayName(area.town)));
        });
        marker.on("click", function () { displayMap(area.lat, area.lng, cfg.pinMinZoom); });
        areaLayer.addLayer(marker);
      });
      setStatus(data.total.toLocaleString("en-SG") + " past sales · zoom in or select a town to see blocks");
    }

    // Flat pins on the map, by location: {marker, signature}. A redraw keeps a pin whose
    // location and flats haven't changed and only touches the rest, so panning stays smooth
    // (redrawing every pin froze the page for 80–150 ms at the pin limit).
    var pinMarkers = {};
    var savedMarkers = {};       // saved flat id -> {marker, lat, lng, hidden}
    var hiddenPins = new Set();  // locations hidden under the focus pin
    var hiddenSaved = new Set(); // saved flat ids hidden under the focus pin
    var focusKey = null;         // the focused location, kept so redraws can re-hide it
    var focus;                   // createFocusController(), shared with the saved map

    function clearFlatPins() {
      pinLayer.clearLayers();
      pinMarkers = {};
    }

    /**
     * A pin's popup: its matching flats, best Fit Score first (FR 2.2.1). Fetched the first time
     * the popup opens rather than sent with every pin, which kept the pins response small.
     */
    function fillLocationPopup(loc, popup, marker) {
      if (popup.dataset.loaded) return;
      var params = new URLSearchParams(search);
      params.set("lat", loc.lat);
      params.set("lng", loc.lng);
      getJSON("/api/flats/at-location?" + params)
        .then(function (data) {
          var list = h("ul", {});
          data.flats.forEach(function (f) { list.appendChild(flatLine(f, origin)); });
          popup.replaceChildren(
            h("h3", {}, data.count === 1 ? "1 past sale" : data.count.toLocaleString("en-SG") + " past sales here"),
            data.approximate ? h("p", { className: "ff-note" }, "Approximate location (town centre)") : "",
            list,
            data.count > data.flats.length
              ? h("p", { className: "ff-note" }, "Showing the best " + data.flats.length + ". Use List View to see all " + data.count.toLocaleString("en-SG") + ".")
              : "");
          popup.dataset.loaded = "1";
        })
        .catch(function () {
          popup.replaceChildren(h("p", {}, "Couldn't load these flats. Close this and try again."));
        })
        .then(function () { marker.getPopup().update(); });  // resize to the new content
    }

    /**
     * displayFlatPins(flats): FR 2.1.2 / 2.2.1 — one pin per location, best Fit Score first.
     * A located block is one house pin that opens its block-level details page; an approximate
     * (town-centre) location holds several blocks, so it keeps the popup list instead.
     */
    function displayFlatPins(data) {
      var next = {};
      data.locations.forEach(function (loc) {
        var key = latLngKey(loc.lat, loc.lng);
        var signature = loc.id + "|" + loc.count + "|" + loc.approximate + "|" + loc.fit + "|" + loc.price;
        var current = pinMarkers[key];
        if (current && current.signature === signature) {
          next[key] = current;
          delete pinMarkers[key];  // whatever is left in pinMarkers afterwards is removed
          return;
        }
        var band = " " + fitBandClass(loc.fit);  // the location's best flat
        var title = loc.count === 1 ? "1 past sale" : loc.count.toLocaleString("en-SG") + " past sales";
        var marker;
        if (loc.approximate) {
          var icon = loc.count === 1
            ? priceTagIcon("ff-price--approx" + band, shortPrice(loc.price))
            : pinIcon("ff-pin--approx" + band, loc.count > 99 ? "99+" : String(loc.count));
          var popup = h("div", { className: "ff-popup" }, h("p", {}, "Loading flats…"));
          marker = addLabelledMarker([loc.lat, loc.lng], icon, { title: title }, pinLayer)
            .bindPopup(popup, { maxWidth: 300 });
          marker.on("popupopen", function () { fillLocationPopup(loc, popup, marker); });
        } else {
          marker = addLabelledMarker([loc.lat, loc.lng], houseIcon(band), { title: title, keyboard: true }, pinLayer);
          marker.on("click", function () { window.location.href = detailsUrl(loc.id, origin); });
        }
        next[key] = { marker: marker, signature: signature };
      });
      // Pins that left the view, or whose flats changed (their replacement was added above).
      Object.keys(pinMarkers).forEach(function (key) { pinLayer.removeLayer(pinMarkers[key].marker); });
      pinMarkers = next;
      syncSavedOverlap();          // keep saved locations clear after a redraw
      if (focus) focus.refresh();  // keep the focus location hidden after a redraw
      var shown = data.locations.reduce(function (sum, loc) { return sum + loc.count; }, 0);
      setStatus(data.truncated
        ? "Showing " + shown.toLocaleString("en-SG") + " of " + data.total.toLocaleString("en-SG") + " past sales in view · zoom in for more"
        : data.total === 0 ? "No matching past sales with a location in this area"
        : data.total.toLocaleString("en-SG") + " past sales in view");
    }

    /**
     * Saved pins take precedence over a matching pin at the same location: a result pin
     * and a ★ pin on top of each other obscure both. Keep the saved marker and hide the
     * matching one; restore it when the bookmark is removed (or the pin redraws).
     */
    function syncSavedOverlap() {
      var savedKeys = new Set();
      Object.keys(savedMarkers).forEach(function (id) {
        var saved = savedMarkers[id];
        savedKeys.add(latLngKey(saved.lat, saved.lng));
      });
      Object.keys(pinMarkers).forEach(function (key) {
        var pin = pinMarkers[key];
        if (savedKeys.has(key) || pin.hidden) {
          if (pinLayer.hasLayer(pin.marker)) pinLayer.removeLayer(pin.marker);
        } else if (!pinLayer.hasLayer(pin.marker)) {
          pinLayer.addLayer(pin.marker);
        }
      });
    }

    /** displayBookmarkPins(flats): UC-03.AC.1 — saved flats get their own pins. */
    function displayBookmarkPins(flats) {
      savedLayer.clearLayers();
      savedMarkers = {};
      flats.forEach(function (f) {
        var marker = L.marker([f.lat, f.lng], { icon: pinIcon("ff-pin--saved", "★"), title: "Saved flat", zIndexOffset: 500 })
          .bindPopup(h("div", { className: "ff-popup" },
            h("h3", {}, "Saved flat"),
            f.approximate ? h("p", { className: "ff-note" }, "Approximate location (town centre)") : null,
            h("ul", {}, flatLine(f, origin))), { maxWidth: 300 })
          .addTo(savedLayer);
        savedMarkers[String(f.id)] = { marker: marker, lat: f.lat, lng: f.lng, hidden: false };
      });
      syncSavedOverlap();          // a saved pin replaces the matching pin at its location
      if (focus) focus.refresh();  // the focused saved pin stays hidden after a reload
    }

    function load() {
      if (pending) pending.abort();
      pending = new AbortController();
      var signal = pending.signal;
      var done;
      if (map.getZoom() < cfg.pinMinZoom) {
        clearFlatPins();
        done = (areaCache ? Promise.resolve(areaCache) : getJSON("/api/flats/area-counts?" + search, signal))
          .then(function (data) { areaCache = data; displayAreaCounts(data); });
      } else {
        areaLayer.clearLayers();
        var b = map.getBounds();
        var params = new URLSearchParams(search);
        params.set("south", b.getSouth().toFixed(6));
        params.set("west", b.getWest().toFixed(6));
        params.set("north", b.getNorth().toFixed(6));
        params.set("east", b.getEast().toFixed(6));
        done = getJSON("/api/flats/in-bounds?" + params, signal).then(displayFlatPins);
      }
      done.catch(function (err) {
        if (err.name !== "AbortError") setStatus("Couldn't load flats for the map. Try moving the map again.");
      });
    }

    function loadSaved() {
      getJSON("/api/bookmarks")
        .then(function (data) { displayBookmarkPins(data.flats); })
        .catch(function () { /* saved pins are extra; the rest of the map still works */ });
    }

    // UC-07: the search-bar location, if one is set. Centre the map on it so the
    // searched block is visible immediately, at least at pin zoom.
    var anchorParams = new URLSearchParams(window.location.search);
    var anchorLat = parseFloat(anchorParams.get("anchor_lat"));
    var anchorLng = parseFloat(anchorParams.get("anchor_lng"));
    if (!isNaN(anchorLat) && !isNaN(anchorLng)) {
      L.marker([anchorLat, anchorLng], {
        icon: L.divIcon({ className: "", iconSize: [22, 22], html: '<div class="ff-anchor" aria-hidden="true"></div>' }),
        title: "Search location", zIndexOffset: 800,
      }).bindPopup(h("div", { className: "ff-popup" },
        h("h3", {}, "Search location"),
        h("p", {}, displayName(anchorParams.get("anchor_label") || "Selected location")))).addTo(map);
      displayMap(anchorLat, anchorLng, Math.max(map.getZoom(), cfg.pinMinZoom));
    }

    /** The browse focus adapter: matching pins by location, saved pins by flat. */
    function hideFocusPins(active) {
      focusKey = latLngKey(active.lat, active.lng);
      var pin = pinMarkers[focusKey];
      if (pin && !pin.hidden) {
        pinLayer.removeLayer(pin.marker);
        pin.hidden = true;
        hiddenPins.add(focusKey);
      }
      Object.keys(savedMarkers).forEach(function (id) {
        var saved = savedMarkers[id];
        if (!saved.hidden && latLngKey(saved.lat, saved.lng) === focusKey) {
          savedLayer.removeLayer(saved.marker);
          saved.hidden = true;
          hiddenSaved.add(id);
        }
      });
    }

    function restoreFocusPins() {
      hiddenPins.forEach(function (key) {
        var pin = pinMarkers[key];
        if (pin && pin.hidden) {
          pinLayer.addLayer(pin.marker);
          pin.hidden = false;
        }
      });
      hiddenPins.clear();
      hiddenSaved.forEach(function (id) {
        var saved = savedMarkers[id];
        if (saved && saved.hidden) {
          savedLayer.addLayer(saved.marker);
          saved.hidden = false;
        }
      });
      hiddenSaved.clear();
      focusKey = null;
      syncSavedOverlap();  // saved pins still replace matching pins after focus clears
    }

    function refreshFocusPins() {
      if (!focusKey) return;
      var pin = pinMarkers[focusKey];
      if (pin) {
        if (pinLayer.hasLayer(pin.marker)) pinLayer.removeLayer(pin.marker);
        pin.hidden = true;
        hiddenPins.add(focusKey);
      }
      Object.keys(savedMarkers).forEach(function (id) {
        var saved = savedMarkers[id];
        if (latLngKey(saved.lat, saved.lng) !== focusKey) return;
        if (savedLayer.hasLayer(saved.marker)) savedLayer.removeLayer(saved.marker);
        saved.hidden = true;
        hiddenSaved.add(id);
      });
    }

    focus = createFocusController({
      hide: hideFocusPins, restore: restoreFocusPins, refresh: refreshFocusPins,
    });

    // A short pause after the map stops, so a quick series of moves makes one request.
    map.on("moveend", function () { clearTimeout(timer); timer = setTimeout(load, 100); });
    document.addEventListener("flatfinder:bookmark-changed", loadSaved);
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-show-on-map]");
      if (button) focus.select(button);
    });
    load();
    loadSaved();
  }

  // --- Flat: the flat, its 1 km circle and amenity layers (UC-11, UC-12) --------------------

  function initFlat() {
    var flatId = el.dataset.flatId;
    var toggles = document.querySelectorAll("[data-layer-toggle]");
    var layers = {};
    var routeLayer = null;
    var activeWalkLine = null;
    var walkRequest = 0;
    displayMap(DEFAULT_VIEW.centre[0], DEFAULT_VIEW.centre[1], DEFAULT_VIEW.zoom);

    /** Remove the drawn route, if any. */
    function clearRouteLayer() {
      if (routeLayer) {
        map.removeLayer(routeLayer);
        routeLayer = null;
      }
    }

    /** UC-04: drop the route and put the popup's walking line back to its initial text. */
    function clearWalkingRoute() {
      walkRequest += 1;  // ignore a response that is still in flight
      clearRouteLayer();
      if (activeWalkLine) {
        activeWalkLine.dataset.state = "";
        activeWalkLine.textContent = "Walking distance: select to calculate";
        activeWalkLine = null;
      }
    }

    /** Draw OneMap's encoded route; the line is non-interactive so a click still clears it. */
    function drawWalkingRoute(encoded) {
      clearRouteLayer();
      var points = decodePolyline(encoded);
      if (!points.length) return;
      routeLayer = L.polyline(points, {
        color: "#287462", weight: 4, opacity: 0.9,
        lineCap: "round", lineJoin: "round", interactive: false, className: "ff-route",
      }).addTo(map);
    }

    map.on("click", clearWalkingRoute);
    map.on("popupclose", clearWalkingRoute);

    /** toggleLayer(type, visible): UC-12 — show or hide pins already fetched; no new request. */
    function toggleLayer(type, visible) {
      if (!layers[type]) return;
      if (visible) layers[type].addTo(map); else map.removeLayer(layers[type]);
      FF.MapState.save({
        visibleLayers: CATEGORY_KEYS.filter(function (k) { return layers[k] && map.hasLayer(layers[k]); }),
      });
    }

    /** selectAmenityPin(amenity): UC-04 step 1 — ask for the walking route when its popup opens. */
    function selectAmenityPin(item, line, flat) {
      if (line.dataset.state === "loading") return;
      clearWalkingRoute();
      activeWalkLine = line;
      var requestId = walkRequest;
      line.dataset.state = "loading";
      line.textContent = "Walking distance: calculating…";
      var params = new URLSearchParams({ flat_id: flat.id, lat: item.lat, lng: item.lng });
      fetch("/api/walking-distance?" + params, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (response) {
          return response.json().then(function (body) { return { ok: response.ok, status: response.status, body: body }; });
        })
        .then(function (res) {
          if (requestId === walkRequest) displayWalkingDistance(line, res);
        })
        .catch(function () {
          if (requestId === walkRequest) displayWalkingDistance(line, { ok: false, status: 0, body: {} });
        });
    }

    /** displayWalkingDistance(amenity, metres): UC-04 step 4, or UC-06 on failure. */
    function displayWalkingDistance(line, res) {
      if (!res.ok) {
        clearWalkingRoute();
        activeWalkLine = line;
        line.dataset.state = "failed";
        line.textContent = "Walking distance unavailable.";
        if (res.status === 502 || res.status === 0) displayErrorMessage(res.body.error);
        return;
      }
      line.dataset.state = "done";
      var text = "Walk: " + res.body.metres.toLocaleString("en-SG") + " m";
      if (res.body.minutes) text += " · about " + res.body.minutes + " min";
      if (res.body.fromTownCentre) text += " (from the town centre)";
      line.textContent = text;
      drawWalkingRoute(res.body.routeGeometry);
    }

    /** displayAmenityPins(amenities): UC-11 — one layer per category, coloured as in the legend. */
    function displayAmenityPins(categories, flat, visible) {
      categories.forEach(function (cat) {
        layers[cat.key] = L.layerGroup(cat.items.map(function (item) {
          var icon = L.divIcon({ className: "", iconSize: [14, 14], html: '<div class="ff-amenity ff-cat-' + cat.key + '"></div>' });
          var walk = h("p", { className: "ff-walk" }, "Walking distance: select to calculate");
          var popup = h("div", { className: "ff-popup" },
            h("h3", {}, displayName(item.name)),
            h("p", {}, cat.label.replace(/s$/, "") + (item.detail ? " · " + item.detail : "")),
            h("p", {}, "About " + item.distanceM.toLocaleString("en-SG") + " m away (straight line)"),
            walk);
          var marker = L.marker([item.lat, item.lng], { icon: icon, title: displayName(item.name) }).bindPopup(popup);
          marker.on("popupopen", function () { selectAmenityPin(item, walk, flat); });
          return marker;
        }));
        if (visible.indexOf(cat.key) >= 0) layers[cat.key].addTo(map);
      });
    }

    getJSON("/api/flats/" + flatId + "/amenities").then(function (data) {
      if (data.flat.lat === null) {
        setStatus("Location not available for this block, so it can't be shown on the map.");
        toggles.forEach(function (t) { t.disabled = true; });
        return;
      }
      var centre = [data.flat.lat, data.flat.lng];
      var circle = L.circle(centre, { radius: data.radiusM, color: "#287462", weight: 1.5, fillOpacity: 0.04 }).addTo(map);
      L.marker(centre, { icon: pinIcon(data.flat.approximate ? "ff-pin--approx" : "", ""), title: "This flat", zIndexOffset: 1000 })
        .bindPopup(h("div", { className: "ff-popup" },
          h("h3", {}, displayName(data.flat.label)),
          data.flat.approximate ? h("p", { className: "ff-note" }, "Approximate location (town centre)") : null))
        .addTo(map);
      map.fitBounds(circle.getBounds(), { padding: [10, 10] });

      var visible = FF.MapState.visibleLayers(CATEGORY_KEYS);
      displayAmenityPins(data.categories, data.flat, visible);

      toggles.forEach(function (toggle) {
        var key = toggle.dataset.layerToggle;
        var cat = data.categories.filter(function (c) { return c.key === key; })[0];
        toggle.checked = visible.indexOf(key) >= 0;
        var count = document.querySelector('[data-layer-count="' + key + '"]');
        if (count && cat) count.textContent = cat.items.length;
        toggle.addEventListener("change", function () { toggleLayer(key, toggle.checked); });
      });
      FF.amenityLayers = layers;
    }).catch(function () {
      setStatus("Couldn't load nearby amenities for the map.");
    });
  }

  // --- Saved: the saved flats --------------------------------------------------------------

  function initSaved() {
    var layer = L.layerGroup().addTo(map);
    var savedMarkers = {};       // saved flat id -> {marker, lat, lng, hidden}
    var hidden = new Set();      // saved flat ids hidden under the focus pin
    var focusKey = null;         // the focused location, kept so reloads can re-hide it
    var focus;
    displayMap(DEFAULT_VIEW.centre[0], DEFAULT_VIEW.centre[1], DEFAULT_VIEW.zoom);

    /** The saved-map focus adapter: hide every saved pin at the selected location. */
    function hideAt(active) {
      focusKey = latLngKey(active.lat, active.lng);
      Object.keys(savedMarkers).forEach(function (id) {
        var entry = savedMarkers[id];
        if (!entry.hidden && latLngKey(entry.lat, entry.lng) === focusKey) {
          layer.removeLayer(entry.marker);
          entry.hidden = true;
          hidden.add(id);
        }
      });
    }

    function restore() {
      hidden.forEach(function (id) {
        var entry = savedMarkers[id];
        if (entry && entry.hidden) {
          layer.addLayer(entry.marker);
          entry.hidden = false;
        }
      });
      hidden.clear();
      focusKey = null;
    }

    function refresh() {
      if (!focusKey) return;
      Object.keys(savedMarkers).forEach(function (id) {
        var entry = savedMarkers[id];
        if (latLngKey(entry.lat, entry.lng) !== focusKey) return;
        if (layer.hasLayer(entry.marker)) layer.removeLayer(entry.marker);
        entry.hidden = true;
        hidden.add(id);
      });
    }

    focus = createFocusController({ hide: hideAt, restore: restore, refresh: refresh });

    function load() {
      getJSON("/api/bookmarks").then(function (data) {
        layer.clearLayers();
        savedMarkers = {};
        var points = [];
        data.flats.forEach(function (f) {
          points.push([f.lat, f.lng]);
          var marker = L.marker([f.lat, f.lng], { icon: pinIcon("ff-pin--saved", "★"), title: "Saved flat" })
            .bindPopup(h("div", { className: "ff-popup" },
              f.approximate ? h("p", { className: "ff-note" }, "Approximate location (town centre)") : null,
              h("ul", {}, flatLine(f, "saved"))), { maxWidth: 300 })
            .addTo(layer);
          savedMarkers[String(f.id)] = { marker: marker, lat: f.lat, lng: f.lng, hidden: false };
        });
        focus.refresh();  // the focused saved pin stays hidden after a reload
        if (points.length) map.fitBounds(L.latLngBounds(points).pad(0.3), { maxZoom: 16 });
        setStatus(data.count === 0 ? "No saved flats yet"
          : points.length < data.count ? (data.count - points.length) + " saved flat(s) have no location and aren't shown" : "");
      }).catch(function () { setStatus("Couldn't load your saved flats for the map."); });
    }
    document.addEventListener("flatfinder:bookmark-changed", load);
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-show-on-map]");
      if (button) focus.select(button);
    });
    load();
  }

  if (mode === "flat") initFlat();
  else if (mode === "saved") initSaved();
  else initBrowse();
})();
