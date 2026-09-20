(() => {
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
