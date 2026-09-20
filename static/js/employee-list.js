(() => {
  document.querySelectorAll("[data-submit-on-change]").forEach((control) => {
    control.addEventListener("change", () => {
      control.form?.requestSubmit();
    });
  });
})();
