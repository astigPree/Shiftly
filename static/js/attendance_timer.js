(() => {
  const timers = document.querySelectorAll("[data-base-seconds]");
  const clockInControls = document.querySelectorAll("[data-clock-in-opens-at]");

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

  if (clockInControls.length) {
    const loadedAt = performance.now();
    const serverNow = Date.parse(clockInControls[0].dataset.serverNow);

    function updateClockInControls() {
      const elapsedSinceLoad = Math.max(0, performance.now() - loadedAt);
      const estimatedNow = Number.isFinite(serverNow) ? serverNow + elapsedSinceLoad : Date.now();

      for (const control of clockInControls) {
        const opensAt = Date.parse(control.dataset.clockInOpensAt);
        const closesAt = Date.parse(control.dataset.clockInClosesAt);
        const button = control.querySelector('button[type="submit"]');
        const hint = control.querySelector("[data-clock-in-hint]");
        if (!button || !Number.isFinite(opensAt) || !Number.isFinite(closesAt)) continue;

        const isOpen = estimatedNow >= opensAt && estimatedNow < closesAt;
        button.disabled = !isOpen;
        control.classList.toggle("is-available", isOpen);

        if (hint && isOpen) hint.textContent = "Clock in is available now.";
        if (hint && estimatedNow >= closesAt) hint.textContent = "The clock-in window has closed. Refresh for the latest schedule status.";
      }
    }

    updateClockInControls();
    window.setInterval(updateClockInControls, 10000);
  }
})();
