(() => {
  const dialog = document.getElementById("statement-details-dialog");
  const body = dialog?.querySelector("[data-statement-modal-body]");
  if (!(dialog instanceof HTMLDialogElement) || !body) return;
  const open = (id, updateHash = true) => {
    const template = document.getElementById(`statement-template-${id}`);
    if (!template) return;
    body.replaceChildren(template.content.cloneNode(true));
    if (updateHash) history.replaceState(null, "", `#statement-${id}`);
    dialog.showModal();
    body.querySelector("form[data-payroll-confirm]")?.addEventListener("submit", (event) => {
      if (!window.confirm("Remove this manual payroll line from the draft?")) event.preventDefault();
    });
  };
  document.querySelectorAll("[data-statement-dialog]").forEach((button) => button.addEventListener("click", () => open(button.dataset.statementDialog)));
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => { if (location.hash.startsWith("#statement-")) history.replaceState(null, "", location.pathname + location.search); });
  const hash = location.hash.match(/^#statement-(\d+)$/);
  if (hash) open(hash[1], false);
})();
