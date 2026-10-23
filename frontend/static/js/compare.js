/**
 * «Boundary» CompareUI, client side (Phase H).
 * Sends each compare toggle and the tray's "Clear" with fetch() to the compare endpoints,
 * then updates the buttons, the tray count/link and its visibility without reloading —
 * so the page keeps its scroll position. On failure the form submits normally (a redirect back).
 */
(function () {
  "use strict";
  window.FlatFinder = window.FlatFinder || {};

  var MAX = 3;

  function setButton(form, added) {
    var button = form.querySelector("[data-compare-button]");
    if (!button) return;
    button.setAttribute("aria-pressed", added ? "true" : "false");
    button.title = added ? "Remove from compare" : "Add to compare";
    var label = button.querySelector("span");
    if (label) label.textContent = added ? "Remove" : "Compare";
    button.classList.toggle("border-brand-300", added);
    button.classList.toggle("bg-brand-50", added);
    button.classList.toggle("text-brand-700", added);
    button.classList.toggle("border-slate-300", !added);
    button.classList.toggle("bg-white", !added);
    button.classList.toggle("text-slate-600", !added);
  }

  function setLinkEnabled(enabled) {
    var link = document.getElementById("compare-link");
    if (!link) return;
    link.classList.toggle("pointer-events-none", !enabled);
    link.classList.toggle("bg-slate-200", !enabled);
    link.classList.toggle("text-slate-400", !enabled);
    link.classList.toggle("bg-brand-600", enabled);
    link.classList.toggle("text-white", enabled);
    link.classList.toggle("hover:bg-brand-700", enabled);
  }

  function setTray(count) {
    var tray = document.getElementById("compare-tray");
    var counter = document.getElementById("compare-count");
    if (counter) counter.textContent = count;
    if (tray) tray.classList.toggle("hidden", count === 0);
    setLinkEnabled(count >= 2);
    document.querySelectorAll("[data-compare-form]").forEach(function (form) {
      var button = form.querySelector("[data-compare-button]");
      var added = button.getAttribute("aria-pressed") === "true";
      if (!added && count >= MAX) {
        button.disabled = true;
        button.title = "Compare is full (max 3)";
      } else if (!added) {
        button.disabled = false;
        button.title = "Add to compare";
      }
    });
  }

  function toggle(form) {
    return fetch(form.action, {
      method: "POST",
      headers: { "Accept": "application/json", "X-CSRFToken": form.elements.csrfmiddlewaretoken.value },
      credentials: "same-origin",
    });
  }

  document.addEventListener("submit", function (event) {
    var toggleForm = event.target.closest("[data-compare-form]");
    if (toggleForm) {
      event.preventDefault();
      toggle(toggleForm)
        .then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        })
        .then(function (data) {
          setButton(toggleForm, data.added);
          setTray(data.count);
        })
        .catch(function () { toggleForm.submit(); });
      return;
    }

    var clearForm = event.target.closest("[data-compare-clear]");
    if (clearForm) {
      event.preventDefault();
      toggle(clearForm)
        .then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.json();
        })
        .then(function (data) {
          document.querySelectorAll("[data-compare-form]").forEach(function (form) { setButton(form, false); });
          setTray(data.count);
        })
        .catch(function () { clearForm.submit(); });
    }
  });
})();
