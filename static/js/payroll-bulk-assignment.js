(() => {
  const dialog = document.getElementById("bulk-rule-assignment-dialog");
  if (!(dialog instanceof HTMLDialogElement)) return;
  const count = dialog.querySelector("[data-bulk-selected-count]");
  const hidden = dialog.querySelector("[data-bulk-hidden-employees]");
  const selected = () => Array.from(document.querySelectorAll("[data-bulk-employee]:checked"));
  const sync = () => {
    const checks = selected();
    if (count) count.textContent = checks.length ? `${checks.length} employee${checks.length === 1 ? "" : "s"} selected` : "Select employees from the table.";
    if (hidden) {
      hidden.replaceChildren(...checks.map((checkbox) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "employees";
        input.value = checkbox.value;
        return input;
      }));
    }
  };
  document.querySelectorAll("[data-bulk-employee]").forEach((checkbox) => checkbox.addEventListener("change", sync));
  document.querySelectorAll('[data-payroll-dialog-open="bulk-rule-assignment-dialog"]').forEach((button) => button.addEventListener("click", () => { sync(); dialog.showModal(); }));
  if (dialog.dataset.payrollAutopen === "true") {
    sync();
    if (!dialog.open) dialog.showModal();
  }
  dialog.addEventListener("close", sync);
})();
