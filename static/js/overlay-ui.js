(() => {
  const dialogs = [...document.querySelectorAll("dialog")];
  const focusableSelector = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled]):not([type='hidden'])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");

  let lastExternalFocus = document.activeElement;
  document.addEventListener("focusin", (event) => {
    if (!event.target.closest("dialog")) lastExternalFocus = event.target;
  });

  const syncScrollLock = () => {
    const open = dialogs.some((dialog) => dialog.open);
    document.documentElement.classList.toggle("overlay-open", open);
    document.body.classList.toggle("overlay-open", open);
  };

  dialogs.forEach((dialog) => {
    let opener = null;

    dialog.addEventListener("toggle", () => {
      if (dialog.open) {
        opener = lastExternalFocus;
        window.requestAnimationFrame(() => {
          const autofocus = dialog.querySelector("[autofocus]");
          const first = dialog.querySelector(focusableSelector);
          (autofocus || first)?.focus();
        });
      } else if (opener instanceof HTMLElement && opener.isConnected) {
        opener.focus();
      }
      syncScrollLock();
    });

    dialog.addEventListener("close", syncScrollLock);
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const focusable = [...dialog.querySelectorAll(focusableSelector)].filter((element) => {
        return element.getClientRects().length && element.getAttribute("aria-hidden") !== "true";
      });
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  });

  const dialogObserver = new MutationObserver(syncScrollLock);
  dialogs.forEach((dialog) => dialogObserver.observe(dialog, { attributes: true, attributeFilter: ["open"] }));

  document.querySelectorAll("details.account-menu").forEach((menu) => {
    menu.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !menu.open) return;
      menu.open = false;
      menu.querySelector("summary")?.focus();
    });
  });

  document.addEventListener("pointerdown", (event) => {
    document.querySelectorAll("details.account-menu[open]").forEach((menu) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });

  syncScrollLock();
})();
