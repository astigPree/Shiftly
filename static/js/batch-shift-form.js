(() => {
  const form = document.querySelector("[data-batch-shift-form]");
  if (!form) return;

  const picker = form.querySelector("[data-employee-picker]");
  const search = picker?.querySelector("[data-employee-search]");
  const selectionInput = picker?.querySelector("[data-employee-selection-input]");
  const options = Array.from(picker?.querySelectorAll("[data-employee-option]") || []);
  const count = picker?.querySelector("[data-employee-selection-count]");
  const selectedList = picker?.querySelector("[data-selected-employees]");
  const noResults = picker?.querySelector("[data-no-employee-results]");
  const selectVisible = picker?.querySelector("[data-select-visible]");
  const clearSelection = picker?.querySelector("[data-clear-selection]");
  const reviewDialog = form.querySelector("[data-batch-review-dialog]");
  const stepInput = form.querySelector("[data-batch-step]");
  const mainSubmit = form.querySelector("[data-batch-main-submit]");

  const normalize = (value) => value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLocaleLowerCase();

  const checkedOptions = () => options.filter((option) =>
    option.querySelector("[data-employee-checkbox]")?.checked,
  );

  const updateSearch = () => {
    const query = normalize(search?.value || "");
    let visibleCount = 0;
    options.forEach((option) => {
      const matches = normalize(option.dataset.search || "").includes(query);
      option.hidden = !matches;
      if (matches) visibleCount += 1;
    });
    if (noResults) noResults.hidden = visibleCount > 0;
    if (selectVisible) {
      selectVisible.textContent = query ? "Select filtered" : "Select all active";
    }
  };

  const invalidateReview = () => {
    if (!stepInput || !mainSubmit) return;
    stepInput.value = "review";
    form.dataset.reviewBatch = "false";
    updateSubmitLabel();
  };

  const updateSubmitLabel = () => {
    if (!mainSubmit) return;
    const selectedCount = checkedOptions().length;
    mainSubmit.disabled = selectedCount === 0;
    if (selectedCount > 1) {
      mainSubmit.textContent = "Review shifts";
    } else if (selectedCount === 1) {
      mainSubmit.textContent = "Create shift";
    } else {
      mainSubmit.textContent = "Select employees";
    }
  };

  const updateSelection = ({ changed = false } = {}) => {
    const selected = checkedOptions();
    const selectedIds = selected.map((option) => option.dataset.employeeId);
    options.forEach((option) => {
      const checkbox = option.querySelector("[data-employee-checkbox]");
      option.classList.toggle("is-selected", Boolean(checkbox?.checked));
    });
    if (selectionInput) selectionInput.value = JSON.stringify(selectedIds);
    if (count) count.textContent = `${selected.length} selected`;
    updateSubmitLabel();

    if (selectedList) {
      selectedList.replaceChildren();
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
          updateSelection({ changed: true });
        });
        chip.append(remove);
        selectedList.append(chip);
      });
      selectedList.hidden = selected.length === 0;
    }

    if (changed) invalidateReview();
  };

  search?.addEventListener("input", updateSearch);
  options.forEach((option) => {
    option.querySelector("[data-employee-checkbox]")?.addEventListener("change", () => {
      updateSelection({ changed: true });
    });
  });

  selectVisible?.addEventListener("click", () => {
    options.forEach((option) => {
      if (!option.hidden) {
        const checkbox = option.querySelector("[data-employee-checkbox]");
        if (checkbox) checkbox.checked = true;
      }
    });
    updateSelection({ changed: true });
  });

  clearSelection?.addEventListener("click", () => {
    options.forEach((option) => {
      const checkbox = option.querySelector("[data-employee-checkbox]");
      if (checkbox) checkbox.checked = false;
    });
    updateSelection({ changed: true });
    search?.focus();
  });

  updateSearch();
  updateSelection();

  form.addEventListener("input", (event) => {
    if (event.target !== selectionInput) invalidateReview();
  });
  form.addEventListener("change", (event) => {
    if (event.target !== selectionInput) invalidateReview();
  });

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
