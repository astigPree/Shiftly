(() => {
  const confirmationDialog = document.getElementById("payroll-confirm-dialog");
  let pendingForm = null;
  let confirmedForm = null;

  document.querySelectorAll("[data-payroll-dialog-open]").forEach((button) => {
    button.addEventListener("click", () => {
      const dialog = document.getElementById(button.dataset.payrollDialogOpen);
      if (dialog instanceof HTMLDialogElement) dialog.showModal();
    });
  });

  document.querySelectorAll("[data-payroll-dialog-close]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });

  document.querySelectorAll("form[data-payroll-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (confirmedForm === form) {
        confirmedForm = null;
        return;
      }
      event.preventDefault();
      if (!(confirmationDialog instanceof HTMLDialogElement)) return;
      pendingForm = form;
      confirmationDialog.querySelector("#payroll-confirm-title").textContent = form.dataset.confirmTitle || "Confirm this action?";
      confirmationDialog.querySelector("#payroll-confirm-description").textContent = form.dataset.confirmDescription || "Continue with this payroll action?";
      const submitButton = confirmationDialog.querySelector("[data-payroll-confirm-submit]");
      submitButton.textContent = form.dataset.confirmAction || "Continue";
      submitButton.classList.toggle("button-danger", form.dataset.confirmDanger !== "false");
      confirmationDialog.showModal();
    });
  });

  confirmationDialog?.querySelector("[data-payroll-confirm-cancel]")?.addEventListener("click", () => {
    pendingForm = null;
    confirmationDialog.close();
  });

  confirmationDialog?.querySelector("[data-payroll-confirm-submit]")?.addEventListener("click", () => {
    if (!pendingForm) return;
    const form = pendingForm;
    pendingForm = null;
    confirmedForm = form;
    confirmationDialog.close();
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
  });

  document.querySelectorAll(".payroll-print-button").forEach((button) => {
    button.addEventListener("click", () => window.print());
  });
})();
