/**
 * «Boundary» SearchUI, client side — the sidebar sliders (UC-01, UC-08) and the sort control (UC-10).
 * Shows each slider's value as it moves, and disables a slider whose "off" checkbox
 * (Ignore / No limit / Any) is ticked, so a blank criterion isn't submitted (FR 1.1.6).
 */
(function () {
  "use strict";

  document.querySelectorAll("[data-slider]").forEach(function (row) {
    var range = row.querySelector('input[type="range"]');
    var output = row.querySelector("output");
    var off = row.querySelector("[data-off]");

    function render() {
      var isOff = Boolean(off && off.checked);  // the anchor slider has no "off" checkbox
      output.textContent = range.value + (range.dataset.unit || "");
      range.disabled = isOff;
      range.classList.toggle("opacity-40", isOff);
      output.classList.toggle("opacity-40", isOff);
      row.classList.toggle("is-off", isOff);
    }

    range.addEventListener("input", render);
    if (off) off.addEventListener("change", render);
    render();
  });

  // UC-10: changing the sort dropdown applies it straight away.
  document.querySelectorAll("[data-sort-form] select").forEach(function (select) {
    select.addEventListener("change", function () { select.form.submit(); });
  });
})();
