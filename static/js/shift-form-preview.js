(() => {
  const form = document.querySelector("[data-shift-form]");
  const preview = form?.querySelector("[data-shift-time-preview]");
  if (!form || !preview) return;

  const dateField = form.querySelector("#id_work_date");
  const startField = form.querySelector("#id_start_time");
  const endField = form.querySelector("#id_end_time");
  const title = preview.querySelector("[data-shift-preview-title]");
  const detail = preview.querySelector("[data-shift-preview-detail]");
  const timezone = form.dataset.organizationTimezone || "organization time";
  if (!dateField || !startField || !endField || !title || !detail) return;

  const parseTime = (value) => {
    const match = /^(\d{2}):(\d{2})$/.exec(value);
    return match ? Number(match[1]) * 60 + Number(match[2]) : null;
  };

  const formatTime = (value) => {
    const [hours, minutes] = value.split(":").map(Number);
    const time = new Date(2000, 0, 1, hours, minutes);
    return new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
    }).format(time);
  };

  const parseDate = (value) => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!match) return null;
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12);
  };

  const formatDate = (date) => new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);

  const updatePreview = () => {
    const start = parseTime(startField.value);
    const end = parseTime(endField.value);
    const date = parseDate(dateField.value);
    preview.classList.remove("shift-time-preview--overnight", "shift-time-preview--invalid");

    if (start === null || end === null) {
      title.textContent = "Shift time preview";
      detail.textContent = "Enter a start and end time to preview the shift. An earlier end time means it ends the next local day.";
      return;
    }

    if (start === end) {
      preview.classList.add("shift-time-preview--invalid");
      title.textContent = "Check the shift times";
      detail.textContent = "Start and end times must be different.";
      return;
    }

    const overnight = end < start;
    const startLabel = formatTime(startField.value);
    const endLabel = formatTime(endField.value);
    const endDate = date ? new Date(date) : null;
    if (overnight && endDate) endDate.setDate(endDate.getDate() + 1);

    if (overnight) {
      preview.classList.add("shift-time-preview--overnight");
      title.textContent = "Overnight shift · ends the next day";
    } else {
      title.textContent = "Same-day shift";
    }

    if (date) {
      detail.textContent = `${formatDate(date)}, ${startLabel} → ${formatDate(endDate)}, ${endLabel} · ${timezone}`;
    } else {
      detail.textContent = `${startLabel} → ${endLabel}${overnight ? " · ends the next local day" : " · same day"} · ${timezone}`;
    }
  };

  [dateField, startField, endField].forEach((field) => {
    field.addEventListener("input", updatePreview);
    field.addEventListener("change", updatePreview);
  });

  updatePreview();
})();
