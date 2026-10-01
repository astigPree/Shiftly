(() => {
  const forms = document.querySelectorAll("[data-statutory-review-form]");
  if (!forms.length || typeof window.fetch !== "function") return;

  function showToast(type, message) {
    if (window.ShiftlyToasts && typeof window.ShiftlyToasts.show === "function") {
      window.ShiftlyToasts.show(type, message);
    }
  }

  function updatePendingCount(count) {
    const numericCount = Number(count) || 0;
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
    if (!form || form.dataset.submitting === "true") return;
    event.preventDefault();
    form.dataset.submitting = "true";

    const submitButton = form.querySelector("button[type=submit]");
    const originalLabel = submitButton ? submitButton.textContent : "";
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = "Saving…";
    }

    try {
      const response = await fetch(form.action || window.location.href, {
        method: "POST",
        body: new FormData(form),
        headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
        credentials: "same-origin",
      });
      let data;
      try {
        data = await response.json();
      } catch (error) {
        throw new Error("The review could not be saved. Refresh the page and try again.");
      }
      if (!response.ok || !data.html) throw new Error(data.message || "The review could not be saved.");

      const currentDetails = form.closest(".payroll-statutory-review");
      if (currentDetails) {
        const holder = document.createElement("div");
        holder.innerHTML = data.html.trim();
        const updatedDetails = holder.firstElementChild;
        if (updatedDetails) {
          updatedDetails.open = true;
          currentDetails.replaceWith(updatedDetails);
        }
      }
      updatePendingCount(data.pending_count);
      updateEmployeeSummary(form.querySelector("[name=statement_id]")?.value, data);
      showToast(data.ok ? "success" : "error", data.message || (data.ok ? "Statutory review saved." : "Check the review fields and try again."));
    } catch (error) {
      showToast("error", error.message || "The review could not be saved. Refresh the page and try again.");
      if (submitButton) {
        submitButton.disabled = false;
        submitButton.textContent = originalLabel;
      }
    } finally {
      delete form.dataset.submitting;
    }
  });
})();
