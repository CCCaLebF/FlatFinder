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
      var span = Number(range.max) - Number(range.min);
      range.style.setProperty("--fill", (span ? (range.value - range.min) / span * 100 : 0) + "%");
      range.disabled = isOff;
      range.classList.toggle("opacity-40", isOff);
      output.classList.toggle("opacity-40", isOff);
      row.classList.toggle("is-off", isOff);
    }

    range.addEventListener("input", render);
    if (off) off.addEventListener("change", render);
    render();
  });

  // Budget heading summary follows the two inputs as the user types.
  var summary = document.querySelector("[data-budget-summary]");
  var low = document.querySelector('[name="min_budget"]');
  var high = document.querySelector('[name="max_budget"]');
  function short(value) {
    return value >= 1e6 ? "S$" + (value / 1e6).toFixed(2).replace(/\.?0+$/, "") + "m" : "S$" + Math.round(value / 1000) + "k";
  }
  function updateSummary() {
    var a = parseFloat(low.value), b = parseFloat(high.value);
    summary.textContent = isNaN(a) && isNaN(b) ? "Any budget"
      : isNaN(a) ? "Up to " + short(b)
      : isNaN(b) ? "From " + short(a)
      : short(a) + " – " + short(b);
  }
  if (summary && low && high) {
    low.addEventListener("input", updateSummary);
    high.addEventListener("input", updateSummary);
  }

  // UC-10: changing the sort dropdown applies it straight away.
  document.querySelectorAll("[data-sort-form] select").forEach(function (select) {
    select.addEventListener("change", function () { select.form.submit(); });
  });
})();
