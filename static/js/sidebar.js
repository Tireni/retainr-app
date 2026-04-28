(function () {
  const toggle = document.querySelector('[data-sidebar-toggle]');
  const backdrop = document.querySelector('[data-sidebar-backdrop]');
  const sidebar = document.querySelector('.app-sidebar');
  if (!toggle || !sidebar) return;

  const setToggleLabel = (isOpen) => {
    toggle.textContent = isOpen ? '✕ Close' : '☰ Menu';
    toggle.setAttribute('aria-label', isOpen ? 'Close menu' : 'Open menu');
  };

  const close = () => {
    document.body.classList.remove('sidebar-open');
    setToggleLabel(false);
  };

  const open = () => {
    document.body.classList.add('sidebar-open');
    setToggleLabel(true);
  };

  toggle.addEventListener('click', () => {
    if (document.body.classList.contains('sidebar-open')) {
      close();
      return;
    }
    open();
  });

  if (backdrop) {
    backdrop.addEventListener('click', close);
  }

  sidebar.addEventListener('click', (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.closest('a')) {
      close();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      close();
    }
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 1024) {
      close();
    }
  });

  setToggleLabel(false);
})();
