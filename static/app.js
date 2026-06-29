/* TimeZone — global front-end behaviour (loaded on every page via layout.html).
   Sections: theme toggle · tabbed panels · bfcache form reset · toasts ·
   sortable tables · Ctrl+Enter submit · inline row editing · prefix combobox. */
    (function () {
      var root = document.documentElement;
      var saved = localStorage.getItem("theme");
      if (saved) root.setAttribute("data-theme", saved);
      var btn = document.getElementById("theme-toggle");
      // the moon/sun icons live in the button; CSS shows the right one per theme
      btn.addEventListener("click", function () {
        var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        localStorage.setItem("theme", next);
      });
    })();

    // Sticky-header behaviour: publish the top bar height (so the sticky tab bar
    // can sit right below it) and mirror the page <h1> into the wide empty left
    // margin (below the logo) once it scrolls out of view.
    (function () {
      var topbar = document.querySelector(".topbar");
      if (!topbar) return;
      function setH() {
        document.documentElement.style.setProperty("--topbar-h", topbar.offsetHeight + "px");
      }
      setH();
      window.addEventListener("resize", setH);

      var h1 = document.querySelector("main.container h1");
      var container = document.querySelector("main.container");
      if (h1 && container) {
        // the title drops diagonally into the empty left margin, centred under
        // the logo and level with the tab-bar row — same on every page
        var mt = document.createElement("div");
        mt.className = "margin-title";
        mt.textContent = h1.textContent.trim();
        mt.setAttribute("aria-hidden", "true");   // decorative; the real <h1> stays for AT
        document.body.appendChild(mt);
        // the title starts at the heading's size and grows toward MAX_FS as it
        // slides into the dock — but the docked size is capped to whatever fits
        // the left-margin column, so long titles shrink to fit instead of vanishing
        var h1FS = parseFloat(getComputedStyle(h1).fontSize) || 24;
        var MAX_FS = 28;
        mt.style.fontSize = MAX_FS + "px";
        var cwMax = mt.offsetWidth, chMax = mt.offsetHeight, curFS = MAX_FS;
        var update = function () {
          var margin = container.getBoundingClientRect().left;
          var maxScroll = Math.max(0,
            (document.scrollingElement || document.documentElement).scrollHeight - window.innerHeight);
          // dock size: grow toward MAX_FS but cap it to fit the left-margin column
          // so even long titles dock (shrunk to fit) instead of being hidden
          var avail = margin - 16;
          var dockFS = Math.min(MAX_FS, MAX_FS * avail / cwMax);
          // genuinely no room (or it'd be unreadably small) -> leave the heading
          if (avail < 40 || dockFS < 12) {
            mt.style.opacity = "0";
            h1.style.opacity = "";
            return;
          }
          if (dockFS !== curFS) { mt.style.fontSize = dockFS + "px"; curFS = dockFS; }
          var cw = cwMax * dockFS / MAX_FS, ch = chMax * dockFS / MAX_FS;
          // the clone *is* the visible heading now — hide the real one (opacity,
          // so it stays in the a11y tree and layout) for a single title on screen
          h1.style.opacity = "0";
          mt.style.opacity = "1";
          // docked resting spot: centred in the left-margin column, tab-bar row
          var restLeft = Math.round((margin - cw) / 2);
          var restTop = Math.round(topbar.offsetHeight + 22 - ch / 2);
          mt.style.left = restLeft + "px";
          mt.style.top = restTop + "px";
          // FLIP: at progress 0 the clone sits exactly on the real heading (same
          // place and size); as the page scrolls it physically slides left + up
          // and shrinks into the dock — the heading itself moving over
          var h1r = h1.getBoundingClientRect();
          // anchor the slide to the heading's FIXED document position (rect.top +
          // scrollY is constant) — not its live on-screen top, which scrolls up
          // and would make the label rise past the dock then drop back (a bounce)
          var h1DocTop = h1r.top + window.scrollY;
          var tx0 = h1r.left - restLeft;
          var ty0 = h1DocTop - restTop;
          // distance over which the title docks: the natural travel (heading
          // scrolling under the top bar) when the page is long enough, but never
          // more than the page can actually scroll. So with little content it
          // docks faster (over the small scroll available); with enough content
          // it moves at the natural pace. No scroll at all -> stays on the heading.
          // The -8 lands it cleanly a hair before the very bottom (sub-pixel max).
          var slideEnd = Math.min(h1DocTop + h1r.height - topbar.offsetHeight, maxScroll - 8);
          var p = slideEnd > 0 ? Math.max(0, Math.min(1, window.scrollY / slideEnd)) : 0;
          // straight slide that grows from the heading's size up to DOCK_FS as
          // it travels (scale 0 at the heading, full size in the dock)
          var scale0 = h1FS / dockFS;
          var s = scale0 + (1 - scale0) * p;
          var tx = tx0 * (1 - p), ty = ty0 * (1 - p);
          mt.style.transform = "translate(" + tx.toFixed(1) + "px," + ty.toFixed(1) + "px) scale(" + s.toFixed(3) + ")";
        };
        window.addEventListener("scroll", update, { passive: true });
        window.addEventListener("resize", update);
        update();
      }
    })();

    // Tabbed sections (Maintain Tasks, Settings, TZ Controls)
    (function () {
      // Stash the currently-active tab so the NEXT load of this SAME page restores
      // it. Used only for in-place reloads (a save / filter that reloads the page) —
      // it is one-shot and path-scoped, mirroring tz_scroll. Navigating away and back
      // never sets it, so a fresh visit (e.g. Home -> Settings) always opens tab one.
      window.__tzStashTab = function () {
        var set = document.querySelector(".tabset");
        if (!set) return;
        var at = set.querySelector(".tab-btn.active");
        if (at) { try { sessionStorage.setItem("tz_tab_once:" + location.pathname, at.dataset.tab); } catch (x) {} }
      };

      document.querySelectorAll(".tabset").forEach(function (set) {
        var btns = set.querySelectorAll(".tab-btn");
        var panels = set.querySelectorAll(".tab-panel");
        function activate(name) {
          btns.forEach(function (b) { b.classList.toggle("active", b.dataset.tab === name); });
          panels.forEach(function (p) { p.classList.toggle("active", p.dataset.tab === name); });
        }
        // A manual switch syncs ?tab (so a plain refresh of THIS url keeps the tab)
        // and starts the new tab at the top. It does NOT push browser history, so Back
        // still steps to the previous *page*. It deliberately does not persist across
        // navigation — leaving the page and returning resets to the first tab.
        btns.forEach(function (b) {
          b.addEventListener("click", function () {
            activate(b.dataset.tab);
            var u = new URL(location.href); u.searchParams.set("tab", b.dataset.tab);
            try { history.replaceState(null, "", u.pathname + u.search + u.hash); } catch (x) {}
            window.scrollTo(0, 0);
          });
        });
        // restore the tab on load: an explicit ?tab wins, else a one-shot stash left
        // by an in-place reload, else the FIRST tab (the default on a fresh visit).
        var names = Array.prototype.map.call(btns, function (b) { return b.dataset.tab; });
        var initial = new URLSearchParams(location.search).get("tab");
        if (names.indexOf(initial) === -1) {
          try {
            var once = sessionStorage.getItem("tz_tab_once:" + location.pathname);
            sessionStorage.removeItem("tz_tab_once:" + location.pathname);
            if (names.indexOf(once) !== -1) initial = once;
          } catch (x) {}
        }
        if (names.indexOf(initial) === -1) initial = names[0];
        if (initial) activate(initial);
      });
    })();

    // If a page is restored from the back/forward cache, re-fetch it so the
    // server-rendered state (client colour, lists, totals, etc.) is never stale
    // on Back. (Belt-and-suspenders alongside the no-store header.)
    window.addEventListener("pageshow", function (e) {
      if (e.persisted) { window.location.reload(); }
    });

    // "App back" links (a[data-back]) behave like the browser's OWN Back button:
    // they unwind to the page you came from WITHOUT pushing a new forward entry, so
    // pressing the browser Back afterwards never replays the in-app detour you just
    // backed out of (e.g. opening Maintain Tasks from a day, adding a task, backing
    // out — browser Back must not drop you back into Maintain Tasks). Falls back to
    // the link's href when there is no in-app history (opened directly / fresh tab).
    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a[data-back]");
      if (!a) return;
      e.preventDefault();
      var href = a.getAttribute("href");
      var fromApp = document.referrer && document.referrer.indexOf(location.origin + "/") === 0;
      if (window.history.length > 1 && fromApp) { window.history.back(); }
      else { window.location.replace(href || location.href); }
    });

    // Filter forms (year / purpose dropdowns) navigate by REPLACING the current
    // history entry instead of pushing a new one — so changing a filter doesn't
    // pile up Back-button steps; Back returns to the page you came from.
    (function () {
      document.querySelectorAll("form[data-filter]").forEach(function (form) {
        form.addEventListener("change", function () {
          var params = new URLSearchParams(new FormData(form)).toString();
          var base = form.getAttribute("action") || location.pathname;
          try { sessionStorage.setItem("tz_scroll", String(window.scrollY)); } catch (x) {}
          if (window.__tzStashTab) window.__tzStashTab();   // keep the open tab across the reload
          window.location.replace(params ? base + "?" + params : base);
        });
      });
    })();

    // Keep the scroll position across a same-page reload triggered by an in-place
    // action or a filter change (stashed just before location.replace). A manual
    // tab switch doesn't stash, so it still starts at the top. (Plain F5 is left to
    // the browser's own scroll restoration.)
    (function () {
      var y = sessionStorage.getItem("tz_scroll");
      if (y === null) return;
      sessionStorage.removeItem("tz_scroll");
      var py = parseInt(y, 10) || 0;
      // after the synchronous init has run (tab restored, layout settled)
      window.requestAnimationFrame(function () { window.scrollTo(0, py); });
    })();

    // Expandable per-purpose category breakdown in the expenses Totals table:
    // clicking a purpose row toggles the category sub-table beneath it.
    (function () {
      document.querySelectorAll("tr.purpose-row").forEach(function (row) {
        var detail = row.nextElementSibling;
        if (!detail || !detail.classList.contains("purpose-detail")) return;
        row.addEventListener("click", function () {
          detail.hidden = !detail.hidden;
          row.classList.toggle("open", !detail.hidden);
        });
      });
    })();

    // ---- flash-toast helpers (shared by page load, in-place reload, soft-swap) ----
    function activateToast(t, i) {
      function dismiss() {
        t.classList.add("toast-out");
        setTimeout(function () { t.remove(); }, 300);
      }
      var close = t.querySelector(".toast-close");
      if (close) close.addEventListener("click", dismiss);
      setTimeout(dismiss, 4000 + (i || 0) * 400);   // stagger multiple toasts
    }
    function showToasts(html) {
      if (!html) return;
      var c = document.getElementById("toasts");
      if (!c) {
        c = document.createElement("div");
        c.className = "toasts"; c.id = "toasts";
        document.body.appendChild(c);
      }
      var tmp = document.createElement("div");
      tmp.innerHTML = html;
      Array.prototype.slice.call(tmp.querySelectorAll(".toast")).forEach(function (t, i) {
        c.appendChild(t); activateToast(t, i);
      });
    }

    // Handle forms that should NOT do a normal navigation: form.inplace (POST
    // actions) and any form with data-soft="<sel[,sel...]>" (e.g. the GET search /
    // page-size filter). Posts/gets via fetch, then either:
    //  - swaps the data-soft region(s) IN PLACE from the fresh HTML (scroll kept,
    //    no reload; for GET the address bar is synced so a refresh restores it), or
    //  - refreshes the whole view with location.replace (adds NO history entry, so
    //    Back never replays the action). The flash toast is shown either way.
    document.addEventListener("submit", function (e) {
      var form = e.target;
      if (!(form instanceof HTMLFormElement)) return;
      var softSel = form.getAttribute("data-soft");
      if (!softSel && !form.classList.contains("inplace")) return;
      if (e.defaultPrevented) return;   // a confirm() onsubmit was cancelled
      e.preventDefault();
      var isGet = (form.method || "get").toLowerCase() === "get";
      var reqUrl, opts;
      if (isGet) {
        var qs = new URLSearchParams(new FormData(form)).toString();
        reqUrl = (form.getAttribute("action") || location.pathname) + (qs ? "?" + qs : "");
        opts = { method: "GET", credentials: "same-origin" };
      } else {
        reqUrl = form.action || location.href;
        opts = { method: "POST", body: new FormData(form), credentials: "same-origin" };
      }
      function go(url) {
        try { sessionStorage.setItem("tz_scroll", String(window.scrollY)); } catch (x) {}
        if (window.__tzStashTab) window.__tzStashTab();   // keep the open tab across the reload
        window.location.replace(url || location.href);
      }
      fetch(reqUrl, opts).then(function (resp) {
        var url = resp.url;
        return resp.text().then(function (html) {
          var doc = new DOMParser().parseFromString(html, "text/html");
          var toastsEl = doc.getElementById("toasts");
          var toastsHTML = toastsEl ? toastsEl.innerHTML : "";
          if (softSel) {
            var sels = softSel.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
            var pairs = sels.map(function (s) { return [doc.querySelector(s), document.querySelector(s)]; });
            if (pairs.every(function (p) { return p[0] && p[1]; })) {
              pairs.forEach(function (p) {
                p[1].innerHTML = p[0].innerHTML;             // swap in place — scroll kept
                if (window.__tzSetupSortable) window.__tzSetupSortable(p[1]);
              });
              try { history.replaceState(null, "", isGet ? reqUrl : url); } catch (x) {}
              showToasts(toastsHTML);
              return;
            }
          }
          // carry the flash across the full reload (the followed GET consumed it)
          if (toastsHTML) sessionStorage.setItem("tz_pending_toasts", toastsHTML);
          go(url);
        });
      }).catch(function () { go(); });
    });

    // The Completed-tasks search + page-size submit their (GET, data-soft) form so
    // the list below swaps in place. Delegated so it survives the soft-swaps.
    (function () {
      var timer;
      document.addEventListener("input", function (e) {
        if (!e.target.matches(".completed-filter input[name='completed_q']")) return;
        var form = e.target.form;
        clearTimeout(timer);
        timer = setTimeout(function () { if (form) form.requestSubmit(); }, 300);
      });
      document.addEventListener("change", function (e) {
        if (e.target.matches(".completed-filter select[name='completed_limit']")) {
          if (e.target.form) e.target.form.requestSubmit();
        }
      });
    })();

    // Auto-dismiss server-rendered toasts, then re-show any flash captured from an
    // in-place POST (stashed before the reload). Both go through the shared helpers.
    Array.prototype.slice.call(document.querySelectorAll("#toasts .toast"))
      .forEach(function (t, i) { activateToast(t, i); });
    (function () {
      var pending = sessionStorage.getItem("tz_pending_toasts");
      if (!pending) return;
      sessionStorage.removeItem("tz_pending_toasts");
      showToasts(pending);
    })();

    // Inline per-row editing for master tables (tasks / sub tasks / charge types)
    (function () {
      function setEditing(tr, on) {
        tr.classList.toggle("editing", on);
        tr.querySelectorAll(".edit-input").forEach(function (inp) { inp.disabled = !on; });
        if (on) {
          var first = tr.querySelector(".edit-input");
          if (first) first.focus();
        }
      }
      document.addEventListener("click", function (e) {
        var edit = e.target.closest(".row-edit");
        if (edit) { setEditing(edit.closest("tr"), true); return; }
        var cancel = e.target.closest(".row-cancel");
        if (cancel) { setEditing(cancel.closest("tr"), false); }
      });
    })();

    // Click-to-sort on table headers (all .grid tables except .no-sort).
    (function () {
      function cellVal(row, idx) {
        var c = row.cells[idx];
        return c ? (c.innerText || c.textContent || "").trim() : "";
      }
      function asNum(v) { return parseFloat(v.replace(/[$,%₹\s]/g, "")); }
      function sortBy(table, idx, th) {
        var tb = table.tBodies[0];
        if (!tb) return;
        var rows = Array.prototype.slice.call(tb.rows);
        // keep total rows and empty-state (colspan) rows pinned at the bottom
        var pinned = rows.filter(function (r) {
          return r.classList.contains("total-row") || r.querySelector("td[colspan]");
        });
        var sortable = rows.filter(function (r) { return pinned.indexOf(r) === -1; });
        var dir = th.getAttribute("data-sort") === "asc" ? "desc" : "asc";
        Array.prototype.forEach.call(table.tHead.rows[0].cells, function (h) {
          if (h !== th) { h.removeAttribute("data-sort"); h.classList.remove("sorted-asc", "sorted-desc"); }
        });
        th.setAttribute("data-sort", dir);
        th.classList.remove("sorted-asc", "sorted-desc");
        th.classList.add(dir === "asc" ? "sorted-asc" : "sorted-desc");
        var mult = dir === "asc" ? 1 : -1;
        sortable.sort(function (a, b) {
          var x = cellVal(a, idx), y = cellVal(b, idx);
          var nx = asNum(x), ny = asNum(y);
          if (!isNaN(nx) && !isNaN(ny)) return (nx - ny) * mult;
          return x.localeCompare(y, undefined, { numeric: true }) * mult;
        });
        sortable.forEach(function (r) { tb.appendChild(r); });
        pinned.forEach(function (r) { tb.appendChild(r); });
      }
      function setupSortable(root) {
        (root || document).querySelectorAll("table.grid:not(.no-sort)").forEach(function (table) {
          if (table._sortInit || !table.tHead || !table.tHead.rows.length) return;
          table._sortInit = true;
          Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, idx) {
            if (th.classList.contains("actions-col")) return;
            if (!th.textContent.trim()) return;
            th.classList.add("sortable-th");
            th.addEventListener("click", function () { sortBy(table, idx, th); });
          });
        });
      }
      setupSortable(document);
      // let the in-place soft-swap re-init sorting on freshly injected tables
      window.__tzSetupSortable = setupSortable;
    })();

    // Ctrl+Enter submits forms marked .ctrl-enter (e.g. the day Add Hours form).
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        var form = e.target.closest && e.target.closest("form.ctrl-enter");
        if (form) { e.preventDefault(); form.requestSubmit(); }
      }
    });

    // Prefix-filtered combobox for inputs.combo (begins-with, not contains).
    (function () {
      document.querySelectorAll("input.combo").forEach(function (input) {
        var dl = document.getElementById(input.getAttribute("data-list"));
        var options = Array.prototype.map.call(dl ? dl.options : [], function (o) {
          return { value: o.value, label: (o.textContent || "").trim() || o.value };
        });
        var wrap = input.parentNode;
        wrap.classList.add("combo-wrap");
        var menu = document.createElement("div");
        menu.className = "combo-menu";
        menu.style.display = "none";
        wrap.appendChild(menu);
        var current = [], active = -1, excluded = [];
        // when set, a purely-numeric query does a contains (wildcard) search
        var numericContains = input.hasAttribute("data-numeric-contains");
        // when set, Up/Down arrows step the (number) value instead of navigating the menu
        var arrowStep = input.hasAttribute("data-arrow-step");
        // allow callers (e.g. the day page) to hide certain option values
        input.setComboExclude = function (list) {
          excluded = (list || []).map(function (s) { return (s || "").toString().trim().toLowerCase(); });
        };

        function hide() { menu.style.display = "none"; active = -1; }
        function render(list) {
          current = list; active = -1; menu.innerHTML = "";
          if (!list.length) { hide(); return; }
          list.forEach(function (opt) {
            var d = document.createElement("div");
            d.className = "combo-item";
            d.textContent = opt.label;
            d.addEventListener("mousedown", function (ev) {
              ev.preventDefault();
              input.value = opt.value; hide();
              input.dispatchEvent(new Event("change", { bubbles: true }));
            });
            menu.appendChild(d);
          });
          menu.style.display = "block";
          setActive(0);  // auto-highlight the first match as you type
        }
        function accept() {
          if (menu.style.display !== "none" && active >= 0 && current[active]) {
            input.value = current[active].value;
            hide();
            input.dispatchEvent(new Event("change", { bubbles: true }));
            return true;
          }
          return false;
        }
        function filter() {
          var q = input.value.trim().toLowerCase();
          var contains = numericContains && /^[0-9]+$/.test(q);  // numeric query -> wildcard
          render(options.filter(function (o) {
            if (excluded.indexOf(o.value.toLowerCase()) !== -1) return false;
            var v = o.value.toLowerCase(), l = o.label.toLowerCase();
            if (contains) return v.indexOf(q) !== -1 || l.indexOf(q) !== -1;
            return v.indexOf(q) === 0 || l.indexOf(q) === 0;
          }));
        }
        function setActive(i) {
          var items = menu.querySelectorAll(".combo-item");
          if (!items.length) return;
          active = (i + items.length) % items.length;
          items.forEach(function (el, idx) { el.classList.toggle("active", idx === active); });
          items[active].scrollIntoView({ block: "nearest" });
        }

        input.addEventListener("focus", filter);
        input.addEventListener("input", filter);
        input.addEventListener("blur", function () { setTimeout(hide, 150); });
        input.addEventListener("keydown", function (e) {
          if (arrowStep && (e.key === "ArrowDown" || e.key === "ArrowUp")) { hide(); return; }
          if (e.key === "ArrowDown") { e.preventDefault(); if (menu.style.display === "none") filter(); else setActive(active + 1); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
          else if (e.key === "Escape") { hide(); }
          else if (e.key === "Tab") {
            // load the highlighted row into the field, then let Tab move focus
            accept();
          }
          else if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
            // never submit on plain Enter; pick highlighted option if any
            e.preventDefault();
            accept();
          }
        });
      });
    })();

    // Top-bar clock menu: Switch Client / TZ Controls dropdown.
    (function () {
      var menu = document.getElementById("tz-menu");
      if (!menu) return;
      var btn = document.getElementById("tz-menu-btn");
      var dd = document.getElementById("tz-dropdown");
      function open() { dd.hidden = false; btn.setAttribute("aria-expanded", "true"); }
      function close() { dd.hidden = true; btn.setAttribute("aria-expanded", "false"); }
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        if (dd.hidden) { open(); var f = dd.querySelector(".add-client input"); } else { close(); }
      });
      // keep clicks inside the dropdown from closing it (except submits, which navigate)
      dd.addEventListener("click", function (e) { e.stopPropagation(); });
      document.addEventListener("click", function () { if (!dd.hidden) close(); });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && !dd.hidden) { close(); btn.focus(); }
      });
    })();

    // Home only: the client-name heading is a dropdown of active clients. Picking
    // one persists the switch and reloads straight away so the new client's data
    // loads immediately; the wave + recolour then plays on the FRESH page (see the
    // entrance block below), so the animation and the data arrive together rather
    // than animating first and loading late.
    (function () {
      var btn = document.getElementById("client-switcher-btn");
      var menu = document.getElementById("client-switch-menu");
      if (!btn || !menu) return;
      var currentId = parseInt(btn.getAttribute("data-current-id"), 10);

      function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); }
      function open() {
        // the current client is hidden via .current; show the empty note if none left
        var empty = menu.querySelector(".csm-empty");
        if (empty) empty.hidden = menu.querySelectorAll(".csm-item:not(.current)").length > 0;
        menu.hidden = false; btn.setAttribute("aria-expanded", "true");
      }
      btn.addEventListener("click", function (e) { e.stopPropagation(); menu.hidden ? open() : close(); });
      menu.addEventListener("click", function (e) { e.stopPropagation(); });
      document.addEventListener("click", function () { if (!menu.hidden) close(); });
      document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !menu.hidden) close(); });

      // Play the entrance once, on the freshly loaded page after a switch: a wave
      // RING sweeps out from the switcher in the NEW client's colour while the page
      // colours ease from the previous client's hue (set pre-paint in layout.html)
      // to the new one — so there is never a flash and the data is already here.
      (function entrance() {
        var en = window.__tzEntrance;
        if (!en || !en.toHue) return;
        window.__tzEntrance = null;
        var b = document.body;
        var rect = btn.getBoundingClientRect();
        var cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
        var vw = window.innerWidth, vh = window.innerHeight;
        var far = Math.max(Math.hypot(cx, cy), Math.hypot(vw - cx, cy),
                           Math.hypot(cx, vh - cy), Math.hypot(vw - cx, vh - cy));
        var d = Math.ceil(far * 2) + 40;
        var wave = document.createElement("div");
        wave.className = "client-wave";
        var grad = "radial-gradient(circle," +
          "hsl(" + en.toHue + " 78% 55% / .10) 0%," +
          "hsl(" + en.toHue + " 78% 55% / .45) 55%," +
          "hsl(" + en.toHue + " 78% 58% / 1) 85%," +
          "hsl(" + en.toHue + " 78% 58% / 0) 100%)";
        wave.style.cssText = "left:" + cx + "px;top:" + cy + "px;width:" + d + "px;height:" + d +
                             "px;background:" + grad + ";";
        b.appendChild(wave);
        b.classList.add("recoloring");
        // commit the start states (wave at scale 0, old colour) before changing
        // them, so the CSS transitions animate (sync reflow, not rAF)
        void b.offsetWidth;
        wave.classList.add("go");                          // ring sweeps out
        b.style.setProperty("--client-hue", en.toHue);     // colours ease to the new client
        if (en.toLight) b.style.setProperty("--ct-light", en.toLight);
        if (en.toDark) b.style.setProperty("--ct-dark", en.toDark);
        setTimeout(function () { wave.remove(); b.classList.remove("recoloring"); }, 1300);
      })();

      menu.querySelectorAll(".csm-item").forEach(function (item) {
        item.addEventListener("click", function () {
          var id = parseInt(item.getAttribute("data-id"), 10);
          close();
          if (id === currentId) return;
          // remember the current client's colour so the fresh page can start there
          // and ease to the new one (the wave plays on arrival, not before)
          var b = document.body;
          try {
            sessionStorage.setItem("tz_switch_entrance", JSON.stringify({
              fromHue: b.style.getPropertyValue("--client-hue").trim(),
              fromLight: b.style.getPropertyValue("--ct-light").trim(),
              fromDark: b.style.getPropertyValue("--ct-dark").trim()
            }));
          } catch (_) {}
          // persist the switch, then reload immediately — the data loads right away
          var fd = new FormData(); fd.set("client_id", id);
          fetch("/clients/switch", {
            method: "POST", body: fd, headers: { "X-Requested-With": "fetch" }
          }).catch(function () {}).then(function () { window.location.reload(); });
        });
      });
    })();
