(() => {
  const form = document.querySelector("[data-attendance-correction-form]");
  const dialog = document.querySelector("[data-attendance-correction-dialog]");
  if (!form) return;

  const breakRows = [...document.querySelectorAll("[data-break-row]")];
  const addBreakButton = document.querySelector("[data-add-break]");
  const updateBreakButton = () => {
    if (!addBreakButton) return;
    const hasHiddenRow = breakRows.some((row) => row.hidden);
    addBreakButton.hidden = !hasHiddenRow;
  };
  addBreakButton?.addEventListener("click", () => {
    const nextRow = breakRows.find((row) => row.hidden);
    if (!nextRow) return;
    nextRow.hidden = false;
    nextRow.querySelector("input")?.focus();
    updateBreakButton();
  });
  updateBreakButton();

  const saveButton = form.querySelector("[data-attendance-correction-save]");
  const setSaving = () => {
    form.dataset.submitting = "true";
    form.setAttribute("aria-busy", "true");
    if (saveButton) {
      saveButton.disabled = true;
      saveButton.dataset.originalLabel = saveButton.dataset.originalLabel || saveButton.textContent;
      saveButton.textContent = "Saving correction...";
    }
  };

  if (!dialog || typeof dialog.showModal !== "function") {
    // Older browsers still get a confirmation and the form remains usable.
    form.addEventListener("submit", (event) => {
      if (!window.confirm("Save this attendance correction? The original punch will remain in the audit history.")) {
        event.preventDefault();
        return;
      }
      setSaving();
    });
    return;
  }

  const confirmButton = dialog.querySelector("[data-attendance-correction-submit]");
  const cancelButton = dialog.querySelector("[data-attendance-correction-cancel]");
  let confirmed = false;

  form.addEventListener("submit", (event) => {
    if (confirmed) {
      confirmed = false;
      setSaving();
      return;
    }
    event.preventDefault();
    if (dialog.open) return;
    dialog.showModal();
    cancelButton?.focus();
  });

  const close = () => {
    if (dialog.open) dialog.close();
  };

  cancelButton?.addEventListener("click", close);
  dialog.addEventListener("cancel", close);
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close();
  });
  confirmButton?.addEventListener("click", () => {
    if (form.dataset.submitting === "true") return;
    confirmed = true;
    close();
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
    } else {
      setSaving();
      form.submit();
    }
  });
})();
