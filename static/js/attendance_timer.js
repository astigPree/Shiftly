(() => {
  const timers = document.querySelectorAll("[data-base-seconds]");

  function renderTimers() {
    const now = Date.now();
    for (const timer of timers) {
      const base = Number.parseInt(timer.dataset.baseSeconds, 10);
      const startedAt = timer.dataset.startedAt ? Date.parse(timer.dataset.startedAt) : Number.NaN;
      const elapsed = Number.isFinite(startedAt) ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0;
      const total = Math.max(0, (Number.isFinite(base) ? base : 0) + elapsed);
      const hours = String(Math.floor(total / 3600)).padStart(2, "0");
      const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
      const seconds = String(total % 60).padStart(2, "0");
      timer.textContent = `${hours}:${minutes}:${seconds}`;
    }
  }

  if (timers.length) {
    renderTimers();
    window.setInterval(renderTimers, 1000);
  }
})();
