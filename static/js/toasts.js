(() => {
  const region = document.querySelector("[data-toast-region]");
  if (!region) return;

  const iconPaths = {
    error: region.dataset.toastIconError,
    loading: region.dataset.toastIconLoading,
    success: region.dataset.toastIconSuccess,
    warning: region.dataset.toastIconWarning,
    info: region.dataset.toastIconInfo,
  };

  function dismiss(toast) {
    if (!toast || toast.dataset.dismissed) return;
    toast.dataset.dismissed = "true";
    toast.classList.add("toast--leaving");
    window.setTimeout(() => toast.remove(), 220);
  }

  function schedule(toast) {
    const closeButton = toast.querySelector("[data-toast-dismiss]");
    if (closeButton) closeButton.addEventListener("click", () => dismiss(toast));
    const duration = Number(toast.dataset.toastDuration || 5000);
    if (duration > 0) window.setTimeout(() => dismiss(toast), duration);
  }

  region.querySelectorAll("[data-toast]").forEach(schedule);

  function show(type, message, options = {}) {
    const toast = document.createElement("section");
    toast.className = `toast toast--${type}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");
    toast.setAttribute("aria-live", type === "error" ? "assertive" : "polite");

    const icon = document.createElement("img");
    icon.className = "toast__icon";
    icon.src = iconPaths[type] || iconPaths.info || "";
    icon.alt = "";

    const copy = document.createElement("div");
    copy.className = "toast__copy";
    const title = document.createElement("strong");
    title.className = "toast__title";
    title.textContent = {
      error: "Please check",
      loading: "Working",
      success: "Success",
      warning: "Attention",
      info: "Notice",
    }[type] || "Notice";
    const body = document.createElement("p");
    body.className = "toast__message";
    body.textContent = message;
    copy.append(title, body);

    const closeButton = document.createElement("button");
    closeButton.className = "toast__dismiss";
    closeButton.type = "button";
    closeButton.setAttribute("aria-label", "Dismiss notification");
    closeButton.textContent = "\u00d7";
    closeButton.addEventListener("click", () => dismiss(toast));

    toast.append(icon, copy, closeButton);
    region.append(toast);
    window.requestAnimationFrame(() => toast.classList.add("toast--shown"));

    const duration = options.persistent ? 0 : Number(options.duration || 6000);
    if (duration > 0) window.setTimeout(() => dismiss(toast), duration);
    return toast;
  }

  window.ShiftlyToasts = { show, dismiss };
})();
