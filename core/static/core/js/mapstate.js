/**
 * «Entity» MapState — the last successfully rendered map, kept in localStorage (UC-13, FR 1.2.1.2).
 * Holds centre, zoom, visibleLayers and viewMode. Restored by MapUI when tiles fail (UC-06).
 * Built in phase 6.
 */
(function () {
  "use strict";
  window.FlatFinder = window.FlatFinder || {};
})();
