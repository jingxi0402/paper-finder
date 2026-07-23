/* Journal Brief — client. No dependencies, no build step. */

(function () {
  "use strict";

  var COLORS = {
    blue: "var(--blue)", teal: "var(--teal)",
    orange: "var(--orange)", purple: "var(--purple)", none: "var(--none)"
  };
  var TIER_RANK = { "1区Top": 4, "1区": 3, "2区": 2, "3区": 1, "4区": 0 };
  var TRACE_DAYS = 45;
  var VISIT_KEY = "jb.lastVisit";

  var DB = { items: [], runs: [], topic_colors: {}, generated: "" };
  var lastVisit = null;
  var active = { q: "", tier: "", kind: "", min: 0, topics: {} };

  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };

  /* ---------- topic colour ---------- */

  function topicColor(name) {
    return COLORS[DB.topic_colors[name]] || COLORS.none;
  }

  function itemColor(it) {
    // The highest-scoring topic drives the accent; ties fall to the first.
    return it.topics && it.topics.length ? topicColor(it.topics[0]) : COLORS.none;
  }

  /* ---------- filtering ---------- */

  function anyTopicOn() {
    for (var k in active.topics) { if (active.topics[k]) return true; }
    return false;
  }

  function matches(it) {
    if (active.min && (it.score || 0) < active.min) return false;

    if (active.kind === "preprint" && !it.preprint) return false;
    if (active.kind === "journal" && it.preprint) return false;

    if (active.tier) {
      if (it.preprint) return false;
      var want = TIER_RANK[active.tier] || 0;
      if ((TIER_RANK[it.tier] || 0) < want) return false;
    }

    if (anyTopicOn()) {
      var hit = false;
      for (var i = 0; i < (it.topics || []).length; i++) {
        if (active.topics[it.topics[i]]) { hit = true; break; }
      }
      if (!hit) return false;
    }

    if (active.q) {
      var hay = (it.title + " " + it.abstract + " " + it.journal + " " +
        (it.authors || []).join(" ") + " " + (it.terms || []).join(" ")).toLowerCase();
      var words = active.q.toLowerCase().split(/\s+/).filter(Boolean);
      for (var j = 0; j < words.length; j++) {
        if (hay.indexOf(words[j]) === -1) return false;
      }
    }
    return true;
  }

  /* ---------- signal trace ---------- */

  function drawTrace(items) {
    var svg = $("trace-svg");
    var W = 900, H = 96, pad = 2;
    var days = [], byDay = {};
    var d = new Date();

    for (var i = TRACE_DAYS - 1; i >= 0; i--) {
      var t = new Date(d.getTime() - i * 86400000);
      var key = t.toISOString().slice(0, 10);
      days.push(key);
      byDay[key] = [];
    }
    items.forEach(function (it) {
      if (byDay[it.added]) byDay[it.added].push(it);
    });

    var max = 1;
    days.forEach(function (k) {
      var sum = byDay[k].reduce(function (a, b) { return a + (b.score || 0); }, 0);
      if (sum > max) max = sum;
    });

    var colW = W / TRACE_DAYS;
    var out = ['<line class="baseline" x1="0" y1="' + (H - 0.5) +
               '" x2="' + W + '" y2="' + (H - 0.5) + '"/>'];

    days.forEach(function (key, idx) {
      var list = byDay[key].slice().sort(function (a, b) {
        return (b.score || 0) - (a.score || 0);
      });
      if (!list.length) return;

      var x = idx * colW + pad / 2;
      var w = colW - pad;
      var y = H;
      var seg = ['<g class="col" tabindex="0" role="button" data-day="' + key +
                 '" aria-label="' + key + ", " + list.length + ' papers">'];

      list.forEach(function (it) {
        var h = ((it.score || 0) / max) * (H - 6);
        if (h < 1.2) h = 1.2;
        y -= h;
        seg.push('<rect x="' + x.toFixed(2) + '" y="' + y.toFixed(2) +
                 '" width="' + w.toFixed(2) + '" height="' + h.toFixed(2) +
                 '" fill="' + itemColor(it) + '"/>');
      });

      seg.push('<title>' + key + " · " + list.length + " paper" +
               (list.length === 1 ? "" : "s") + "</title></g>");
      out.push(seg.join(""));
    });

    // today marker
    out.push('<line class="today" x1="' + (W - 0.5) + '" y1="0" x2="' +
             (W - 0.5) + '" y2="' + H + '"/>');

    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.innerHTML = out.join("");
    $("trace-from").textContent = days[0];
    $("trace-to").textContent = days[days.length - 1];

    Array.prototype.forEach.call(svg.querySelectorAll(".col"), function (g) {
      var jump = function () {
        var el = document.querySelector('[data-daygroup="' + g.dataset.day + '"]');
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      };
      g.addEventListener("click", jump);
      g.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); jump(); }
      });
    });
  }

  /* ---------- chips ---------- */

  function buildChips() {
    var counts = {};
    DB.items.forEach(function (it) {
      (it.topics || []).forEach(function (t) { counts[t] = (counts[t] || 0) + 1; });
    });

    var names = Object.keys(DB.topic_colors);
    Object.keys(counts).forEach(function (n) {
      if (names.indexOf(n) === -1) names.push(n);
    });

    $("topics").innerHTML = names.map(function (n) {
      return '<button class="chip" type="button" aria-pressed="false" ' +
        'data-topic="' + esc(n) + '" style="--chip:' + topicColor(n) + '">' +
        esc(n) + ' <span class="chip-count">' + (counts[n] || 0) + "</span></button>";
    }).join("");

    Array.prototype.forEach.call($("topics").querySelectorAll(".chip"), function (b) {
      b.addEventListener("click", function () {
        var t = b.dataset.topic;
        active.topics[t] = !active.topics[t];
        b.setAttribute("aria-pressed", active.topics[t] ? "true" : "false");
        apply();
      });
    });
  }

  /* ---------- item rendering ---------- */

  function itemHTML(it) {
    var accent = itemColor(it);
    var isNew = lastVisit && it.added > lastVisit;

    var tags = "";
    if (isNew) tags += '<span class="tag new">NEW</span>';
    if (it.preprint) tags += '<span class="tag pre">PREPRINT</span>';

    var bits = ['<span class="journal">' + esc(it.journal) + "</span>"];
    if (it.tier) bits.push(esc(it.tier));
    if (it.if) bits.push("IF " + it.if);
    if (it.date) bits.push(esc(it.date));

    var links = [];
    if (it.doi) links.push('<a href="https://doi.org/' + esc(it.doi) + '" target="_blank" rel="noopener">DOI</a>');
    if (it.pmid) links.push('<a href="https://pubmed.ncbi.nlm.nih.gov/' + esc(it.pmid) + '/" target="_blank" rel="noopener">PubMed</a>');
    links.push('<a href="https://scholar.google.com/scholar?q=' +
      encodeURIComponent(it.title.slice(0, 200)) + '" target="_blank" rel="noopener">Scholar</a>');

    return '<article class="item" style="--accent:' + accent + '">' +
      '<div class="score">' + (it.score != null ? it.score.toFixed(1) : "—") +
        "<small>score</small></div>" +
      '<div class="body">' +
        '<h3 class="title"><a href="' + esc(it.url) + '" target="_blank" rel="noopener">' +
          esc(it.title) + "</a></h3>" +
        '<div class="meta">' + tags + bits.join(' <span class="sep">/</span> ') + "</div>" +
        (it.authors && it.authors.length
          ? '<div class="authors">' + esc(it.authors.slice(0, 3).join(", ")) +
            (it.authors.length > 3 ? " et al." : "") + "</div>" : "") +
        (it.abstract ? '<p class="abstract">' + esc(it.abstract) + "</p>" : "") +
        (it.terms && it.terms.length
          ? '<div class="terms">◆ ' + esc(it.terms.join(", ")) + "</div>" : "") +
        '<div class="links">' + links.join("") + "</div>" +
      "</div></article>";
  }

  function apply() {
    var shown = DB.items.filter(matches);
    var results = $("results");

    if (!DB.items.length) {
      results.innerHTML = '<p class="empty"><b>Nothing collected yet.</b><br>' +
        "The first run happens on the next weekday morning. " +
        "To fill it now, trigger the workflow manually with a 7-day lookback.</p>";
      drawTrace([]);
      return;
    }

    if (!shown.length) {
      results.innerHTML = '<p class="empty"><b>No papers match these filters.</b><br>' +
        "Widen the score range or clear a topic to see more.</p>";
      drawTrace([]);
      return;
    }

    var groups = {}, order = [];
    shown.forEach(function (it) {
      var k = it.added || "undated";
      if (!groups[k]) { groups[k] = []; order.push(k); }
      groups[k].push(it);
    });
    order.sort().reverse();

    results.innerHTML = order.map(function (day) {
      var list = groups[day].slice().sort(function (a, b) {
        return (b.score || 0) - (a.score || 0);
      });
      return '<section class="daygroup" data-daygroup="' + esc(day) + '">' +
        '<div class="dayhead"><b>' + esc(day) + "</b>" +
        '<span class="spacer"></span><span>' + list.length + " item" +
        (list.length === 1 ? "" : "s") + "</span></div>" +
        list.map(itemHTML).join("") + "</section>";
    }).join("");

    drawTrace(shown);
    $("stat-total").textContent = shown.length === DB.items.length
      ? DB.items.length : shown.length + "/" + DB.items.length;
  }

  /* ---------- wiring ---------- */

  function debounce(fn, ms) {
    var t; return function () {
      clearTimeout(t); t = setTimeout(fn, ms);
    };
  }

  function wire() {
    $("q").addEventListener("input", debounce(function () {
      active.q = $("q").value.trim(); apply();
    }, 140));

    $("tier").addEventListener("change", function () {
      active.tier = this.value; apply();
    });
    $("kind").addEventListener("change", function () {
      active.kind = this.value; apply();
    });
    $("minscore").addEventListener("input", function () {
      active.min = +this.value;
      $("minscore-val").textContent = this.value;
      apply();
    });

    $("reset").addEventListener("click", function () {
      active = { q: "", tier: "", kind: "", min: 0, topics: {} };
      $("q").value = ""; $("tier").value = ""; $("kind").value = "";
      $("minscore").value = 0; $("minscore-val").textContent = "0";
      Array.prototype.forEach.call(document.querySelectorAll(".chip"), function (b) {
        b.setAttribute("aria-pressed", "false");
      });
      apply();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== $("q")) {
        e.preventDefault(); $("q").focus();
      }
      if (e.key === "Escape" && document.activeElement === $("q")) {
        $("q").value = ""; active.q = ""; apply(); $("q").blur();
      }
    });
  }

  /* ---------- boot ---------- */

  function boot(data) {
    DB = data;
    DB.items = DB.items || [];

    try {
      lastVisit = localStorage.getItem(VISIT_KEY);
      localStorage.setItem(VISIT_KEY, new Date().toISOString().slice(0, 10));
    } catch (e) { lastVisit = null; }

    var fresh = lastVisit
      ? DB.items.filter(function (it) { return it.added > lastVisit; }).length
      : DB.items.length;

    $("stat-new").textContent = fresh;
    $("stat-total").textContent = DB.items.length;
    $("stat-gen").textContent = DB.generated
      ? "built " + DB.generated.replace("T", " ").replace("Z", " UTC") : "";

    var maxScore = DB.items.reduce(function (m, it) {
      return Math.max(m, it.score || 0);
    }, 20);
    $("minscore").max = Math.ceil(maxScore);

    buildChips();
    wire();
    apply();
  }

  fetch("data/items.json", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(boot)
    .catch(function (err) {
      $("results").innerHTML = '<p class="empty"><b>Could not load the archive.</b><br>' +
        "data/items.json is missing or unreadable (" + esc(err.message) + ").<br>" +
        "Run the workflow once to generate it.</p>";
    });
})();
