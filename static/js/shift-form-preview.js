(() => {
  const form = document.querySelector("[data-shift-form]");
  const preview = form?.querySelector("[data-shift-time-preview]");
  if (!form || !preview) return;

  const dateField = form.querySelector("#id_work_date");
  const startField = form.querySelector("#id_start_time");
  const endField = form.querySelector("#id_end_time");
  const title = preview.querySelector("[data-shift-preview-title]");
  const companyLine = preview.querySelector("[data-shift-preview-company]");
  const viewerLine = preview.querySelector("[data-shift-preview-viewer]");
  const companyTimezone = form.dataset.organizationTimezone || "UTC";
  const viewerTimezone = form.dataset.viewerTimezone || companyTimezone;
  const companyLabel = form.dataset.companyLabel || companyTimezone;
  const viewerLabel = form.dataset.viewerLabel || viewerTimezone;
  if (!dateField || !startField || !endField || !title || !companyLine || !viewerLine) return;

  const parseTime = (value) => {
    const match = /^(\d{2}):(\d{2})$/.exec(value);
    return match ? { hour: Number(match[1]), minute: Number(match[2]) } : null;
  };

  const parseDate = (value) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    return match ? { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) } : null;
  };

  const getZonedParts = (instant, zone) => {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(instant);
    return Object.fromEntries(parts.map((part) => [part.type, Number(part.value)]));
  };

  const sameWallTime = (left, right) =>
    left.year === right.year && left.month === right.month && left.day === right.day &&
    left.hour === right.hour && left.minute === right.minute;

  // A wall time can map to zero instants during a DST gap or two during a DST fold.
  // Treat both as invalid, matching the server-side shift form validation.
  const wallTimeToInstant = (wallTime, zone) => {
    const target = Date.UTC(
      wallTime.year, wallTime.month - 1, wallTime.day, wallTime.hour, wallTime.minute,
    );
    const offsets = new Set();
    for (let hours = -36; hours <= 36; hours += 6) {
      const probe = new Date(target + hours * 60 * 60 * 1000);
      const local = getZonedParts(probe, zone);
      const localAsUtc = Date.UTC(
        local.year, local.month - 1, local.day, local.hour, local.minute,
      );
      offsets.add(localAsUtc - probe.getTime());
    }

    const matches = [];
    offsets.forEach((offset) => {
      const candidate = new Date(target - offset);
      if (sameWallTime(getZonedParts(candidate, zone), wallTime)) matches.push(candidate);
    });
    return matches.length === 1 ? matches[0] : null;
  };

  const dateOnly = (parts) => new Date(Date.UTC(parts.year, parts.month - 1, parts.day, 12));
  const formatDate = (date) => new Intl.DateTimeFormat(undefined, {
    timeZone: "UTC",
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
  const formatWallTime = (time) => new Intl.DateTimeFormat(undefined, {
    timeZone: "UTC",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(Date.UTC(2000, 0, 1, time.hour, time.minute)));
  const formatInZone = (instant, zone) => new Intl.DateTimeFormat(undefined, {
    timeZone: zone,
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(instant);

  const nextDate = (date) => {
    const next = new Date(Date.UTC(date.year, date.month - 1, date.day + 1, 12));
    return { year: next.getUTCFullYear(), month: next.getUTCMonth() + 1, day: next.getUTCDate() };
  };

  const updatePreview = () => {
    const start = parseTime(startField.value);
    const end = parseTime(endField.value);
    const date = parseDate(dateField.value);
    preview.classList.remove("shift-time-preview--overnight", "shift-time-preview--invalid");
    viewerLine.hidden = true;
    viewerLine.textContent = "";

    if (!start || !end) {
      title.textContent = "Shift time preview";
      companyLine.textContent = "Enter a date and times to preview the shift in your organization's time zone.";
      return;
    }

    if (start.hour === end.hour && start.minute === end.minute) {
      preview.classList.add("shift-time-preview--invalid");
      title.textContent = "Check the shift times";
      companyLine.textContent = "Start and end times must be different.";
      return;
    }

    const startMinutes = start.hour * 60 + start.minute;
    const endMinutes = end.hour * 60 + end.minute;
    const overnight = endMinutes < startMinutes;
    preview.classList.toggle("shift-time-preview--overnight", overnight);
    title.textContent = overnight ? "Overnight shift · ends the next day" : "Same-day shift";

    if (!date) {
      companyLine.textContent = `Company time (${companyLabel}): ${formatWallTime(start)} → ${formatWallTime(end)}${overnight ? " · ends next day" : ""}. Enter a work date to see your local time.`;
      return;
    }

    const endDate = overnight ? nextDate(date) : date;
    const startWallTime = { ...date, ...start };
    const endWallTime = { ...endDate, ...end };
    companyLine.textContent = `Company time (${companyLabel}): ${formatDate(dateOnly(date))}, ${formatWallTime(start)} → ${formatDate(dateOnly(endDate))}, ${formatWallTime(end)} · ${companyTimezone}`;

    if (viewerTimezone === companyTimezone) return;

    try {
      const localStart = wallTimeToInstant(startWallTime, companyTimezone);
      const localEnd = wallTimeToInstant(endWallTime, companyTimezone);
      if (!localStart || !localEnd) {
        preview.classList.add("shift-time-preview--invalid");
        title.textContent = "Choose a different local time";
        viewerLine.hidden = false;
        viewerLine.textContent = `This time is skipped or repeated during a daylight-saving change in ${companyTimezone}. Choose another start or end time.`;
        return;
      }
      viewerLine.hidden = false;
      viewerLine.textContent = `Your time (${viewerLabel}): ${formatInZone(localStart, viewerTimezone)} → ${formatInZone(localEnd, viewerTimezone)}`;
    } catch (error) {
      viewerLine.hidden = false;
      viewerLine.textContent = `Your local time preview is unavailable for ${viewerTimezone}.`;
    }
  };

  [dateField, startField, endField].forEach((field) => {
    field.addEventListener("input", updatePreview);
    field.addEventListener("change", updatePreview);
  });
  updatePreview();
})();
