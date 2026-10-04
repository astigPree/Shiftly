(() => {
  const confirmationDialog = document.getElementById("payroll-confirm-dialog");
  let pendingForm = null;
  let confirmedForm = null;

  function syncDialogScrollLock() {
    const hasOpenDialog = Array.from(document.querySelectorAll("dialog")).some((dialog) => dialog.open);
    document.documentElement.classList.toggle("payroll-dialog-open", hasOpenDialog);
  }

  function openDialog(dialog) {
    if (!(dialog instanceof HTMLDialogElement)) return;
    dialog.showModal();
    syncDialogScrollLock();
    dialog.querySelector("input:not([type='hidden']), select, textarea, button")?.focus();
  }

  function closeDialog(dialog) {
    if (!(dialog instanceof HTMLDialogElement)) return;
    dialog.close();
    syncDialogScrollLock();
  }

  document.querySelectorAll("[data-payroll-dialog-open]").forEach((button) => {
    button.addEventListener("click", () => {
      const dialog = document.getElementById(button.dataset.payrollDialogOpen);
      openDialog(dialog);
    });
  });

  document.querySelectorAll("[data-payroll-dialog-close]").forEach((button) => {
    button.addEventListener("click", () => closeDialog(button.closest("dialog")));
  });

  document.querySelectorAll("form[data-payroll-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (confirmedForm === form) {
        confirmedForm = null;
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!(confirmationDialog instanceof HTMLDialogElement)) return;
      pendingForm = form;
      confirmationDialog.querySelector("#payroll-confirm-title").textContent = form.dataset.confirmTitle || "Confirm this action?";
      confirmationDialog.querySelector("#payroll-confirm-description").textContent = form.dataset.confirmDescription || "Continue with this payroll action?";
      const submitButton = confirmationDialog.querySelector("[data-payroll-confirm-submit]");
      submitButton.textContent = form.dataset.confirmAction || "Continue";
      submitButton.classList.toggle("button-danger", form.dataset.confirmDanger !== "false");
      submitButton.classList.toggle("button-link", form.dataset.confirmDanger === "false");
      openDialog(confirmationDialog);
      confirmationDialog.querySelector("[data-payroll-confirm-cancel]")?.focus();
    }, true);
  });

  confirmationDialog?.querySelector("[data-payroll-confirm-cancel]")?.addEventListener("click", () => {
    pendingForm?.querySelector('button[type="submit"]')?.focus();
    pendingForm = null;
    closeDialog(confirmationDialog);
  });

  confirmationDialog?.addEventListener("cancel", () => { pendingForm = null; });

  confirmationDialog?.querySelector("[data-payroll-confirm-submit]")?.addEventListener("click", () => {
    if (!pendingForm) return;
    const form = pendingForm;
    pendingForm = null;
    confirmedForm = form;
    closeDialog(confirmationDialog);
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
  });

  document.querySelectorAll(".payroll-print-button").forEach((button) => {
    button.addEventListener("click", () => window.print());
  });

  document.querySelectorAll("dialog[data-payroll-autopen='true']").forEach((dialog) => {
    openDialog(dialog);
  });

  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("close", syncDialogScrollLock);
  });
})();
