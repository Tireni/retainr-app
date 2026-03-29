(function () {
  const topbar = document.querySelector(".topbar");
  if (!topbar) return;

  const container = topbar.querySelector(".container");
  const nav = topbar.querySelector(".nav");
  if (!container || !nav) return;

  let overlay = document.querySelector(".nav-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "nav-overlay";
    document.body.appendChild(overlay);
  }

  let toggleBtn = topbar.querySelector(".nav-toggle");
  if (!toggleBtn) {
    toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "nav-toggle";
    toggleBtn.setAttribute("aria-label", "Toggle navigation");
    toggleBtn.setAttribute("aria-expanded", "false");
    toggleBtn.innerHTML = "<span></span><span></span><span></span>";
    container.appendChild(toggleBtn);
  }

  const closeMenu = () => {
    document.body.classList.remove("mobile-nav-open");
    toggleBtn.setAttribute("aria-expanded", "false");
  };

  const openMenu = () => {
    document.body.classList.add("mobile-nav-open");
    toggleBtn.setAttribute("aria-expanded", "true");
  };

  toggleBtn.addEventListener("click", () => {
    if (document.body.classList.contains("mobile-nav-open")) {
      closeMenu();
      return;
    }
    openMenu();
  });

  overlay.addEventListener("click", closeMenu);

  nav.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.closest("a")) {
      closeMenu();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenu();
    }
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 768) {
      closeMenu();
    }
  });

  // Ensure menu never stays open across page restores/back-forward cache.
  closeMenu();
  window.addEventListener("pageshow", closeMenu);
})();
