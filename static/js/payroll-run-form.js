(function () {
  "use strict";

  var root = document.querySelector("[data-payroll-run-form]");
  if (!root) return;

  var form = root.querySelector("form") || root.closest("form");
  var frequency = root.dataset.frequency || "SEMI_MONTHLY";
  var today = parseDate(root.dataset.today) || new Date();
  var startField = document.getElementById("id_period_start");
  var endField = document.getElementById("id_period_end");
  var payDateField = document.getElementById("id_pay_date");
  var parentSection = root.querySelector("[data-parent-run-section]");
  var parentField = document.getElementById("id_parent_run");
  var picker = root.querySelector("[data-employee-picker]");
  var allSummary = root.querySelector("[data-all-active-summary]");
  var employeeCheckboxes = Array.prototype.slice.call(root.querySelectorAll("[data-employee-checkbox]"));
  var employeeCount = root.querySelector("[data-employee-count]");
  var previewEmployees = root.querySelector("[data-preview-employees]");
  var previewPeriod = root.querySelector("[data-preview-period]");
  var previewPayDate = root.querySelector("[data-preview-pay-date]");
  var previewApproved = root.querySelector("[data-preview-approved]");
  var previewReview = root.querySelector("[data-preview-review]");
  var previewReviewRow = previewReview && previewReview.closest(".payroll-source-row");
  var periodValidation = root.querySelector("[data-period-validation]");
  var scopeReadiness = root.querySelector("[data-scope-readiness]");
  var scopeReadinessDetail = root.querySelector("[data-scope-readiness-detail]");
  var createButton = root.querySelector("[data-create-run]");

  function parseDate(value) {
    if (!value) return null;
    var parts = value.split("-").map(Number);
    if (parts.length !== 3 || parts.some(function (part) { return !part; })) return null;
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  function isoDate(date) {
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function addDays(date, amount) {
    var next = new Date(date);
    next.setDate(next.getDate() + amount);
    return next;
  }

  function monthStart(date) { return new Date(date.getFullYear(), date.getMonth(), 1); }
  function monthEnd(date) { return new Date(date.getFullYear(), date.getMonth() + 1, 0); }

  function periodBounds(reference, which) {
    var start;
    var end;
    if (frequency === "WEEKLY") {
      start = addDays(reference, -reference.getDay() + 1);
      if (reference.getDay() === 0) start = addDays(reference, -6);
      end = addDays(start, 6);
      if (which === "previous") { start = addDays(start, -7); end = addDays(end, -7); }
      return [start, end];
    }
    var first = monthStart(reference);
    var last = monthEnd(reference);
    if (frequency === "MONTHLY") {
      if (which === "previous") {
        var priorLast = addDays(first, -1);
        return [monthStart(priorLast), priorLast];
      }
      return [first, last];
    }
    if (reference.getDate() <= 15) {
      if (which === "previous") {
        var priorMonthLast = addDays(first, -1);
        return [new Date(priorMonthLast.getFullYear(), priorMonthLast.getMonth(), 16), priorMonthLast];
      }
      return [first, new Date(reference.getFullYear(), reference.getMonth(), 15)];
    }
    if (which === "previous") return [first, new Date(reference.getFullYear(), reference.getMonth(), 15)];
    return [new Date(reference.getFullYear(), reference.getMonth(), 16), last];
  }

  function formatDate(date) {
    return date ? new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date) : "not set";
  }

  function sameDate(left, right) {
    return left && right && left.getFullYear() === right.getFullYear() && left.getMonth() === right.getMonth() && left.getDate() === right.getDate();
  }

  function periodValidationMessage(start, end) {
    var runType = root.querySelector('input[name="run_type"]:checked');
    if (!start || !end || (runType && runType.value !== "REGULAR")) return "";
    if (frequency === "MONTHLY") {
      var monthlyEnd = monthEnd(start);
      if (start.getDate() !== 1 || !sameDate(end, monthlyEnd)) return "Monthly periods must start on day 1 and end on " + formatDate(monthlyEnd) + ".";
    } else if (frequency === "SEMI_MONTHLY") {
      var semiEnd = start.getDate() === 16 ? monthEnd(start) : new Date(start.getFullYear(), start.getMonth(), 15);
      if (!((start.getDate() === 1 || start.getDate() === 16) && sameDate(end, semiEnd))) return "Semi-monthly periods must run from the 1st-15th or 16th-month end.";
    } else if (frequency === "WEEKLY") {
      var monday = start.getDay() === 0 ? addDays(start, -6) : addDays(start, 1 - start.getDay());
      if (start.getDay() !== 1 || !sameDate(end, addDays(monday, 6))) return "Weekly periods must run Monday through Sunday.";
    }
    return "";
  }

  function updatePeriodValidation(start, end) {
    var message = periodValidationMessage(start, end);
    if (periodValidation) {
      periodValidation.textContent = message;
      periodValidation.hidden = !message;
    }
    if (startField) startField.classList.toggle("payroll-input-warning", Boolean(message));
    if (endField) endField.classList.toggle("payroll-input-warning", Boolean(message));
  }

  function updatePreview() {
    var start = parseDate(startField && startField.value);
    var end = parseDate(endField && endField.value);
    var payDate = parseDate(payDateField && payDateField.value);
    var selected = employeeCheckboxes.filter(function (checkbox) { return checkbox.checked; }).length;
    var selectedMode = root.querySelector('input[name="scope_mode"]:checked');
    var employeeTotal = selectedMode && selectedMode.value === "SELECTED" ? selected : Number(root.dataset.eligibleCount || 0);
    var approvedTotal = Number(root.dataset.previewApprovedTotal || 0);
    var reviewTotal = Number(root.dataset.previewReviewTotal || 0);
    if (selectedMode && selectedMode.value === "SELECTED") {
      approvedTotal = 0;
      reviewTotal = 0;
      employeeCheckboxes.forEach(function (checkbox) {
        if (!checkbox.checked) return;
        var option = checkbox.closest("[data-employee-option]");
        approvedTotal += Number(option && option.dataset.approved || 0);
        reviewTotal += Number(option && option.dataset.review || 0);
      });
    }
    if (previewEmployees) previewEmployees.textContent = employeeTotal + " selected";
    if (previewApproved) previewApproved.textContent = approvedTotal;
    if (previewReview) previewReview.textContent = reviewTotal;
    if (previewReviewRow) previewReviewRow.classList.toggle("payroll-source-row--warning", reviewTotal > 0);
    if (employeeCount) employeeCount.textContent = selected + " employee" + (selected === 1 ? "" : "s") + " selected";
    var scopedOptions = employeeCheckboxes.filter(function (checkbox) {
      return !(selectedMode && selectedMode.value === "SELECTED") || checkbox.checked;
    });
    var attentionCount = scopedOptions.filter(function (checkbox) {
      var option = checkbox.closest("[data-employee-option]");
      return !option || option.dataset.ready !== "1";
    }).length;
    if (scopeReadiness) {
      scopeReadiness.classList.toggle("payroll-readiness-row--complete", scopedOptions.length > 0 && attentionCount === 0);
      scopeReadiness.classList.toggle("payroll-readiness-row--warning", scopedOptions.length === 0 || attentionCount > 0);
      var icon = scopeReadiness.querySelector(".payroll-readiness-icon");
      if (icon) icon.textContent = scopedOptions.length > 0 && attentionCount === 0 ? "✓" : "!";
    }
    if (scopeReadinessDetail) {
      scopeReadinessDetail.textContent = !scopedOptions.length
        ? "Select at least one employee."
        : attentionCount
          ? attentionCount + " selected employee" + (attentionCount === 1 ? " needs" : "s need") + " payroll setup review."
          : scopedOptions.length + " selected employee" + (scopedOptions.length === 1 ? " is" : "s are") + " payroll ready.";
    }
    if (previewPeriod) previewPeriod.textContent = start && end ? formatDate(start) + " – " + formatDate(end) : "Choose dates";
    if (previewPayDate) previewPayDate.textContent = formatDate(payDate);
    updatePeriodValidation(start, end);
    updateCreateAvailability();
  }

  function updateCreateAvailability() {
    if (!createButton) return;
    var runType = root.querySelector('input[name="run_type"]:checked');
    var scopeMode = root.querySelector('input[name="scope_mode"]:checked');
    var selectedCount = employeeCheckboxes.filter(function (checkbox) { return checkbox.checked; }).length;
    var offCycleMissingParent = runType && runType.value === "OFF_CYCLE" && (!parentField || !parentField.value);
    var emptySelectedScope = scopeMode && scopeMode.value === "SELECTED" && selectedCount === 0;
    createButton.disabled = Boolean(offCycleMissingParent || emptySelectedScope);
    createButton.title = offCycleMissingParent
      ? "Choose the finalized payroll run this correction belongs to."
      : emptySelectedScope ? "Select at least one employee." : "";
  }

  function updateScope() {
    var selected = root.querySelector('input[name="scope_mode"]:checked');
    var isSelected = selected && selected.value === "SELECTED";
    if (picker) picker.hidden = !isSelected;
    if (allSummary) allSummary.hidden = isSelected;
    employeeCheckboxes.forEach(function (checkbox) {
      checkbox.disabled = !isSelected;
    });
    updatePreview();
  }

  function updateParent() {
    var selected = root.querySelector('input[name="run_type"]:checked');
    var offCycle = selected && selected.value === "OFF_CYCLE";
    if (parentSection) parentSection.hidden = !offCycle;
    if (parentField) parentField.disabled = !offCycle;
    updateCreateAvailability();
  }

  function setPeriod(which) {
    if (which === "custom") {
      if (startField) startField.focus();
      return;
    }
    var bounds = periodBounds(today, which);
    if (startField) startField.value = isoDate(bounds[0]);
    if (endField) endField.value = isoDate(bounds[1]);
    if (payDateField) payDateField.value = isoDate(addDays(bounds[1], 5));
    updatePreview();
  }

  function updateShortcutLabels() {
    var labels = frequency === "MONTHLY"
      ? { previous: "Previous month", current: "Current month" }
      : frequency === "WEEKLY"
        ? { previous: "Previous week", current: "Current week" }
        : { previous: "Previous period", current: "Current period" };
    root.querySelectorAll("[data-period-preset]").forEach(function (button) {
      if (labels[button.dataset.periodPreset]) button.textContent = labels[button.dataset.periodPreset];
    });
  }

  root.querySelectorAll('input[name="scope_mode"]').forEach(function (input) { input.addEventListener("change", updateScope); });
  root.querySelectorAll('input[name="run_type"]').forEach(function (input) { input.addEventListener("change", updateParent); });
  [startField, endField, payDateField].forEach(function (field) { if (field) field.addEventListener("input", updatePreview); });
  root.querySelectorAll("[data-period-preset]").forEach(function (button) { button.addEventListener("click", function () { setPeriod(button.dataset.periodPreset); }); });

  var search = root.querySelector("[data-employee-search]");
  if (search) search.addEventListener("input", function () {
    var query = search.value.trim().toLowerCase();
    root.querySelectorAll("[data-employee-option]").forEach(function (option) {
      option.hidden = query && option.dataset.search.indexOf(query) === -1;
    });
  });
  root.querySelectorAll("[data-select-all]").forEach(function (button) { button.addEventListener("click", function () { employeeCheckboxes.forEach(function (checkbox) { if (!checkbox.disabled) checkbox.checked = true; }); updatePreview(); }); });
  root.querySelectorAll("[data-clear-all]").forEach(function (button) { button.addEventListener("click", function () { employeeCheckboxes.forEach(function (checkbox) { if (!checkbox.disabled) checkbox.checked = false; }); updatePreview(); }); });
  employeeCheckboxes.forEach(function (checkbox) { checkbox.addEventListener("change", updatePreview); });
  if (parentField) parentField.addEventListener("change", updateCreateAvailability);
  if (form) form.addEventListener("submit", function () {
    var button = form.querySelector("[data-create-run]");
    if (button) { button.disabled = true; button.classList.add("is-loading"); button.innerHTML = "Creating draft…"; }
  });

  updateScope();
  updateParent();
  updateShortcutLabels();
  updatePreview();
}());
