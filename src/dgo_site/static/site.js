/* dgo-site behaviour.
 *
 * Everything here is an enhancement. With JavaScript off the site still works:
 * every term is listed on the glossary page, every row is a real link, and the
 * theme falls back to the reader's OS preference. Only search and the filter
 * pills stop working, and both say so.
 *
 * No build step, no dependencies -- the site has to open straight out of a
 * downloaded PR-preview artifact over file://.
 */
(function () {
  "use strict";

  var BASE = window.DGO_SITE_BASE || "";
  var TEXT = window.DGO_SITE_TEXT || {};

  /* Wording from the site's text catalog (text.yaml, overridable in
     dgo-site.yaml), with {placeholders} filled in. */
  function T(key, fields) {
    var s = TEXT[key] || "";
    return s.replace(/\{(\w+)\}/g, function (all, name) {
      return fields && name in fields ? fields[name] : all;
    });
  }
  var THEME_KEY = "dgo-site-theme";

  /* ---------- Theme ---------- */

  function currentTheme() {
    var explicit = document.documentElement.getAttribute("data-theme");
    if (explicit) return explicit;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function paintToggle() {
    var label = document.querySelector("[data-theme-label]");
    if (!label) return;
    label.textContent = currentTheme() === "dark" ? T("theme_light") : T("theme_dark");
  }

  var toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch (e) {
        /* Private browsing, or site data blocked. The theme still applies for
           this page view; it just will not be remembered. */
      }
      paintToggle();
    });
    paintToggle();
  }

  /* ---------- Search index ---------- */

  var index = null;
  var indexPromise = null;

  function loadIndex() {
    if (indexPromise) return indexPromise;
    /* A script tag rather than fetch(): fetch is refused over file://, and the
       site has to work opened straight out of a downloaded artifact. */
    indexPromise = new Promise(function (resolve, reject) {
      if (window.DGO_SITE_INDEX) return resolve(window.DGO_SITE_INDEX);
      var tag = document.createElement("script");
      tag.src = BASE + "assets/search-index.js";
      tag.onload = function () {
        window.DGO_SITE_INDEX ? resolve(window.DGO_SITE_INDEX) : reject(new Error("empty index"));
      };
      tag.onerror = function () {
        reject(new Error("search index unavailable"));
      };
      document.head.appendChild(tag);
    })
      .then(function (data) {
        index = data.map(function (entry) {
          return Object.assign({}, entry, { haystack: (entry.text || "").toLowerCase() });
        });
        return index;
      })
      .catch(function () {
        index = [];
        return index;
      });
    return indexPromise;
  }

  function score(entry, needle) {
    var title = entry.title.toLowerCase();
    if (title === needle) return 0;
    if (title.indexOf(needle) === 0) return 1;
    var alts = (entry.alt || []).map(function (a) {
      return a.toLowerCase();
    });
    for (var i = 0; i < alts.length; i++) {
      if (alts[i].indexOf(needle) === 0) return 2;
    }
    if (title.indexOf(needle) > -1) return 3;
    if (entry.haystack.indexOf(needle) > -1) return 4;
    return -1;
  }

  function search(query, kind) {
    var needle = query.trim().toLowerCase();
    if (!needle || !index) return [];
    var hits = [];
    for (var i = 0; i < index.length; i++) {
      var entry = index[i];
      if (kind && kind !== "all" && entry.kind !== kind) continue;
      var s = score(entry, needle);
      if (s > -1) hits.push({ entry: entry, score: s });
    }
    hits.sort(function (a, b) {
      return a.score - b.score || a.entry.title.localeCompare(b.entry.title);
    });
    return hits.map(function (h) {
      return h.entry;
    });
  }

  /* ---------- Header type-ahead ---------- */

  var input = document.getElementById("site-search");
  var results = document.getElementById("search-results");

  function closeResults() {
    if (!results) return;
    results.innerHTML = "";
    if (input) input.setAttribute("aria-expanded", "false");
  }

  function renderDropdown(hits, query) {
    if (!results) return;
    if (!query.trim()) {
      closeResults();
      return;
    }
    if (!hits.length) {
      results.innerHTML = '<div class="search__empty">' + escapeHtml(T("search_empty", { query: query })) + "</div>";
      input.setAttribute("aria-expanded", "true");
      return;
    }
    var html = hits.slice(0, 8).map(function (entry) {
      return (
        '<a class="search__hit" role="option" href="' + BASE + entry.url + '">' +
        '<div class="search__hit-title">' + escapeHtml(entry.title) + "</div>" +
        '<div class="search__hit-meta">' + escapeHtml(entry.meta || "") + "</div>" +
        "</a>"
      );
    });
    results.innerHTML = html.join("");
    input.setAttribute("aria-expanded", "true");
  }

  if (input) {
    input.addEventListener("focus", loadIndex);
    input.addEventListener("input", function () {
      var query = input.value;
      loadIndex().then(function () {
        renderDropdown(search(query, "all"), query);
      });
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        input.value = "";
        closeResults();
        input.blur();
        return;
      }
      if (event.key === "Enter") {
        var first = results && results.querySelector(".search__hit");
        if (first) {
          event.preventDefault();
          window.location.href = first.getAttribute("href");
        }
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        var hits = results ? Array.prototype.slice.call(results.querySelectorAll(".search__hit")) : [];
        if (!hits.length) return;
        event.preventDefault();
        var current = hits.findIndex(function (h) {
          return h.getAttribute("aria-selected") === "true";
        });
        hits.forEach(function (h) {
          h.removeAttribute("aria-selected");
        });
        var next = event.key === "ArrowDown" ? current + 1 : current - 1;
        if (next < 0) next = hits.length - 1;
        if (next >= hits.length) next = 0;
        hits[next].setAttribute("aria-selected", "true");
        hits[next].scrollIntoView({ block: "nearest" });
      }
    });

    document.addEventListener("click", function (event) {
      if (results && !results.contains(event.target) && event.target !== input) closeResults();
    });

    document.addEventListener("keydown", function (event) {
      var tag = (event.target.tagName || "").toLowerCase();
      if (event.key === "/" && tag !== "input" && tag !== "textarea" && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        input.focus();
        input.select();
      }
    });
  }

  /* ---------- Glossary filter pills + pagination ---------- */

  var filterBarEl = document.querySelector("[data-filter-bar]");
  if (filterBarEl) {
    /* How many terms show at once. The dictionary is expected to reach the
       hundreds; a window keeps the page short to scan and quick to paint
       without dropping any term from the document. The reader picks the size;
       these are the offered values, smallest first. */
    var PAGE_SIZES = [10, 25, 50, 100];
    var DEFAULT_PAGE_SIZE = 25;
    var SIZE_KEY = "dgo-site-page-size";

    var rows = Array.prototype.slice.call(document.querySelectorAll(".term-row[data-domain]"));
    var countEl = document.querySelector("[data-term-count]");
    var emptyEl = document.querySelector("[data-empty]");
    var table = document.querySelector(".term-table");
    var pager = document.querySelector("[data-pager]");
    var pagerNav = pager && pager.querySelector("[data-pager-nav]");
    var pagerPrev = pager && pager.querySelector("[data-pager-prev]");
    var pagerNext = pager && pager.querySelector("[data-pager-next]");
    var pagerStatus = pager && pager.querySelector("[data-pager-status]");
    var sizeSelect = pager && pager.querySelector("[data-page-size]");

    var activeFilter = "all";
    var page = 1;
    var pageSize = DEFAULT_PAGE_SIZE;

    /* Restore the reader's saved page size, the way the theme is restored. A
       stale or tampered value that is not one of the offered sizes is ignored. */
    try {
      var saved = parseInt(localStorage.getItem(SIZE_KEY), 10);
      if (PAGE_SIZES.indexOf(saved) > -1) pageSize = saved;
    } catch (e) {
      /* Private browsing, or site data blocked -- fall back to the default. */
    }
    if (sizeSelect) sizeSelect.value = String(pageSize);

    function keeps(row) {
      if (activeFilter === "all") return true;
      if (activeFilter === "attention") return row.hasAttribute("data-attention");
      return "domain:" + row.getAttribute("data-domain") === activeFilter;
    }

    function render() {
      var matched = rows.filter(keeps);
      var total = matched.length;
      var pageCount = Math.max(1, Math.ceil(total / pageSize));
      if (page > pageCount) page = pageCount;
      if (page < 1) page = 1;
      var start = (page - 1) * pageSize;
      var end = Math.min(start + pageSize, total);

      /* Hide everything, then reveal only the current page's slice. Rows that
         fail the filter stay hidden regardless of page. */
      rows.forEach(function (row) {
        row.hidden = true;
      });
      matched.slice(start, end).forEach(function (row) {
        row.hidden = false;
      });

      if (emptyEl) emptyEl.hidden = total !== 0;

      if (countEl) {
        if (total === 0) {
          countEl.textContent = T("count_none");
        } else if (total <= pageSize) {
          countEl.textContent = T(total === 1 ? "count_one" : "count_other", { n: total });
        } else {
          countEl.textContent = T("count_range", { start: start + 1, end: end, total: total });
        }
      }

      if (pager) {
        /* Offer the whole control once choosing a smaller size could split the
           list; below the smallest size every choice shows everything, so it
           has nothing to do. The prev/next nav appears only with real pages. */
        pager.hidden = total <= PAGE_SIZES[0];
        if (pagerNav) pagerNav.hidden = pageCount <= 1;
        if (pagerStatus) pagerStatus.textContent = T("page_status", { page: page, pages: pageCount });
        if (pagerPrev) pagerPrev.disabled = page <= 1;
        if (pagerNext) pagerNext.disabled = page >= pageCount;
      }
    }

    function goTo(next) {
      page = next;
      render();
      /* Bring the top of the list back into view so the reader is not left
         mid-page after the rows swap out. */
      if (table && table.scrollIntoView) {
        table.scrollIntoView({ block: "start", behavior: "smooth" });
      }
    }

    filterBarEl.addEventListener("click", function (event) {
      var button = event.target.closest("[data-filter]");
      if (!button) return;
      activeFilter = button.getAttribute("data-filter");
      page = 1;
      filterBarEl.querySelectorAll("[data-filter]").forEach(function (b) {
        b.setAttribute("aria-pressed", String(b === button));
      });
      render();
    });

    if (pagerPrev) {
      pagerPrev.addEventListener("click", function () {
        if (page > 1) goTo(page - 1);
      });
    }
    if (pagerNext) {
      pagerNext.addEventListener("click", function () {
        goTo(page + 1);
      });
    }

    if (sizeSelect) {
      sizeSelect.addEventListener("change", function () {
        var chosen = parseInt(sizeSelect.value, 10);
        if (PAGE_SIZES.indexOf(chosen) === -1) return;
        pageSize = chosen;
        page = 1;
        try {
          localStorage.setItem(SIZE_KEY, String(chosen));
        } catch (e) {
          /* Preference just will not carry to the next visit. */
        }
        render();
      });
    }

    render();
  }

  /* ---------- Copy to clipboard ---------- */

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    /* file:// and plain http are not secure contexts, and a steward opening
       the PR-preview artifact out of a downloaded zip is on file://. */
    return new Promise(function (resolve, reject) {
      var scratch = document.createElement("textarea");
      scratch.value = text;
      scratch.setAttribute("readonly", "");
      scratch.style.cssText = "position:fixed;top:-1000px;opacity:0";
      document.body.appendChild(scratch);
      scratch.select();
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      }
      document.body.removeChild(scratch);
      ok ? resolve() : reject(new Error("copy failed"));
    });
  }

  document.querySelectorAll("[data-copy-target]").forEach(function (button) {
    var source = document.getElementById(button.getAttribute("data-copy-target"));
    if (!source) return;

    var resetTimer = null;
    button.addEventListener("click", function () {
      copyText(source.textContent.trim()).then(
        function () {
          button.textContent = T("copied");
          button.setAttribute("data-copied", "");
        },
        function () {
          /* Say so rather than silently doing nothing; the value is on screen
             and can still be selected by hand. */
          button.textContent = T("copy_fallback");
          var range = document.createRange();
          range.selectNodeContents(source);
          var selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        }
      );
      clearTimeout(resetTimer);
      resetTimer = setTimeout(function () {
        button.textContent = button.getAttribute("data-copy-label");
        button.removeAttribute("data-copied");
      }, 2000);
    });
  });

  /* ---------- On-this-page rail ---------- */

  var railLinks = Array.prototype.slice.call(document.querySelectorAll(".toc-rail a[href^='#']"));
  if (railLinks.length && "IntersectionObserver" in window) {
    var targets = railLinks
      .map(function (link) {
        return document.getElementById(link.getAttribute("href").slice(1));
      })
      .filter(Boolean);

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          railLinks.forEach(function (link) {
            link.classList.toggle(
              "is-active",
              link.getAttribute("href") === "#" + entry.target.id
            );
          });
        });
      },
      { rootMargin: "-110px 0px -70% 0px" }
    );
    targets.forEach(function (t) {
      observer.observe(t);
    });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }
})();
