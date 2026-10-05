(() => {
  const workspace = document.querySelector("[data-statutory-workspace]");
  if (!workspace || typeof window.fetch !== "function") return;

  const showToast = (type, message) => {
    if (window.ShiftlyToasts && typeof window.ShiftlyToasts.show === "function") {
      window.ShiftlyToasts.show(type, message);
    }
  };
  const checkboxes = () => Array.from(workspace.querySelectorAll("[data-statutory-checkbox]:not(:disabled)"));
  const selected = () => checkboxes().filter((box) => box.checked);
  const selectionBar = workspace.querySelector("[data-statutory-selection-bar]");
  const selectionCount = workspace.querySelector("[data-statutory-selected-count]");
  const selectionLabel = workspace.querySelector("[data-statutory-selection-label]");
  const selectionNote = workspace.querySelector("[data-statutory-selection-note]");
  const visibleToggle = workspace.querySelector("[data-statutory-toggle-visible]");
  const selectAllButton = workspace.querySelector("[data-statutory-select-all]");
  const scopeInput = workspace.querySelector("[data-statutory-selection-scope]");
  const matchingCount = Number(workspace.dataset.statutoryMatchingCount || 0);

  const updateSelection = () => {
    const rows = selected();
    const allMatching = scopeInput?.value === "all";
    if (selectionBar) selectionBar.hidden = false;
    selectionBar?.classList.toggle("is-all-selected", allMatching);
    if (selectionCount) selectionCount.textContent = String(allMatching ? matchingCount : rows.length);
    if (selectionLabel) selectionLabel.textContent = allMatching ? "matching assessments selected across all pages" : "assessments selected";
    if (selectionNote) selectionNote.textContent = allMatching
      ? "Rows on other pages are included. Clear this selection to review only visible rows."
      : "Select rows on this page or select all matching assessments across pages.";
    if (selectAllButton) {
      selectAllButton.textContent = allMatching ? "Clear all matching" : "Select all matching";
      selectAllButton.setAttribute("aria-pressed", String(allMatching));
    }
    const reviewButton = workspace.querySelector("[data-statutory-open-bulk-review]");
    if (reviewButton) reviewButton.disabled = allMatching ? matchingCount === 0 : rows.length === 0;
    if (visibleToggle) {
      const enabled = checkboxes();
      visibleToggle.checked = enabled.length > 0 && enabled.every((box) => box.checked);
      visibleToggle.indeterminate = enabled.some((box) => box.checked) && !visibleToggle.checked;
    }
  };

  const syncSummaryCallout = (count) => {
    const summary = document.querySelector(".payroll-statutory-summary");
    if (!summary || Number(count) !== 0) return;
    const needed = summary.querySelector("[data-statutory-review-needed]");
    if (needed && !summary.querySelector("[data-statutory-summary-complete]")) {
      needed.outerHTML = '<div class="payroll-empty-state payroll-empty-state--success" data-statutory-summary-complete><span class="payroll-empty-icon" aria-hidden="true">✓</span><div><h3>Statutory review complete</h3><p>All statutory items have been reviewed.</p></div></div>';
    }
  };
  workspace.addEventListener("change", (event) => {
    if (event.target.matches("[data-statutory-checkbox]")) {
      if (scopeInput) scopeInput.value = "visible";
      updateSelection();
    }
    if (event.target === visibleToggle) {
      checkboxes().forEach((box) => { box.checked = visibleToggle.checked; });
      if (scopeInput) scopeInput.value = "visible";
      updateSelection();
    }
  });
  workspace.querySelector("[data-statutory-select-visible]")?.addEventListener("click", () => {
    checkboxes().forEach((box) => { box.checked = true; });
    if (scopeInput) scopeInput.value = "visible";
    updateSelection();
  });
  selectAllButton?.addEventListener("click", () => {
    const allMatching = scopeInput?.value === "all";
    if (allMatching) {
      if (scopeInput) scopeInput.value = "visible";
      checkboxes().forEach((box) => { box.checked = false; });
      updateSelection();
      showToast("info", "Cleared the all-pages selection.");
      return;
    }
    if (matchingCount === 0) {
      showToast("info", "No unresolved assessments match the current filters.");
      return;
    }
    checkboxes().forEach((box) => { box.checked = true; });
    if (scopeInput) scopeInput.value = "all";
    updateSelection();
    showToast("info", `${matchingCount} matching assessment${matchingCount === 1 ? "" : "s"} selected across all pages.`);
  });

  const dialog = workspace.querySelector("#bulk-statutory-dialog");
  const bulkForm = workspace.querySelector("[data-statutory-bulk-form]");
  const hiddenHolder = workspace.querySelector("[data-statutory-bulk-selected-inputs]");
  workspace.querySelector("[data-statutory-open-bulk-review]")?.addEventListener("click", () => {
    const rows = selected();
    const allMatching = scopeInput?.value === "all";
    if (!allMatching && !rows.length) {
      showToast("error", "Select at least one ready assessment to review.");
      return;
    }
    if (hiddenHolder) {
      hiddenHolder.innerHTML = "";
      if (!allMatching) rows.forEach((box) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "assessment_ids";
        input.value = box.value;
        hiddenHolder.appendChild(input);
      });
    }
    const count = workspace.querySelector("[data-statutory-dialog-count]");
    if (count) count.textContent = allMatching ? "All matching assessments" : `${rows.length} assessment${rows.length === 1 ? "" : "s"}`;
    const agencies = [...new Set(rows.map((box) => box.closest("tr")?.querySelector(".statutory-agency-badge")?.textContent.trim()).filter(Boolean))];
    const agencyLabel = workspace.querySelector("[data-statutory-dialog-agencies]");
    if (agencyLabel) agencyLabel.textContent = allMatching ? "The current filters define the selected population." : (agencies.join(", ") || "Selected assessments");
    dialog?.showModal();
  });

  bulkForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (bulkForm.dataset.submitting === "true") return;
    bulkForm.dataset.submitting = "true";
    const button = bulkForm.querySelector("[data-statutory-bulk-submit]");
    const original = button?.textContent || "Confirm reviewed assessments";
    if (button) { button.disabled = true; button.textContent = "Saving…"; }
    try {
      const response = await fetch(bulkForm.action, {
        method: "POST",
        body: new FormData(bulkForm),
        headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.message || "The bulk review could not be saved.");
      const ids = new Set((data.assessment_ids || []).map(String));
      workspace.querySelectorAll("[data-statutory-row]").forEach((row) => {
        if (!ids.has(row.dataset.assessmentId)) return;
        row.dataset.assessmentStatus = "REVIEWED";
        row.querySelector("[data-statutory-checkbox]")?.remove();
        const cell = row.querySelector(".statutory-select-column");
        if (cell && !cell.textContent.trim()) cell.innerHTML = "<span class=\"muted\">—</span>";
        const status = row.querySelector("[data-statutory-row-status]");
        if (status) { status.textContent = "Reviewed"; status.className = "payroll-status payroll-status--finalized"; }
        const source = row.querySelector(".statutory-source-label");
        if (source && bulkForm.elements.treatment) source.textContent = bulkForm.elements.treatment.selectedOptions[0]?.textContent || source.textContent;
      });
      if (data.counts) {
        const metricValues = [data.counts.total, data.counts.ready, data.counts.attention, data.counts.reviewed];
        workspace.querySelectorAll(".statutory-bulk-metrics > div strong").forEach((element, index) => {
          if (metricValues[index] !== undefined) element.textContent = String(metricValues[index]);
        });
      }
      if (data.pending_employee_count !== undefined) {
        document.querySelectorAll("[data-statutory-pending-count]").forEach((element) => { element.textContent = String(data.pending_employee_count); });
        document.querySelectorAll("[data-submit-review-button]").forEach((element) => { element.disabled = Number(data.pending_employee_count) > 0 || Number(element.dataset.blockingExceptions) > 0; });
        syncSummaryCallout(data.pending_employee_count);
      }
      dialog?.close();
      workspace.querySelectorAll("[data-statutory-checkbox]").forEach((box) => { box.checked = false; });
      if (scopeInput) scopeInput.value = "visible";
      updateSelection();
      showToast("success", data.message || "Statutory assessments reviewed.");
    } catch (error) {
      showToast("error", error.message || "The bulk review could not be saved. Refresh and try again.");
      if (button) { button.disabled = false; button.textContent = original; }
    } finally {
      delete bulkForm.dataset.submitting;
    }
  });

  const generateForm = workspace.querySelector("[data-statutory-generate-form]");
  generateForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = generateForm.querySelector("[data-statutory-generate-button]");
    if (button) { button.disabled = true; button.textContent = "Generating…"; }
    try {
      const response = await fetch(generateForm.action, {
        method: "POST", body: new FormData(generateForm),
        headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" }, credentials: "same-origin",
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.message || "The assessment queue could not be generated.");
      showToast("success", data.message || "Assessment queue generated.");
      window.setTimeout(() => window.location.reload(), 250);
    } catch (error) {
      showToast("error", error.message || "The assessment queue could not be generated.");
      if (button) { button.disabled = false; button.textContent = "Generate assessments"; }
    }
  });
  updateSelection();
})();
