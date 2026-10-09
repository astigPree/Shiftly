(() => {
  const forms = document.querySelectorAll("[data-statutory-review-form]");
  if (!forms.length || typeof window.fetch !== "function") return;

  function openLinkedPanel() {
    if (!window.location.hash) return;
    const linkedPanel = document.querySelector(window.location.hash);
    if (linkedPanel?.tagName === "DETAILS") linkedPanel.open = true;
  }
  openLinkedPanel();
  window.addEventListener("pageshow", openLinkedPanel);
  window.addEventListener("hashchange", openLinkedPanel);

  function showToast(type, message) {
    if (window.ShiftlyToasts && typeof window.ShiftlyToasts.show === "function") {
      window.ShiftlyToasts.show(type, message);
    }
  }

  async function readResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try {
        return await response.json();
      } catch (error) {
        throw new Error(`The server returned an unreadable review response (HTTP ${response.status}).`);
      }
    }

    if (response.status === 403) {
      throw new Error("Your session or security token expired. Refresh the page, sign in again, and retry the review.");
    }
    if (response.redirected || response.url.includes("/login")) {
      throw new Error("Your session expired. Refresh the page, sign in again, and retry the review.");
    }
    if (response.status >= 500) {
      throw new Error(`The server could not save this review (HTTP ${response.status}). Check the server log for details.`);
    }
    throw new Error(`The server returned an unexpected response (HTTP ${response.status}). Refresh the page and try again.`);
  }

  function updatePendingCount(count) {
    if (count === undefined || count === null || count === "") return;
    const numericCount = Number(count);
    if (!Number.isFinite(numericCount)) return;
    document.querySelectorAll("[data-statutory-pending-count]").forEach((element) => {
      element.textContent = String(numericCount);
    });
    document.querySelectorAll("[data-statutory-pending-label]").forEach((element) => {
      const textNode = Array.from(element.childNodes).find((node) => node.nodeType === Node.TEXT_NODE);
      if (textNode) textNode.textContent = ` employee${numericCount === 1 ? "" : "s"} pending`;
    });
    document.querySelectorAll("[data-statutory-pending-banner]").forEach((element) => {
      const textNode = Array.from(element.childNodes).find((node) => node.nodeType === Node.TEXT_NODE);
      if (textNode) textNode.textContent = ` employee${numericCount === 1 ? "" : "s"} awaiting statutory review`;
      const banner = element.closest(".payroll-run-banner");
      if (banner) banner.hidden = numericCount === 0;
    });
    document.querySelectorAll(".payroll-statutory-summary .payroll-status, #statutory-review > .payroll-section-heading .payroll-status").forEach((status) => {
      status.classList.toggle("payroll-status--needs-review", numericCount > 0);
      status.classList.toggle("payroll-status--ready", numericCount === 0);
    });
    document.querySelectorAll("[data-submit-review-button]").forEach((button) => {
      const blockingExceptions = Number(button.dataset.blockingExceptions) || 0;
      button.disabled = numericCount > 0 || blockingExceptions > 0;
      if (button.disabled) button.setAttribute("aria-describedby", "submit-review-requirements");
      else button.removeAttribute("aria-describedby");
    });
    document.querySelectorAll("[data-submit-readiness-banner]").forEach((banner) => {
      const blockingExceptions = Number(banner.dataset.blockingExceptions) || 0;
      if (blockingExceptions > 0) return;
      banner.classList.toggle("payroll-run-banner--neutral", numericCount > 0);
      banner.classList.toggle("payroll-run-banner--success", numericCount === 0);
      const title = banner.querySelector("[data-submit-readiness-title]");
      const copy = banner.querySelector("[data-submit-readiness-copy]");
      if (title) title.textContent = numericCount > 0 ? "Calculation checks passed" : "Ready for review";
      if (copy) copy.textContent = numericCount > 0
        ? "Complete the statutory reviews before submitting this draft."
        : "All submission checks have passed. You can submit this draft for review.";
    });

    const summary = document.querySelector(".payroll-statutory-summary");
    if (summary && numericCount === 0 && !summary.querySelector("[data-statutory-summary-complete]")) {
      const list = summary.querySelector("[data-statutory-summary-list]");
      if (list) {
        list.outerHTML = '<div class="payroll-empty-state payroll-empty-state--success" data-statutory-summary-complete><span class="payroll-empty-icon" aria-hidden="true">✓</span><div><h3>Statutory review complete</h3><p>All statutory items have been reviewed.</p></div></div>';
      }
    }

    const reviewSection = document.querySelector("#statutory-review");
    if (reviewSection && numericCount === 0 && !reviewSection.querySelector("[data-statutory-review-complete]")) {
      const needed = reviewSection.querySelector("[data-statutory-review-needed]");
      if (needed) {
        needed.outerHTML = '<div class="payroll-empty-state" data-statutory-review-complete><span class="payroll-empty-icon" aria-hidden="true">✓</span><div><h3>Statutory review complete</h3><p>All statements have reviewed contribution and withholding lines.</p></div></div>';
      }
    }
  }

  function updateEmployeeSummary(statementId, data) {
    const row = document.querySelector(`[data-statutory-summary-row="${statementId}"]`);
    if (!row) return;
    if (data.complete) {
      row.remove();
      return;
    }
    const progress = row.querySelector("[data-statutory-row-progress]");
    if (progress) {
      const textNode = Array.from(progress.childNodes).find((node) => node.nodeType === Node.TEXT_NODE);
      if (textNode) textNode.textContent = `${data.reviewed_count} of ${data.total_count} reviewed`;
    }
  }

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-statutory-review-form]");
    if (!form) return;
    event.preventDefault();
    if (form.dataset.submitting === "true") return;
    form.dataset.submitting = "true";

    const submitButton = form.querySelector("button[type=submit]");
    const originalLabel = submitButton ? submitButton.textContent : "";
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Saving…";
    }

    try {
      const action = form.getAttribute("action") || window.location.href;
      const response = await fetch(new URL(action, window.location.href).href, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
        credentials: "same-origin",
      });
      const data = await readResponse(response);
      if (!data.html || (!response.ok && response.status !== 422)) {
        throw new Error(data.message || `The review could not be saved (HTTP ${response.status}).`);
      }

      const currentDetails = form.closest(".payroll-statutory-review");
      let updatedDetails = null;
      if (currentDetails) {
        const holder = document.createElement("div");
        holder.innerHTML = data.html.trim();
        updatedDetails = holder.firstElementChild;
        if (updatedDetails) {
          updatedDetails.open = true;
          currentDetails.replaceWith(updatedDetails);
        }
      }
      updatePendingCount(data.pending_count);
      updateEmployeeSummary(form.querySelector("[name=statement_id]")?.value, data);
      showToast(data.ok ? "success" : "error", data.message || (data.ok ? "Statutory review saved." : "Check the review fields and try again."));
      if (!data.ok && updatedDetails) {
        const firstInvalid = updatedDetails.querySelector("[aria-invalid='true'], .form-field--invalid input, .form-field--invalid select, .form-field--invalid textarea");
        const firstError = updatedDetails.querySelector(".field-error");
        (firstInvalid || firstError)?.scrollIntoView({ behavior: "smooth", block: "center" });
        firstInvalid?.focus({ preventScroll: true });
      }
      if (!data.ok && submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = originalLabel;
      }
    } catch (error) {
      const message = error instanceof TypeError
        ? "The server could not be reached. Check that Shiftly is running and try again."
        : (error.message || "The review could not be saved. Refresh the page and try again.");
      showToast("error", message);
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = originalLabel;
      }
    } finally {
      delete form.dataset.submitting;
    }
  });
})();
