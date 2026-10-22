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
      setStatus(data.total.toLocaleString("en-SG") + " matching flats · zoom in or select a town to see flats");
    }

    // Flat pins on the map, by location: {marker, signature}. A redraw keeps a pin whose
    // location and flats haven't changed and only touches the rest, so panning stays smooth
    // (redrawing every pin froze the page for 80–150 ms at the pin limit).
    var pinMarkers = {};

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
            h("h3", {}, data.count === 1 ? "1 matching flat" : data.count.toLocaleString("en-SG") + " matching flats here"),
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

    /** displayFlatPins(flats): FR 2.1.2 / 2.2.1 — one pin per location, best Fit Score first. */
    function displayFlatPins(data) {
      var next = {};
      data.locations.forEach(function (loc) {
        var key = loc.lat + "," + loc.lng;
        var signature = loc.count + "|" + loc.approximate + "|" + loc.fit + "|" + loc.price;
        var current = pinMarkers[key];
        if (current && current.signature === signature) {
          next[key] = current;
          delete pinMarkers[key];  // whatever is left in pinMarkers afterwards is removed
          return;
        }
        var approx = loc.approximate ? " ff-pin--approx" : "";
        var band = " " + fitBandClass(loc.fit);  // the location's best flat
        var icon = loc.count === 1
          ? priceTagIcon(approx.replace("ff-pin", "ff-price") + band, shortPrice(loc.price))
          : pinIcon(approx + band, loc.count > 99 ? "99+" : String(loc.count));
        var popup = h("div", { className: "ff-popup" }, h("p", {}, "Loading flats…"));
        var marker = addLabelledMarker([loc.lat, loc.lng], icon, { title: loc.count + " matching flat(s)" }, pinLayer)
          .bindPopup(popup, { maxWidth: 300 });
        marker.on("popupopen", function () { fillLocationPopup(loc, popup, marker); });
        next[key] = { marker: marker, signature: signature };
      });
      // Pins that left the view, or whose flats changed (their replacement was added above).
      Object.keys(pinMarkers).forEach(function (key) { pinLayer.removeLayer(pinMarkers[key].marker); });
      pinMarkers = next;
      var shown = data.locations.reduce(function (sum, loc) { return sum + loc.count; }, 0);
      setStatus(data.truncated
        ? "Showing " + shown.toLocaleString("en-SG") + " of " + data.total.toLocaleString("en-SG") + " flats in view · zoom in for more"
        : data.total === 0 ? "No matching flats with a location in this area"
        : data.total.toLocaleString("en-SG") + " matching flats in view");
    }

    /** displayBookmarkPins(flats): UC-03.AC.1 — saved flats get their own pins. */
    function displayBookmarkPins(flats) {
      savedLayer.clearLayers();
      flats.forEach(function (f) {
        L.marker([f.lat, f.lng], { icon: pinIcon("ff-pin--saved", "★"), title: "Saved flat", zIndexOffset: 500 })
          .bindPopup(h("div", { className: "ff-popup" },
            h("h3", {}, "Saved flat"),
            f.approximate ? h("p", { className: "ff-note" }, "Approximate location (town centre)") : null,
            h("ul", {}, flatLine(f, origin))), { maxWidth: 300 })
          .addTo(savedLayer);
      });
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

    // UC-07: the search-bar location, if one is set.
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
    }

    /**
     * selectFlatPin: "Show on map" on a side-list card centres the map on that flat, or that
     * block (PLAN §11), and marks it with its own highlighted pin and open popup. The pin is
     * separate from the flat pins, so it shows even when the block's pin is cut by the pin limit.
     */
    var focusMarker = null;
    function selectFlatPin(button) {
      var d = button.dataset;
      var isBlock = d.kind === "block";
      var lat = parseFloat(d.lat), lng = parseFloat(d.lng);
      if (focusMarker) map.removeLayer(focusMarker);
      document.querySelectorAll(".ff-card--focus").forEach(function (card) {
        card.classList.remove("ff-card--focus");
      });
      var card = button.closest("[data-flat-card], [data-block-card]");
      if (card) card.classList.add("ff-card--focus");
      var priceText = price(parseFloat(d.price))
        + (isBlock && d.priceMax !== d.price ? " – " + price(parseFloat(d.priceMax)) : "");

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
              (isBlock ? "up to " : "") + d.fit) : null,
            h("a", { href: d.detailsUrl }, d.label),
            h("p", {}, d.summary + " · " + priceText))),
          isBlock ? h("p", { className: "ff-note" }, h("a", { href: d.detailsUrl }, "View each flat in this block")) : null),
          { maxWidth: 300 });
      focusMarker.on("add", function () {
        focusMarker.getElement().querySelector(".ff-pin span").textContent = icon.label;
      });
      focusMarker.addTo(map).openPopup();
    }

    // A short pause after the map stops, so a quick series of moves makes one request.
    map.on("moveend", function () { clearTimeout(timer); timer = setTimeout(load, 100); });
    document.addEventListener("flatfinder:bookmark-changed", loadSaved);
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-show-on-map]");
      if (button) selectFlatPin(button);
    });
    load();
    loadSaved();
  }

  // --- Flat: the flat, its 1 km circle and amenity layers (UC-11, UC-12) --------------------

  function initFlat() {
    var flatId = el.dataset.flatId;
    var toggles = document.querySelectorAll("[data-layer-toggle]");
    var layers = {};
    displayMap(DEFAULT_VIEW.centre[0], DEFAULT_VIEW.centre[1], DEFAULT_VIEW.zoom);

    /** toggleLayer(type, visible): UC-12 — show or hide pins already fetched; no new request. */
    function toggleLayer(type, visible) {
      if (!layers[type]) return;
      if (visible) layers[type].addTo(map); else map.removeLayer(layers[type]);
      FF.MapState.save({
        visibleLayers: CATEGORY_KEYS.filter(function (k) { return layers[k] && map.hasLayer(layers[k]); }),
      });
    }

    /** selectAmenityPin(amenity): UC-04 step 1 — ask for the walking distance once per pin. */
    function selectAmenityPin(item, line, flat) {
      if (line.dataset.state === "done" || line.dataset.state === "loading") return;
      line.dataset.state = "loading";
      line.textContent = "Walking distance: calculating…";
      var params = new URLSearchParams({ flat_id: flat.id, lat: item.lat, lng: item.lng });
      fetch("/api/walking-distance?" + params, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (response) {
          return response.json().then(function (body) { return { ok: response.ok, status: response.status, body: body }; });
        })
        .then(function (res) { displayWalkingDistance(line, res); })
        .catch(function () { displayWalkingDistance(line, { ok: false, status: 0, body: {} }); });
    }

    /** displayWalkingDistance(amenity, metres): UC-04 step 4, or UC-06 on failure. */
    function displayWalkingDistance(line, res) {
      if (!res.ok) {
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
    displayMap(DEFAULT_VIEW.centre[0], DEFAULT_VIEW.centre[1], DEFAULT_VIEW.zoom);
    function load() {
      getJSON("/api/bookmarks").then(function (data) {
        layer.clearLayers();
        var points = [];
        data.flats.forEach(function (f) {
          points.push([f.lat, f.lng]);
          L.marker([f.lat, f.lng], { icon: pinIcon("ff-pin--saved", "★"), title: "Saved flat" })
            .bindPopup(h("div", { className: "ff-popup" },
              f.approximate ? h("p", { className: "ff-note" }, "Approximate location (town centre)") : null,
              h("ul", {}, flatLine(f, "saved"))), { maxWidth: 300 })
            .addTo(layer);
        });
        if (points.length) map.fitBounds(L.latLngBounds(points).pad(0.3), { maxZoom: 16 });
        setStatus(data.count === 0 ? "No saved flats yet"
          : points.length < data.count ? (data.count - points.length) + " saved flat(s) have no location and aren't shown" : "");
      }).catch(function () { setStatus("Couldn't load your saved flats for the map."); });
    }
    document.addEventListener("flatfinder:bookmark-changed", load);
    load();
  }

  if (mode === "flat") initFlat();
  else if (mode === "saved") initSaved();
  else initBrowse();
})();
