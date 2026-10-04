(() => {
  const tabGroups = [...document.querySelectorAll("[data-workspace-anchor-tabs]")];

  const setActive = (group, tab) => {
    const tabs = [...group.querySelectorAll("a.workspace-tab[href^='#']")];
    tabs.forEach((item) => {
      const active = item === tab;
      item.classList.toggle("is-active", active);
      if (active) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    });
  };

  const syncWithHash = (group) => {
    if (!window.location.hash) return;
    const tab = [...group.querySelectorAll("a.workspace-tab[href^='#']")].find(
      (item) => item.hash === window.location.hash,
    );
    if (tab) setActive(group, tab);
  };

  tabGroups.forEach((group) => {
    group.addEventListener("click", (event) => {
      const tab = event.target.closest("a.workspace-tab[href^='#']");
      if (tab && group.contains(tab)) setActive(group, tab);
    });
    syncWithHash(group);
  });

  window.addEventListener("hashchange", () => tabGroups.forEach(syncWithHash));
})();
