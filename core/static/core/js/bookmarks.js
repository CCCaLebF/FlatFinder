/**
 * «Boundary» BookmarkUI, client side (UC-05, UC-14).
 * Sends each bookmark form with fetch() to POST /api/bookmarks/<flat_id>/toggle,
 * then updates every icon for that flat and the header's Saved (n) counter.
 * On the Saved page, a removed flat's card disappears; the empty state shows when none are left.
 * If the request fails, the form is submitted normally (the server redirects back).
 */
(function () {
  "use strict";
  window.FlatFinder = window.FlatFinder || {};

  function setSaved(flatId, saved) {
    document.querySelectorAll('[data-bookmark-form="' + flatId + '"] [data-bookmark-button]').forEach(function (button) {
      button.setAttribute("aria-pressed", saved ? "true" : "false");
      button.setAttribute("aria-label", saved ? "Remove from saved flats" : "Save this flat");
      button.title = saved ? "Saved — click to remove" : "Save this flat";
    });
  }

  function removeFromSavedPage(form) {
    var item = form.closest("[data-saved-item]");
    if (!item) return;
    item.remove();
    if (!document.querySelector("[data-saved-item]")) {
      var empty = document.querySelector("[data-saved-empty]");
      if (empty) empty.classList.remove("hidden");
    }
  }

  document.addEventListener("submit", function (event) {
    var form = event.target.closest("[data-bookmark-form]");
    if (!form) return;
    event.preventDefault();
    var flatId = form.dataset.bookmarkForm;

    fetch(form.action, {
      method: "POST",
      headers: { "Accept": "application/json", "X-CSRFToken": form.elements.csrfmiddlewaretoken.value },
      credentials: "same-origin",
    })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        setSaved(flatId, data.saved);
        var counter = document.getElementById("saved-count");
        if (counter) counter.textContent = data.count;
        if (!data.saved) removeFromSavedPage(form);
        // MapUI redraws its saved-flat pins (UC-03.AC.1).
        document.dispatchEvent(new CustomEvent("flatfinder:bookmark-changed", { detail: { flatId: flatId, saved: data.saved } }));
      })
      .catch(function () {
        form.submit();  // fall back to the plain form post
      });
  });
})();
