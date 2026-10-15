/**
 * ErrorHandler, client side — the dismissible banner for UC-06 Handle API Failure
 * (FR 1.2.1.1, NFR 2.1). FlatFinder.showError(message) shows it; the page keeps working.
 * Also lets the user dismiss any message under the header.
 */
(function () {
  "use strict";
  window.FlatFinder = window.FlatFinder || {};

  var DEFAULT_MESSAGE = "OneMap service currently unavailable. Please try again later.";

  window.FlatFinder.showError = function (message) {
    var banner = document.querySelector("[data-error-banner]");
    if (!banner) return;
    banner.querySelector("[data-error-text]").textContent = message || DEFAULT_MESSAGE;
    banner.classList.remove("hidden");
  };

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-dismiss]");
    if (!button) return;
    var box = button.parentElement;
    if (box.hasAttribute("data-error-banner")) box.classList.add("hidden");
    else box.remove();
  });
})();
