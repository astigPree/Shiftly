(() => {
  const menus = [...document.querySelectorAll('.schedule-row-menu')];
  if (!menus.length) return;

  const close = (menu, restoreFocus = false) => {
    menu.open = false;
    if (restoreFocus) menu.querySelector('summary').focus();
  };

  const position = (menu) => {
    if (!menu.open) return;
    const trigger = menu.querySelector('summary');
    const panel = menu.querySelector('.schedule-row-menu-popover');
    const anchor = trigger.getBoundingClientRect();
    if (anchor.bottom < 0 || anchor.top > innerHeight || anchor.right < 0 || anchor.left > innerWidth) {
      close(menu);
      return;
    }
    const bounds = panel.getBoundingClientRect();
    const left = Math.max(12, Math.min(anchor.right - bounds.width, innerWidth - bounds.width - 12));
    const below = anchor.bottom + 6;
    const top = below + bounds.height <= innerHeight - 12 ? below : Math.max(12, anchor.top - bounds.height - 6);
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
  };

  menus.forEach((menu) => {
    const panel = menu.querySelector('.schedule-row-menu-popover');
    const supportsPopover = typeof panel.showPopover === 'function';
    if (supportsPopover) panel.setAttribute('popover', 'manual');
    panel.classList.add('schedule-row-menu-popover--floating');
    menu.addEventListener('toggle', () => {
      if (menu.open) {
        menus.forEach((other) => { if (other !== menu) close(other); });
        if (supportsPopover && !panel.matches(':popover-open')) panel.showPopover();
        position(menu);
      } else if (supportsPopover && panel.matches(':popover-open')) {
        panel.hidePopover();
      }
    });
    menu.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && menu.open) {
        event.preventDefault();
        close(menu, true);
      }
    });
  });

  document.addEventListener('click', (event) => {
    menus.forEach((menu) => { if (menu.open && !menu.contains(event.target)) close(menu); });
  });
  document.addEventListener('focusin', (event) => {
    menus.forEach((menu) => { if (menu.open && !menu.contains(event.target)) close(menu); });
  });
  window.addEventListener('resize', () => menus.forEach(position));
  document.addEventListener('scroll', () => menus.forEach(position), true);
})();
