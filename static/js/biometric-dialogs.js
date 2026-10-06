(() => {
  const dialogs = [...document.querySelectorAll("[data-biometric-dialog]")];
  const overflowMenus = [...document.querySelectorAll("[data-bio-overflow]")];

  const closeMenus = (except = null) => {
    overflowMenus.forEach((details) => {
      if (details !== except) details.open = false;
    });
  };

  const openDialog = (dialog) => {
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (dialog.open) return;
    dialog.showModal();
  };

  dialogs.forEach((dialog) => {
    if (dialog.hasAttribute("open")) {
      dialog.removeAttribute("open");
      openDialog(dialog);
    }
    dialog.querySelectorAll("[data-biometric-dialog-close]").forEach((button) => {
      button.addEventListener("click", () => dialog.close());
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  document.querySelectorAll("[data-biometric-dialog-open]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      closeMenus();
      const targetName = trigger.getAttribute("data-biometric-dialog-open");
      const dialog = dialogs.find((item) => item.getAttribute("data-biometric-dialog") === targetName);
      openDialog(dialog);
    });
  });

  const positionMenu = (details) => {
    const summary = details.querySelector("summary");
    const menu = details.querySelector(".bio-more-menu");
    if (!summary || !menu) return;
    const rect = summary.getBoundingClientRect();
    const menuWidth = menu.offsetWidth || 218;
    const menuHeight = Math.min(menu.scrollHeight || 280, window.innerHeight - 24);
    const left = Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12));
    let top = rect.bottom + 8;
    if (top + menuHeight > window.innerHeight - 12) top = rect.top - menuHeight - 8;
    top = Math.max(12, top);
    details.style.setProperty("--bio-menu-left", `${left}px`);
    details.style.setProperty("--bio-menu-top", `${top}px`);
  };

  overflowMenus.forEach((details) => {
    details.addEventListener("toggle", () => {
      if (!details.open) return;
      closeMenus(details);
      requestAnimationFrame(() => positionMenu(details));
    });
  });

  document.addEventListener("pointerdown", (event) => {
    overflowMenus.forEach((details) => {
      const menu = details.querySelector(".bio-more-menu");
      if (details.open && !details.contains(event.target) && !menu?.contains(event.target)) details.open = false;
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenus();
  });

  const repositionOpenMenus = () => overflowMenus.filter((details) => details.open).forEach(positionMenu);
  window.addEventListener("resize", repositionOpenMenus);
  window.addEventListener("scroll", repositionOpenMenus, { passive: true });
})();
