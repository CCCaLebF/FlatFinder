/**
 * «Entity» MapState — the last successfully rendered map, kept in localStorage (UC-13, FR 1.2.1.2).
 * Holds centre, zoom, visibleLayers, viewMode and panelsHidden (Map View side panels hidden,
 * so the map fills the window).
 *
 * Also applies the view-mode default (PLAN §6): the `view` URL parameter wins; without one,
 * the last mode chosen in the header toggle is used.
 */
(function () {
  "use strict";
  window.FlatFinder = window.FlatFinder || {};

  var KEY = "flatfinder.mapState";

  function load() {
    try {
      return JSON.parse(window.localStorage.getItem(KEY)) || {};
    } catch (e) {
      return {};  // private mode, blocked storage or bad JSON: behave as if nothing is saved
    }
  }

  function save(changes) {
    var state = load();
    Object.keys(changes).forEach(function (key) { state[key] = changes[key]; });
    try {
      window.localStorage.setItem(KEY, JSON.stringify(state));
    } catch (e) { /* storage unavailable: the map still works, it just won't be remembered */ }
    return state;
  }

  window.FlatFinder.MapState = {
    load: load,
    save: save,
    /** {centre: [lat, lng], zoom} if a map view has been rendered before, else null. */
    lastView: function () {
      var s = load();
      return Array.isArray(s.centre) && typeof s.zoom === "number" ? { centre: s.centre, zoom: s.zoom } : null;
    },
    visibleLayers: function (fallback) {
      var layers = load().visibleLayers;
      return Array.isArray(layers) ? layers : fallback;
    },
    viewMode: function () { return load().viewMode === "map" ? "map" : "list"; },
    panelsHidden: function () { return load().panelsHidden === true; },
  };

  // Hidden side panels: set before the page paints, so they never flash in (map.css hides them).
  if (window.FlatFinder.MapState.panelsHidden()) document.documentElement.dataset.panelsHidden = "1";

  // Remember the mode the user picks in the header toggle.
  document.addEventListener("click", function (event) {
    var link = event.target.closest("[data-view]");
    if (link) save({ viewMode: link.dataset.view });
  });

  // No `view` in the URL: fall back to the remembered mode. This file loads in <head>,
  // so the redirect happens before the list version is painted.
  var params = new URLSearchParams(window.location.search);
  if (!params.has("view") && window.FlatFinder.MapState.viewMode() === "map"
      && document.documentElement.dataset.mapCapable) {
    params.set("view", "map");
    window.location.replace(window.location.pathname + "?" + params.toString());
  }
})();
