/**
 * «Boundary» MapUI — the Leaflet map (UC-03, UC-11, UC-12, UC-13).
 *
 * The map element's `data-map-mode` picks what is drawn:
 *  - "browse" (Start / Results, Map View): town counts below zoom 14 (FR 2.1.1), matching flats
 *    as pins from zoom 14 (FR 2.1.2), and saved flats as their own pins (UC-03.AC.1).
 *  - "flat" (Details, Map View): the flat, a 1 km circle and amenity pins, one toggleable
 *    layer per category (UC-11, UC-12; toggling never re-fetches).
 *  - "saved" (Saved, Map View): the saved flats.
 * The visible area and layers are kept in MapState (UC-13).
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

  var map = L.map(el, {
    minZoom: cfg.minZoom, maxZoom: cfg.maxZoom,
    maxBounds: SINGAPORE.pad(0.15), maxBoundsViscosity: 0.8,
  });
  var tiles = L.tileLayer(cfg.tileUrl, {
    attribution: cfg.attribution, minZoom: cfg.minZoom, maxZoom: cfg.maxZoom, detectRetina: true,
  }).addTo(map);
  FF.map = map;

  // --- UC-06 / UC-13: base-map tiles from OneMap ----------------------------------------
  // A view is saved to MapState only once its tiles have loaded without errors, so MapState
  // always holds the last *successfully rendered* map (FR 1.2.1.2). If tiles fail, show the
  // banner and go back to that view once (its tiles may still be in the browser cache);
  // with no saved view, the blank map stays with the banner (UC-13.EX.1).
  var tileErrors = 0;
  var restoring = false;
  var rememberView = el.dataset.mapMode === "browse";
  tiles.on("loading", function () { tileErrors = 0; });
  tiles.on("tileerror", function () { tileErrors += 1; });
  tiles.on("load", function () {
    if (tileErrors === 0) {
      restoring = false;
      if (rememberView) {
        var c = map.getCenter();
        FF.MapState.save({ centre: [c.lat, c.lng], zoom: map.getZoom() });
      }
      return;
    }
    if (FF.showError) FF.showError("OneMap service currently unavailable. The map may not display correctly.");
    var last = FF.MapState.lastView();
    if (!restoring && last && rememberView) {
      restoring = true;
      map.setView(last.centre, last.zoom);
    }
  });

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

  function flatLine(flat, origin) {
    return h("li", {},
      flat.fit !== null && flat.fit !== undefined ? h("span", { className: "ff-fit", title: "Fit Score" }, flat.fit.toFixed(1)) : null,
      h("a", { href: detailsUrl(flat.id, origin) }, "Blk " + flat.block + " " + displayName(flat.street)),
      h("p", {}, displayName(flat.flatType) + " · " + price(flat.price) + (flat.storey ? " · storey " + flat.storey.toLowerCase() : "")));
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
    map.setView(last.centre, Math.max(last.zoom, cfg.minZoom));

    function drawAreas(data) {
      areaLayer.clearLayers();
      data.areas.forEach(function (area) {
        var size = Math.min(72, 34 + Math.sqrt(area.count) * 1.1);
        var icon = L.divIcon({
          className: "", iconSize: [size, size],
          html: '<div class="ff-area" style="width:' + size + "px;height:" + size + 'px"><div></div></div>',
        });
        var marker = L.marker([area.lat, area.lng], { icon: icon, title: area.town, keyboard: true });
        marker.on("add", function () {
          var inner = marker.getElement().querySelector(".ff-area > div");
          inner.appendChild(document.createTextNode(area.count.toLocaleString("en-SG")));
          inner.appendChild(h("small", {}, displayName(area.town)));
        });
        marker.on("click", function () { map.setView([area.lat, area.lng], cfg.pinMinZoom); });
        areaLayer.addLayer(marker);
      });
      setStatus(data.total.toLocaleString("en-SG") + " matching flats · zoom in or click a town to see flats");
    }

    function drawPins(data) {
      pinLayer.clearLayers();
      data.locations.forEach(function (loc) {
        var classes = loc.approximate ? "ff-pin--approx" : "";
        var label = loc.count > 1 ? (loc.count > 99 ? "99+" : String(loc.count)) : "";
        var list = h("ul", {});
        loc.flats.forEach(function (f) { list.appendChild(flatLine(f, origin)); });
        var popup = h("div", { className: "ff-popup" },
          h("h3", {}, loc.count === 1 ? "1 matching flat" : loc.count.toLocaleString("en-SG") + " matching flats here"),
          loc.approximate ? h("p", { className: "ff-note" }, "Approximate location (town centre)") : null,
          list,
          loc.count > loc.flats.length
            ? h("p", { className: "ff-note" }, "Showing the best " + loc.flats.length + ". Use List View to see all " + loc.count.toLocaleString("en-SG") + ".")
            : null);
        L.marker([loc.lat, loc.lng], { icon: pinIcon(classes, label), title: loc.count + " flats" })
          .bindPopup(popup, { maxWidth: 300 }).addTo(pinLayer);
      });
      var shown = data.locations.reduce(function (sum, loc) { return sum + loc.count; }, 0);
      setStatus(data.truncated
        ? "Showing " + shown.toLocaleString("en-SG") + " of " + data.total.toLocaleString("en-SG") + " flats in view · zoom in for more"
        : data.total === 0 ? "No matching flats with a location in this area"
        : data.total.toLocaleString("en-SG") + " matching flats in view");
    }

    function load() {
      if (pending) pending.abort();
      pending = new AbortController();
      var signal = pending.signal;
      var done;
      if (map.getZoom() < cfg.pinMinZoom) {
        pinLayer.clearLayers();
        done = (areaCache ? Promise.resolve(areaCache) : getJSON("/api/flats/area-counts?" + search, signal))
          .then(function (data) { areaCache = data; drawAreas(data); });
      } else {
        areaLayer.clearLayers();
        var b = map.getBounds();
        var params = new URLSearchParams(search);
        params.set("south", b.getSouth().toFixed(6));
        params.set("west", b.getWest().toFixed(6));
        params.set("north", b.getNorth().toFixed(6));
        params.set("east", b.getEast().toFixed(6));
        done = getJSON("/api/flats/in-bounds?" + params, signal).then(drawPins);
      }
      done.catch(function (err) {
        if (err.name !== "AbortError") setStatus("Couldn't load flats for the map. Try moving the map again.");
      });
    }

    function loadSaved() {
      getJSON("/api/bookmarks").then(function (data) {
        savedLayer.clearLayers();
        data.flats.forEach(function (f) {
          L.marker([f.lat, f.lng], { icon: pinIcon("ff-pin--saved", "★"), title: "Saved flat", zIndexOffset: 500 })
            .bindPopup(h("div", { className: "ff-popup" },
              h("h3", {}, "Saved flat"),
              f.approximate ? h("p", { className: "ff-note" }, "Approximate location (town centre)") : null,
              h("ul", {}, flatLine(f, origin))), { maxWidth: 300 })
            .addTo(savedLayer);
        });
      }).catch(function () { /* saved pins are extra; the rest of the map still works */ });
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

    map.on("moveend", function () { clearTimeout(timer); timer = setTimeout(load, 200); });
    document.addEventListener("flatfinder:bookmark-changed", loadSaved);
    load();
    loadSaved();

    // Results Map View: "Show on map" on a side-list card.
    document.addEventListener("click", function (event) {
      var button = event.target.closest("[data-show-on-map]");
      if (!button) return;
      map.setView([parseFloat(button.dataset.lat), parseFloat(button.dataset.lng)], Math.max(map.getZoom(), 16));
    });
  }

  // --- Flat: the flat, its 1 km circle and amenity layers (UC-11, UC-12) --------------------

  function initFlat() {
    var flatId = el.dataset.flatId;
    var toggles = document.querySelectorAll("[data-layer-toggle]");
    map.setView(DEFAULT_VIEW.centre, DEFAULT_VIEW.zoom);

    getJSON("/api/flats/" + flatId + "/amenities").then(function (data) {
      if (data.flat.lat === null) {
        setStatus("Location not available for this block, so it can't be shown on the map.");
        toggles.forEach(function (t) { t.disabled = true; });
        return;
      }
      var centre = [data.flat.lat, data.flat.lng];
      var circle = L.circle(centre, { radius: data.radiusM, color: "#0d9488", weight: 1.5, fillOpacity: 0.04 }).addTo(map);
      L.marker(centre, { icon: pinIcon(data.flat.approximate ? "ff-pin--approx" : "", ""), title: "This flat", zIndexOffset: 1000 })
        .bindPopup(h("div", { className: "ff-popup" },
          h("h3", {}, displayName(data.flat.label)),
          data.flat.approximate ? h("p", { className: "ff-note" }, "Approximate location (town centre)") : null))
        .addTo(map);
      map.fitBounds(circle.getBounds(), { padding: [10, 10] });

      var visible = FF.MapState.visibleLayers(CATEGORY_KEYS);
      var layers = {};
      data.categories.forEach(function (cat) {
        layers[cat.key] = L.layerGroup(cat.items.map(function (item) {
          var icon = L.divIcon({ className: "", iconSize: [14, 14], html: '<div class="ff-amenity ff-cat-' + cat.key + '"></div>' });
          var popup = h("div", { className: "ff-popup" },
            h("h3", {}, displayName(item.name)),
            h("p", {}, cat.label.replace(/s$/, "") + (item.detail ? " · " + item.detail : "")),
            h("p", {}, "About " + item.distanceM.toLocaleString("en-SG") + " m away (straight line)"));
          var walk = h("p", { className: "ff-walk" }, "Walking distance: select to calculate");
          popup.appendChild(walk);
          var marker = L.marker([item.lat, item.lng], { icon: icon, title: displayName(item.name) }).bindPopup(popup);
          marker.on("popupopen", function () { showWalkingDistance(walk, item, data.flat); });
          return marker;
        }));
        if (visible.indexOf(cat.key) >= 0) layers[cat.key].addTo(map);
      });

      toggles.forEach(function (toggle) {
        var key = toggle.dataset.layerToggle;
        var cat = data.categories.filter(function (c) { return c.key === key; })[0];
        toggle.checked = visible.indexOf(key) >= 0;
        var count = document.querySelector('[data-layer-count="' + key + '"]');
        if (count && cat) count.textContent = cat.items.length;
        toggle.addEventListener("change", function () {
          // UC-12: show or hide pins already fetched; no new request.
          if (toggle.checked) layers[key].addTo(map); else map.removeLayer(layers[key]);
          FF.MapState.save({
            visibleLayers: CATEGORY_KEYS.filter(function (k) { return layers[k] && map.hasLayer(layers[k]); }),
          });
        });
      });
      FF.amenityLayers = layers;
    }).catch(function () {
      setStatus("Couldn't load nearby amenities for the map.");
    });
  }

  /**
   * UC-04 Calculate Walking Distance: asked for once per pin, when its popup first opens.
   * A OneMap failure shows the UC-06 banner; the rest of the map keeps working.
   */
  function showWalkingDistance(line, item, flat) {
    if (line.dataset.state === "done" || line.dataset.state === "loading") return;
    line.dataset.state = "loading";
    line.textContent = "Walking distance: calculating…";
    var params = new URLSearchParams({ flat_id: flat.id, lat: item.lat, lng: item.lng });
    fetch("/api/walking-distance?" + params, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (response) {
        return response.json().then(function (body) { return { ok: response.ok, status: response.status, body: body }; });
      })
      .then(function (res) {
        if (!res.ok) {
          line.dataset.state = "failed";
          line.textContent = "Walking distance unavailable.";
          if (res.status === 502 && FF.showError) FF.showError(res.body.error);
          return;
        }
        line.dataset.state = "done";
        var text = "Walk: " + res.body.metres.toLocaleString("en-SG") + " m";
        if (res.body.minutes) text += " · about " + res.body.minutes + " min";
        if (res.body.fromTownCentre) text += " (from the town centre)";
        line.textContent = text;
      })
      .catch(function () {
        line.dataset.state = "failed";
        line.textContent = "Walking distance unavailable.";
        if (FF.showError) FF.showError();
      });
  }

  // --- Saved: the saved flats --------------------------------------------------------------

  function initSaved() {
    var layer = L.layerGroup().addTo(map);
    map.setView(DEFAULT_VIEW.centre, DEFAULT_VIEW.zoom);
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

  var mode = el.dataset.mapMode;
  if (mode === "flat") initFlat();
  else if (mode === "saved") initSaved();
  else initBrowse();
})();
