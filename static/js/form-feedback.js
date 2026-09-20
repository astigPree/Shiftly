(() => {
  const toastRegion = document.querySelector("[data-toast-region]");
  const toastApi = window.ShiftlyToasts;

  if (!toastRegion || !toastApi) return;

  const loadingMessages = new Map([
    ["sign out", "Signing you out…"],
    ["clock in", "Recording your clock-in…"],
    ["start break", "Starting your break…"],
    ["end break", "Ending your break…"],
    ["clock out", "Recording your clock-out…"],
    ["approve timesheet", "Approving the timesheet…"],
    ["reject timesheet", "Submitting your rejection…"],
    ["cancel shift", "Cancelling the shift…"],
    ["create employee", "Creating the employee…"],
    ["save changes", "Saving your changes…"],
    ["save settings", "Saving your settings…"],
    ["save profile", "Saving your profile…"],
    ["create shift", "Creating the shift…"],
    ["save shift", "Saving the shift…"],
    ["deactivate employee", "Updating employee access…"],
    ["activate employee", "Updating employee access…"],
    ["reactivate employee", "Restoring employee access…"],
    ["send a new activation link", "Sending a new activation link…"],
    ["send activation link", "Sending the activation link…"],
  ]);

  function normalizedText(element) {
    return (element?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function showValidationToast() {
    if (toastRegion.querySelector(".toast--error")) return;

    const messages = Array.from(
      document.querySelectorAll(".error-list[role='alert'], form .field-error"),
    )
      .map(normalizedText)
      .filter(Boolean);
    const uniqueMessages = [...new Set(messages)];

    if (uniqueMessages.length) {
      const summary = uniqueMessages.slice(0, 3).join(" ");
      toastApi.show("error", summary, { duration: 8000 });
    }
  }

  function attachSubmissionFeedback(form) {
    if (form.dataset.authForm !== undefined) return;

    form.addEventListener("submit", (event) => {
      if (event.defaultPrevented) return;
      if (form.dataset.toastSubmitting === "true") {
        event.preventDefault();
        return;
      }

      form.dataset.toastSubmitting = "true";
      form.setAttribute("aria-busy", "true");

      const submitter = event.submitter || form.querySelector(
        'button[type="submit"], input[type="submit"], button:not([type])',
      );
      if (submitter) {
        submitter.disabled = true;
        submitter.setAttribute("aria-busy", "true");
      }

      const action = normalizedText(submitter).toLowerCase();
      const message = form.dataset.toastLoadingMessage
        || loadingMessages.get(action)
        || "Submitting your request…";
      toastApi.show("loading", message, { persistent: true });
    });
  }

  document.querySelectorAll("form").forEach((form) => {
    if (form.method.toLowerCase() === "post") attachSubmissionFeedback(form);
  });

  showValidationToast();
})();
