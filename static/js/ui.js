(() => {
  // 1. Theme persistence (light / dark)
  const root = document.documentElement;
  const savedTheme = localStorage.getItem("invoicelocal_theme");
  if (savedTheme === "dark" || savedTheme === "light") {
    root.setAttribute("data-theme", savedTheme);
  }

  function updateThemeIcon() {
    const btn = document.querySelector("#theme-toggle");
    if (!btn) return;
    const isDark = root.getAttribute("data-theme") === "dark";
    btn.innerHTML = isDark ? '<i data-lucide="sun"></i>' : '<i data-lucide="moon"></i>';
    btn.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
    if (window.lucide) window.lucide.createIcons();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const themeBtn = document.querySelector("#theme-toggle");
    if (themeBtn) {
      updateThemeIcon();
      themeBtn.addEventListener("click", () => {
        const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        localStorage.setItem("invoicelocal_theme", next);
        updateThemeIcon();
      });
    }

    // 2. Render Lucide icons
    if (window.lucide) {
      window.lucide.createIcons();
    }

    // 3. Password visibility toggles
    document.querySelectorAll(".pw-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const input = btn.parentElement.querySelector("input");
        if (!input) return;
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.innerHTML = show ? '<i data-lucide="eye-off"></i>' : '<i data-lucide="eye"></i>';
        if (window.lucide) window.lucide.createIcons();
      });
    });

    // 4. History page live search & status filter
    const searchInput = document.querySelector("#history-search");
    const filterPills = document.querySelectorAll(".filter-pill");
    const historyRows = document.querySelectorAll(".history-table tbody tr");
    if (historyRows.length && (searchInput || filterPills.length)) {
      let activeFilter = "all";
      const applyFilter = () => {
        const q = (searchInput?.value || "").trim().toLowerCase();
        historyRows.forEach((row) => {
          const text = row.textContent.toLowerCase();
          const status = row.dataset.status || "";
          const matchesQuery = !q || text.includes(q);
          const matchesStatus = activeFilter === "all" || status === activeFilter;
          row.style.display = matchesQuery && matchesStatus ? "" : "none";
        });
      };
      searchInput?.addEventListener("input", applyFilter);
      filterPills.forEach((pill) => {
        pill.addEventListener("click", () => {
          filterPills.forEach((p) => p.classList.remove("active"));
          pill.classList.add("active");
          activeFilter = pill.dataset.filter || "all";
          applyFilter();
        });
      });
    }

    // 5. Self-contained Lottie vector animations (no external JSON dependency)
    if (window.lottie) {
      const pulseDocAnimation = {
        v: "5.7.4",
        fr: 30,
        ip: 0,
        op: 90,
        w: 120,
        h: 120,
        nm: "InvoicePulse",
        ddd: 0,
        assets: [],
        layers: [
          {
            ddd: 0,
            ind: 1,
            ty: 4,
            nm: "Ring",
            sr: 1,
            ks: {
              o: { a: 1, k: [{ t: 0, s: [35] }, { t: 45, s: [85] }, { t: 90, s: [35] }] },
              r: { a: 1, k: [{ t: 0, s: [0] }, { t: 90, s: [360] }] },
              p: { a: 0, k: [60, 60, 0] },
              a: { a: 0, k: [0, 0, 0] },
              s: { a: 1, k: [{ t: 0, s: [92, 92, 100] }, { t: 45, s: [104, 104, 100] }, { t: 90, s: [92, 92, 100] }] }
            },
            shapes: [
              {
                ty: "el",
                p: { a: 0, k: [0, 0] },
                s: { a: 0, k: [86, 86] },
                nm: "Circle"
              },
              {
                ty: "st",
                c: { a: 0, k: [0.31, 0.27, 0.9, 1] },
                o: { a: 0, k: 100 },
                w: { a: 0, k: 4 },
                d: [{ n: "d", nm: "dash", v: { a: 0, k: 18 } }, { n: "g", nm: "gap", v: { a: 0, k: 12 } }],
                lc: 2
              }
            ],
            ip: 0,
            op: 90,
            st: 0
          },
          {
            ddd: 0,
            ind: 2,
            ty: 4,
            nm: "Card",
            sr: 1,
            ks: {
              o: { a: 0, k: 100 },
              r: { a: 0, k: 0 },
              p: { a: 1, k: [{ t: 0, s: [60, 62, 0] }, { t: 45, s: [60, 56, 0] }, { t: 90, s: [60, 62, 0] }] },
              a: { a: 0, k: [0, 0, 0] },
              s: { a: 0, k: [100, 100, 100] }
            },
            shapes: [
              {
                ty: "rc",
                p: { a: 0, k: [0, 0] },
                s: { a: 0, k: [40, 48] },
                r: { a: 0, k: 8 }
              },
              {
                ty: "fl",
                c: { a: 0, k: [0.31, 0.27, 0.9, 0.14] },
                o: { a: 0, k: 100 }
              },
              {
                ty: "st",
                c: { a: 0, k: [0.31, 0.27, 0.9, 1] },
                o: { a: 0, k: 100 },
                w: { a: 0, k: 3.5 }
              }
            ],
            ip: 0,
            op: 90,
            st: 0
          },
          {
            ddd: 0,
            ind: 3,
            ty: 4,
            nm: "CheckDot",
            sr: 1,
            ks: {
              o: { a: 0, k: 100 },
              r: { a: 0, k: 0 },
              p: { a: 1, k: [{ t: 0, s: [76, 42, 0] }, { t: 45, s: [76, 36, 0] }, { t: 90, s: [76, 42, 0] }] },
              a: { a: 0, k: [0, 0, 0] },
              s: { a: 1, k: [{ t: 0, s: [85, 85, 100] }, { t: 45, s: [115, 115, 100] }, { t: 90, s: [85, 85, 100] }] }
            },
            shapes: [
              {
                ty: "el",
                p: { a: 0, k: [0, 0] },
                s: { a: 0, k: [16, 16] }
              },
              {
                ty: "fl",
                c: { a: 0, k: [0.06, 0.72, 0.51, 1] },
                o: { a: 0, k: 100 }
              }
            ],
            ip: 0,
            op: 90,
            st: 0
          }
        ]
      };

      document.querySelectorAll("[data-lottie]").forEach((el) => {
        window.lottie.loadAnimation({
          container: el,
          renderer: "svg",
          loop: true,
          autoplay: true,
          animationData: pulseDocAnimation,
        });
      });
    }
  });
})();
