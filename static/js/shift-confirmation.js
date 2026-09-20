(() => {
  const attendanceDialog = document.querySelector("[data-attendance-confirm-dialog]");
  if (attendanceDialog && typeof attendanceDialog.showModal === "function") {
    const title = attendanceDialog.querySelector("[data-attendance-confirm-title]");
    const description = attendanceDialog.querySelector("[data-attendance-confirm-description]");
    const confirmButton = attendanceDialog.querySelector("[data-attendance-confirm-submit]");
    const cancelButton = attendanceDialog.querySelector("[data-attendance-confirm-cancel]");
    let pendingForm = null;
    let confirmedForm = null;

    document.querySelectorAll("form[data-attendance-confirm]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (confirmedForm === form) {
          confirmedForm = null;
          return;
        }

        event.preventDefault();
        event.stopImmediatePropagation();
        pendingForm = form;
        title.textContent = form.dataset.confirmTitle || "Confirm this attendance action?";
        description.textContent = form.dataset.confirmDescription || "Please confirm before continuing.";
        confirmButton.textContent = form.dataset.confirmAction || "Confirm";
        attendanceDialog.showModal();
        cancelButton.focus();
      });
    });

    const closeAttendanceDialog = () => {
      pendingForm = null;
      if (attendanceDialog.open) attendanceDialog.close();
    };

    cancelButton?.addEventListener("click", closeAttendanceDialog);
    attendanceDialog.addEventListener("cancel", () => {
      pendingForm = null;
    });
    attendanceDialog.addEventListener("click", (event) => {
      if (event.target === attendanceDialog) closeAttendanceDialog();
    });
    confirmButton?.addEventListener("click", () => {
      if (!pendingForm) return;
      const form = pendingForm;
      pendingForm = null;
      confirmedForm = form;
      attendanceDialog.close();
      form.requestSubmit();
    });
  }

  document.querySelectorAll("[data-open-shift-cancel]").forEach((trigger) => {
    const dialogId = trigger.getAttribute("aria-controls");
    const dialog = dialogId ? document.getElementById(dialogId) : null;
    if (!dialog || typeof dialog.showModal !== "function") return;

    trigger.addEventListener("click", () => dialog.showModal());

    dialog.querySelector("[data-close-shift-cancel]")?.addEventListener("click", () => {
      dialog.close();
    });

    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });
})();
