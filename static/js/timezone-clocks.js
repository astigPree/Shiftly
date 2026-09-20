(() => {
  const widgets = document.querySelectorAll("[data-timezone-clocks]");
  if (!widgets.length) return;

  const clockFormatters = new Map();
  const metaFormatters = new Map();

  const getClockFormatter = (zone) => {
    if (!clockFormatters.has(zone)) {
      clockFormatters.set(zone, new Intl.DateTimeFormat(undefined, {
        timeZone: zone,
        hour: "numeric",
        minute: "2-digit",
      }));
    }
    return clockFormatters.get(zone);
  };

  const getMetaFormatter = (zone) => {
    if (!metaFormatters.has(zone)) {
      metaFormatters.set(zone, new Intl.DateTimeFormat(undefined, {
        timeZone: zone,
        weekday: "short",
        month: "short",
        day: "numeric",
        timeZoneName: "shortOffset",
      }));
    }
    return metaFormatters.get(zone);
  };

  const normalizeOffset = (value) => {
    if (value === "GMT" || value === "UTC") return "UTC+00:00";
    const match = /^GMT([+-])(\d{1,2})(?::(\d{2}))?$/.exec(value);
    if (!match) return value.replace(/^GMT/, "UTC");
    return `UTC${match[1]}${match[2].padStart(2, "0")}:${match[3] || "00"}`;
  };

  widgets.forEach((widget) => {
    const serverTimestamp = Date.parse(widget.dataset.now || "");
    if (!Number.isFinite(serverTimestamp)) return;
    const startedAt = performance.now();

    const update = () => {
      const now = new Date(serverTimestamp + (performance.now() - startedAt));
      widget.querySelectorAll("[data-timezone-clock]").forEach((clock) => {
        const zone = clock.dataset.timezone;
        try {
          const time = clock.querySelector(".timezone-clock__time");
          const meta = clock.querySelector(".timezone-clock__meta");
          if (time) {
            time.textContent = getClockFormatter(zone).format(now);
            time.dateTime = now.toISOString();
          }
          if (meta) {
            const parts = getMetaFormatter(zone).formatToParts(now);
            const date = parts
              .filter((part) => part.type !== "timeZoneName")
              .map((part) => part.value)
              .join("")
              .replace(/,\s*$/, "");
            const offset = parts.find((part) => part.type === "timeZoneName")?.value || zone;
            meta.textContent = `${date} · ${normalizeOffset(offset)}`;
          }
        } catch (error) {
          // Keep the server-rendered value if the browser lacks this time zone.
        }
      });
    };

    update();
    window.setInterval(update, 15_000);
  });
})();
