(() => {
  const form = document.querySelector("[data-batch-shift-form]");
  if (!form) return;

  const employeePicker = form.querySelector("[data-employee-picker]");
  const datePicker = form.querySelector("[data-multi-date-picker]");
  if (!employeePicker || !datePicker) return;

  const employeeSearch = employeePicker.querySelector("[data-employee-search]");
  const employeeInput = employeePicker.querySelector("[data-employee-selection-input]");
  const employeeOptions = Array.from(
    employeePicker.querySelectorAll("[data-employee-option]"),
  );
  const employeeCount = employeePicker.querySelector("[data-employee-selection-count]");
  const selectedEmployees = employeePicker.querySelector("[data-selected-employees]");
  const noEmployeeResults = employeePicker.querySelector("[data-no-employee-results]");
  const selectVisibleEmployees = employeePicker.querySelector("[data-select-visible]");
  const clearEmployeeSelection = employeePicker.querySelector("[data-clear-selection]");

  const dateInput = datePicker.querySelector("[data-work-date-selection-input]");
  const dateGrid = datePicker.querySelector("[data-calendar-grid]");
  const weekdayRow = datePicker.querySelector("[data-calendar-weekdays]");
  const monthLabel = datePicker.querySelector("[data-calendar-month]");
  const selectedDateCount = datePicker.querySelector("[data-selected-date-count]");
  const selectedDateList = datePicker.querySelector("[data-selected-date-list]");
  const datePickerStatus = datePicker.querySelector("[data-date-picker-status]");
  const clearDates = datePicker.querySelector("[data-clear-dates]");

  const reviewDialog = form.querySelector("[data-batch-review-dialog]");
  const stepInput = form.querySelector("[data-batch-step]");
  const mainSubmit = form.querySelector("[data-batch-main-submit]");
  const maxDates = Number(datePicker.dataset.maxDates) || 90;
  const maxAssignments = Number(datePicker.dataset.maxAssignments) || 1000;
  const dayFormatter = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
  const monthFormatter = new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  const shortDateFormatter = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

  const normalize = (value) => value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLocaleLowerCase();

  const checkedEmployeeOptions = () => employeeOptions.filter((option) =>
    option.querySelector("[data-employee-checkbox]")?.checked,
  );

  const parseIsoDate = (value) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return null;
    const parsed = new Date(`${value}T12:00:00Z`);
    return Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value
      ? null
      : parsed;
  };

  const formatIsoDate = (date) => date.toISOString().slice(0, 10);
  const selectedWorkDates = new Set();
  try {
    const initialDates = JSON.parse(dateInput?.value || "[]");
    if (Array.isArray(initialDates)) {
      initialDates.forEach((value) => {
        if (parseIsoDate(value)) selectedWorkDates.add(value);
      });
    }
  } catch (error) {
    // The server will report malformed submitted date data; keep the picker usable.
  }

  let visibleMonth = parseIsoDate(
    [...selectedWorkDates].sort()[0] || datePicker.dataset.today,
  ) || new Date();
  visibleMonth = new Date(Date.UTC(visibleMonth.getUTCFullYear(), visibleMonth.getUTCMonth(), 1, 12));
  let focusedDateValue = datePicker.dataset.today || formatIsoDate(new Date());

  let dateConflictCounts = {};
  try {
    const conflicts = JSON.parse(datePicker.dataset.dateConflicts || "{}");
    if (conflicts && typeof conflicts === "object" && !Array.isArray(conflicts)) {
      dateConflictCounts = Object.fromEntries(
        Object.entries(conflicts).map(([key, value]) => [key, Number(value) || 0]),
      );
    }
  } catch (error) {
    dateConflictCounts = {};
  }

  let statusOverride = "";

  const updateSubmitLabel = () => {
    if (!mainSubmit) return;
    const assignmentCount = checkedEmployeeOptions().length * selectedWorkDates.size;
    const overLimit = selectedWorkDates.size > maxDates || assignmentCount > maxAssignments;
    mainSubmit.disabled = assignmentCount === 0 || overLimit;
    if (overLimit) {
      mainSubmit.textContent = "Reduce the selection";
    } else if (assignmentCount > 1) {
      mainSubmit.textContent = "Review shifts";
    } else if (assignmentCount === 1) {
      mainSubmit.textContent = "Create shift";
    } else {
      mainSubmit.textContent = "Select employees and dates";
    }
  };

  const clearConflictMarks = () => {
    dateConflictCounts = {};
    statusOverride = "";
  };

  const updateDateStatus = () => {
    if (!datePickerStatus) return;
    if (statusOverride) {
      datePickerStatus.textContent = statusOverride;
      return;
    }

    const employeeTotal = checkedEmployeeOptions().length;
    const dateTotal = selectedWorkDates.size;
    const assignmentTotal = employeeTotal * dateTotal;
    const conflictingDateCount = Object.keys(dateConflictCounts).length;
    if (dateTotal > maxDates || assignmentTotal > maxAssignments) {
      datePickerStatus.textContent = `This selection is over the limit of ${maxAssignments} employee-date shifts. Remove some employees or dates to continue.`;
    } else if (conflictingDateCount) {
      datePickerStatus.textContent = "Conflict markers show dates where selected employees already have a shift. Remove a marked date or the affected employee.";
    } else if (dateTotal && employeeTotal) {
      datePickerStatus.textContent = `${dateTotal} date${dateTotal === 1 ? "" : "s"} selected · ${assignmentTotal} individual shift${assignmentTotal === 1 ? "" : "s"} will be created. Up to ${maxAssignments} shifts per submission.`;
    } else if (dateTotal) {
      datePickerStatus.textContent = `${dateTotal} date${dateTotal === 1 ? "" : "s"} selected. Choose employees to see how many individual shifts will be created.`;
    } else {
      datePickerStatus.textContent = `Choose one or more dates. You can select up to ${maxDates} dates and create up to ${maxAssignments} shifts at once.`;
    }
  };

  const renderSelectedDates = () => {
    const dates = [...selectedWorkDates].sort();
    if (dateInput) dateInput.value = JSON.stringify(dates);
    dateInput?.dispatchEvent(new Event("change", { bubbles: true }));
    if (selectedDateCount) {
      selectedDateCount.textContent = `${dates.length} date${dates.length === 1 ? "" : "s"} selected`;
    }
    if (clearDates) clearDates.disabled = dates.length === 0;

    if (selectedDateList) {
      selectedDateList.replaceChildren();
      dates.forEach((value) => {
        const parsedDate = parseIsoDate(value);
        if (!parsedDate) return;
        const chip = document.createElement("span");
        chip.className = "multi-date-picker__chip";
        const label = document.createElement("span");
        label.textContent = shortDateFormatter.format(parsedDate);
        chip.append(label);

        const conflictCount = dateConflictCounts[value] || 0;
        if (conflictCount) {
          const conflict = document.createElement("span");
          conflict.className = "multi-date-picker__chip-conflict";
          conflict.textContent = `${conflictCount} conflict${conflictCount === 1 ? "" : "s"}`;
          chip.append(conflict);
        }

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "multi-date-picker__chip-remove";
        remove.setAttribute("aria-label", `Remove ${dayFormatter.format(parsedDate)}`);
        remove.textContent = String.fromCharCode(215);
        remove.addEventListener("click", () => toggleDate(value));
        chip.append(remove);
        selectedDateList.append(chip);
      });
      selectedDateList.hidden = dates.length === 0;
    }
  };

  const renderWeekdays = () => {
    if (!weekdayRow) return;
    weekdayRow.replaceChildren();
    for (let day = 0; day < 7; day += 1) {
      const date = new Date(Date.UTC(2023, 0, 1 + day, 12));
      const label = new Intl.DateTimeFormat(undefined, {
        weekday: "short",
        timeZone: "UTC",
      }).format(date);
      const heading = document.createElement("span");
      heading.textContent = label;
      weekdayRow.append(heading);
    }
  };

  const renderCalendar = () => {
    if (!dateGrid || !monthLabel) return;
    monthLabel.textContent = monthFormatter.format(visibleMonth);
    dateGrid.replaceChildren();
    const firstDay = new Date(Date.UTC(
      visibleMonth.getUTCFullYear(), visibleMonth.getUTCMonth(), 1, 12,
    ));
    const startOffset = firstDay.getUTCDay();
    const focusDate = parseIsoDate(focusedDateValue);
    const todayDate = parseIsoDate(datePicker.dataset.today || "");
    const focusIsVisible = focusDate
      && focusDate.getUTCMonth() === visibleMonth.getUTCMonth()
      && focusDate.getUTCFullYear() === visibleMonth.getUTCFullYear();
    const todayIsVisible = todayDate
      && todayDate.getUTCMonth() === visibleMonth.getUTCMonth()
      && todayDate.getUTCFullYear() === visibleMonth.getUTCFullYear();
    const defaultFocusableDate = focusIsVisible
      ? focusedDateValue
      : todayIsVisible
        ? datePicker.dataset.today
        : formatIsoDate(firstDay);

    let weekRow;
    for (let index = 0; index < 42; index += 1) {
      if (index % 7 === 0) {
        weekRow = document.createElement("div");
        weekRow.className = "multi-date-picker__week";
        weekRow.setAttribute("role", "row");
        dateGrid.append(weekRow);
      }
      const date = new Date(Date.UTC(
        visibleMonth.getUTCFullYear(),
        visibleMonth.getUTCMonth(),
        1 - startOffset + index,
        12,
      ));
      const value = formatIsoDate(date);
      const cell = document.createElement("div");
      cell.className = "multi-date-picker__cell";
      cell.setAttribute("role", "gridcell");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "multi-date-picker__day";
      button.dataset.date = value;
      button.tabIndex = value === defaultFocusableDate ? 0 : -1;
      button.setAttribute("aria-pressed", selectedWorkDates.has(value) ? "true" : "false");
      button.classList.toggle("is-selected", selectedWorkDates.has(value));
      button.classList.toggle(
        "is-outside-month",
        date.getUTCMonth() !== visibleMonth.getUTCMonth(),
      );
      if (value === datePicker.dataset.today) button.classList.add("is-today");
      button.textContent = String(date.getUTCDate());

      const conflictCount = dateConflictCounts[value] || 0;
      button.setAttribute(
        "aria-label",
        conflictCount
          ? `${dayFormatter.format(date)}, ${conflictCount} employee conflict${conflictCount === 1 ? "" : "s"}`
          : dayFormatter.format(date),
      );
      if (conflictCount) {
        button.classList.add("has-conflict");
        button.title = `${dayFormatter.format(date)} · ${conflictCount} employee conflict${conflictCount === 1 ? "" : "s"}`;
        const marker = document.createElement("span");
        marker.className = "multi-date-picker__conflict-marker";
        marker.setAttribute("aria-hidden", "true");
        button.append(marker);
      }

      button.addEventListener("click", () => toggleDate(value, date));
      cell.append(button);
      weekRow.append(cell);
    }
  };

  const updateCalendar = () => {
    renderCalendar();
    renderSelectedDates();
    updateSubmitLabel();
    updateDateStatus();
  };

  function toggleDate(value, dateToShow = parseIsoDate(value)) {
    const isRemoving = selectedWorkDates.has(value);
    if (isRemoving) {
      selectedWorkDates.delete(value);
    } else {
      const selectedEmployeeTotal = checkedEmployeeOptions().length;
      const nextDateTotal = selectedWorkDates.size + 1;
      const nextAssignmentTotal = selectedEmployeeTotal * nextDateTotal;
      if (nextDateTotal > maxDates) {
        statusOverride = `You can select up to ${maxDates} dates at a time.`;
        updateDateStatus();
        return;
      }
      if (nextAssignmentTotal > maxAssignments) {
        statusOverride = `That date would exceed the ${maxAssignments}-shift limit. Remove employees or dates first.`;
        updateDateStatus();
        return;
      }
      selectedWorkDates.add(value);
    }

    clearConflictMarks();
    if (!isRemoving && dateToShow && (
      dateToShow.getUTCMonth() !== visibleMonth.getUTCMonth()
      || dateToShow.getUTCFullYear() !== visibleMonth.getUTCFullYear()
    )) {
      visibleMonth = new Date(Date.UTC(
        dateToShow.getUTCFullYear(), dateToShow.getUTCMonth(), 1, 12,
      ));
    }
    focusedDateValue = value;
    updateCalendar();
    dateGrid?.querySelector(`[data-date="${value}"]`)?.focus();
    invalidateReview();
  }

  const filterEmployees = () => {
    const query = normalize(employeeSearch?.value || "");
    let visibleCount = 0;
    employeeOptions.forEach((option) => {
      const matches = normalize(option.dataset.search || "").includes(query);
      option.hidden = !matches;
      if (matches) visibleCount += 1;
    });
    if (noEmployeeResults) noEmployeeResults.hidden = visibleCount > 0;
    if (selectVisibleEmployees) {
      selectVisibleEmployees.textContent = query ? "Select filtered" : "Select all active";
    }
  };

  const updateEmployeeSelection = ({ changed = false } = {}) => {
    const selected = checkedEmployeeOptions();
    selected.forEach((option) => option.classList.add("is-selected"));
    employeeOptions.forEach((option) => {
      if (!selected.includes(option)) option.classList.remove("is-selected");
    });
    if (employeeInput) {
      employeeInput.value = JSON.stringify(
        selected.map((option) => option.dataset.employeeId),
      );
    }
    if (employeeCount) employeeCount.textContent = `${selected.length} selected`;

    if (selectedEmployees) {
      selectedEmployees.replaceChildren();
      selected.forEach((option) => {
        const checkbox = option.querySelector("[data-employee-checkbox]");
        const chip = document.createElement("span");
        chip.className = "employee-picker__chip";
        const name = document.createElement("span");
        name.textContent = option.dataset.name || "Employee";
        chip.append(name);

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "employee-picker__chip-remove";
        remove.setAttribute("aria-label", `Remove ${option.dataset.name || "employee"}`);
        remove.textContent = String.fromCharCode(215);
        remove.addEventListener("click", () => {
          if (checkbox) checkbox.checked = false;
          updateEmployeeSelection({ changed: true });
        });
        chip.append(remove);
        selectedEmployees.append(chip);
      });
      selectedEmployees.hidden = selected.length === 0;
    }

    updateSubmitLabel();
    updateDateStatus();
    if (changed) {
      clearConflictMarks();
      updateCalendar();
      invalidateReview();
    }
  };

  employeeSearch?.addEventListener("input", filterEmployees);
  employeeOptions.forEach((option) => {
    option.querySelector("[data-employee-checkbox]")?.addEventListener("change", (event) => {
      const selected = checkedEmployeeOptions();
      if (
        event.target.checked
        && selected.length * selectedWorkDates.size > maxAssignments
      ) {
        event.target.checked = false;
        statusOverride = `This would exceed the ${maxAssignments}-shift limit. Remove some dates or employees.`;
        updateEmployeeSelection();
        return;
      }
      updateEmployeeSelection({ changed: true });
    });
  });

  selectVisibleEmployees?.addEventListener("click", () => {
    let blocked = false;
    let selectedEmployeeTotal = checkedEmployeeOptions().length;
    employeeOptions.forEach((option) => {
      if (option.hidden) return;
      const checkbox = option.querySelector("[data-employee-checkbox]");
      if (!checkbox || checkbox.checked) return;
      const nextEmployeeCount = selectedEmployeeTotal + 1;
      if (nextEmployeeCount * selectedWorkDates.size > maxAssignments) {
        blocked = true;
        return;
      }
      checkbox.checked = true;
      selectedEmployeeTotal = nextEmployeeCount;
    });
    updateEmployeeSelection({ changed: true });
    if (blocked) {
      statusOverride = `Some employees were left unselected to stay within the ${maxAssignments}-shift limit.`;
      updateDateStatus();
    }
  });

  clearEmployeeSelection?.addEventListener("click", () => {
    employeeOptions.forEach((option) => {
      const checkbox = option.querySelector("[data-employee-checkbox]");
      if (checkbox) checkbox.checked = false;
    });
    updateEmployeeSelection({ changed: true });
    employeeSearch?.focus();
  });

  datePicker.querySelector("[data-calendar-previous]")?.addEventListener("click", () => {
    visibleMonth = new Date(Date.UTC(
      visibleMonth.getUTCFullYear(), visibleMonth.getUTCMonth() - 1, 1, 12,
    ));
    renderCalendar();
  });

  datePicker.querySelector("[data-calendar-next]")?.addEventListener("click", () => {
    visibleMonth = new Date(Date.UTC(
      visibleMonth.getUTCFullYear(), visibleMonth.getUTCMonth() + 1, 1, 12,
    ));
    renderCalendar();
  });

  dateGrid?.addEventListener("keydown", (event) => {
    const dayButton = event.target.closest("[data-date]");
    if (!dayButton) return;
    const currentDate = parseIsoDate(dayButton.dataset.date);
    if (!currentDate) return;

    let dayOffset;
    if (event.key === "ArrowLeft") dayOffset = -1;
    else if (event.key === "ArrowRight") dayOffset = 1;
    else if (event.key === "ArrowUp") dayOffset = -7;
    else if (event.key === "ArrowDown") dayOffset = 7;
    else if (event.key === "Home") dayOffset = -currentDate.getUTCDay();
    else if (event.key === "End") dayOffset = 6 - currentDate.getUTCDay();
    else return;
    event.preventDefault();

    const nextDate = new Date(currentDate);
    nextDate.setUTCDate(nextDate.getUTCDate() + dayOffset);
    focusedDateValue = formatIsoDate(nextDate);
    if (
      nextDate.getUTCMonth() !== visibleMonth.getUTCMonth()
      || nextDate.getUTCFullYear() !== visibleMonth.getUTCFullYear()
    ) {
      visibleMonth = new Date(Date.UTC(
        nextDate.getUTCFullYear(), nextDate.getUTCMonth(), 1, 12,
      ));
    }
    renderCalendar();
    dateGrid.querySelector(`[data-date="${focusedDateValue}"]`)?.focus();
  });

  clearDates?.addEventListener("click", () => {
    selectedWorkDates.clear();
    clearConflictMarks();
    updateCalendar();
    invalidateReview();
  });

  form.querySelectorAll("#id_start_time, #id_end_time").forEach((input) => {
    input.addEventListener("input", () => {
      clearConflictMarks();
      updateCalendar();
      invalidateReview();
    });
    input.addEventListener("change", () => {
      clearConflictMarks();
      updateCalendar();
      invalidateReview();
    });
  });

  function invalidateReview() {
    if (!stepInput || !mainSubmit) return;
    stepInput.value = "review";
    form.dataset.reviewBatch = "false";
    updateSubmitLabel();
  }

  renderWeekdays();
  filterEmployees();
  updateEmployeeSelection();
  updateCalendar();

  if (!reviewDialog || !stepInput || !mainSubmit) return;

  let confirming = false;
  const returnToReview = () => {
    if (confirming) return;
    invalidateReview();
    mainSubmit.focus();
  };

  reviewDialog.addEventListener("close", returnToReview);
  reviewDialog.addEventListener("click", (event) => {
    if (event.target === reviewDialog) reviewDialog.close("back");
  });
  reviewDialog.querySelector("[data-batch-review-back]")?.addEventListener("click", () => {
    reviewDialog.close("back");
  });

  const confirmButton = reviewDialog.querySelector("[data-batch-review-confirm]");
  confirmButton?.addEventListener("click", () => {
    confirming = true;
    confirmButton.disabled = true;
    stepInput.value = "create";
    form.dataset.toastLoadingMessage = "Creating the selected shifts...";
    mainSubmit.textContent = "Creating shifts...";
    reviewDialog.close("confirm");
    form.requestSubmit(mainSubmit);
  });

  if (reviewDialog.dataset.autoOpen === "true" && typeof reviewDialog.showModal === "function") {
    reviewDialog.showModal();
    reviewDialog.querySelector("[data-batch-review-back]")?.focus();
  }
})();
