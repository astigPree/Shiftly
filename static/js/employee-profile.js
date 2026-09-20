(() => {
  const dialog = document.querySelector("[data-deactivation-dialog]");
  const openButton = document.querySelector("[data-open-deactivation-dialog]");
  if (!dialog || !openButton) return;

  const closeButton = dialog.querySelector("[data-close-deactivation-dialog]");
  const confirmForm = dialog.querySelector("form");

  openButton.addEventListener("click", () => {
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
      return;
    }
    if (window.confirm("Deactivate this employee? They will lose sign-in access, but their work history will be kept.")) {
      confirmForm.requestSubmit();
    }
  });

  closeButton?.addEventListener("click", () => dialog.close());

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
})();
