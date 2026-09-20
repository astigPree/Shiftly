(() => {
  document.querySelectorAll("[data-auth-form]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const invalidField = form.querySelector(":invalid");
      if (invalidField) {
        event.preventDefault();
        invalidField.setAttribute("aria-invalid", "true");
        invalidField.closest(".auth-field")?.classList.add("auth-field--invalid");
        invalidField.focus();
        window.ShiftlyToasts?.show(
          "error",
          form.dataset.validationMessage || "Check the highlighted fields and try again.",
          { duration: 7000 },
        );
        return;
      }

      if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }

      form.dataset.submitting = "true";
      form.setAttribute("aria-busy", "true");
      const button = form.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        button.replaceChildren();

        const spinner = document.createElement("span");
        spinner.className = "button-spinner";
        spinner.setAttribute("aria-hidden", "true");
        const label = document.createElement("span");
        label.textContent = button.dataset.loadingLabel || "Please wait...";
        button.append(spinner, label);
      }

      window.ShiftlyToasts?.show(
        "loading",
        form.dataset.loadingMessage || "Please wait while we finish this request.",
        { persistent: true },
      );
    });

    form.addEventListener("input", (event) => {
      const field = event.target;
      if (field.matches(":invalid")) return;
      field.removeAttribute("aria-invalid");
      field.closest(".auth-field")?.classList.remove("auth-field--invalid");
    });
  });

  document.querySelectorAll("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.target);
      const icon = button.querySelector("img");
      if (!input || !icon) return;

      const showPassword = input.type === "password";
      input.type = showPassword ? "text" : "password";
      button.setAttribute("aria-label", showPassword ? "Hide password" : "Show password");
      icon.src = showPassword ? button.dataset.visibleIcon : button.dataset.hiddenIcon;
      input.focus();
    });
  });
})();
