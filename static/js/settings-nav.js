(() => {
  const page = document.querySelector("[data-settings-page]");
  if (!page) return;

  const links = [...page.querySelectorAll("[data-settings-tab]")];
  const panels = new Map(
    links.map((link) => [link.dataset.settingsTab, document.querySelector(link.hash)]),
  );

  function activate(section) {
    links.forEach((link) => {
      const isActive = link.dataset.settingsTab === section;
      link.classList.toggle("is-active", isActive);
      if (isActive) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }

  links.forEach((link) => {
    link.addEventListener("click", () => activate(link.dataset.settingsTab));
  });

  const hashSection = links.find((link) => link.hash === window.location.hash)?.dataset.settingsTab;
  const activeSection = hashSection || page.dataset.activeSection || "organization";
  activate(activeSection);

  if (page.dataset.scrollToActive === "true") {
    window.requestAnimationFrame(() => {
      panels.get(activeSection)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
})();
