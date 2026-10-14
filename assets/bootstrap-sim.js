/* ==========================================================================
   bootstrap-sim.js — why "the CI lower bound is not negative" is the claim.

   Mounts a widget that replays the yardstick's statistics on REAL judged
   scores: the 149 per-item quality deltas of a frozen run
   (assets/data/quality-deltas.js, from metrics.json ->
   aggregate.task_quality.items).

   The learner draws a *paired percentile bootstrap* by hand: resample the
   prompt set with replacement, take the mean, watch the distribution of
   means build up. The interval that ends up enclosing 95% of those means
   is the reported CI.

   Contract:
     <div class="sim" id="sim-boot"></div>
     <script src="../assets/data/quality-deltas.js"></script>
     <script src="../assets/bootstrap-sim.js"></script>
     <script>
       BootstrapSim.mount(document.getElementById("sim-boot"),
                          window.LEIA_DELTAS, {checkpoint: "mbert", level: 0.2});
     </script>

   Caliber note: the demo draws with Math.random and reports percentiles by
   linear interpolation between order statistics — the same percentile
   caliber as the harness (src/leia/quality.py), a different RNG (the
   report seed is pinned and printed alongside for comparison).
   ========================================================================== */

(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var W = 620, H = 190, PAD = {l: 8, r: 8, t: 10, b: 26};
  var RANGE = 0.15;   // half-width of the plotted window around the mean
  var BINS = 61;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function svg(tag, attrs) {
    var n = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }

  // linear-interpolation percentile over a sorted array (harness caliber)
  function quantile(sorted, p) {
    if (!sorted.length) return NaN;
    if (sorted.length === 1) return sorted[0];
    var rank = (p / 100) * (sorted.length - 1);
    var lo = Math.floor(rank), hi = Math.min(lo + 1, sorted.length - 1);
    return sorted[lo] + (rank - lo) * (sorted[hi] - sorted[lo]);
  }

  function fmt(x, d) { return (x >= 0 ? "+" : "") + x.toFixed(d === undefined ? 4 : d); }

  function mount(root, data, opts) {
    if (!root || !data) return;
    opts = opts || {};
    var cpName = opts.checkpoint || "mbert";
    var cp = data.checkpoints[cpName];
    if (!cp) return;

    var levels = cp.levels.map(function (l) { return l.level; });
    var level = opts.level !== undefined ? opts.level : levels[0];
    var n = 149;                      // draw size (sample-size teaching knob)
    var means = [];                   // accumulated bootstrap means

    // ── chrome ────────────────────────────────────────────────────────────
    var head = el("div", "sim-head");
    head.appendChild(el("div", "sim-title", "亲手跑一次配对 bootstrap · " + (cp.label || cp.model_id)));
    var bar = el("div", "sim-levels");
    head.appendChild(bar);
    root.appendChild(head);

    var controls = el("div", "sim-guess");
    controls.innerHTML =
      '<label>每次重采样抽几条 prompt？</label>' +
      '<select aria-label="样本量">' +
        '<option value="149" selected>全部 149 条</option>' +
        '<option value="45">只用 45 条</option>' +
        '<option value="15">只用 15 条</option>' +
      '</select>' +
      '<button type="button" data-act="step">再抽 200 次</button>' +
      '<button type="button" data-act="run">跑满 10000 次</button>' +
      '<button type="button" data-act="reset">重置</button>';
    root.appendChild(controls);

    var stats = el("div", "sim-stats");
    root.appendChild(stats);

    var chartWrap = el("div", "sim-out");
    chartWrap.style.padding = "0.3rem 0.2rem";
    root.appendChild(chartWrap);

    var verdict = el("div", "sim-stats");
    verdict.style.borderTop = "1px dashed var(--rule)";
    verdict.style.paddingTop = "0.5rem";
    root.appendChild(verdict);

    var svgRoot = svg("svg", {
      viewBox: "0 0 " + W + " " + H,
      width: "100%",
      role: "img",
      "aria-label": "bootstrap 均值分布",
    });
    chartWrap.appendChild(svgRoot);

    // ── per-level state ───────────────────────────────────────────────────
    function levelData() {
      return cp.levels.filter(function (l) { return l.level === level; })[0];
    }

    function xScale(center) {
      var lo = center - RANGE, hi = center + RANGE;
      return {
        lo: lo,
        hi: hi,
        x: function (v) {
          return PAD.l + (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * (W - PAD.l - PAD.r);
        },
      };
    }

    function draw() {
      var d = levelData();
      var sc = xScale(d.mean);
      svgRoot.textContent = "";

      var baseY = H - PAD.b;

      // histogram of accumulated bootstrap means
      var counts = new Array(BINS).fill(0);
      var maxCount = 1;
      means.forEach(function (m) {
        var b = Math.floor((m - sc.lo) / (sc.hi - sc.lo) * BINS);
        if (b >= 0 && b < BINS) { counts[b]++; maxCount = Math.max(maxCount, counts[b]); }
      });
      var bw = (W - PAD.l - PAD.r) / BINS;
      counts.forEach(function (c, i) {
        if (!c) return;
        var h = (c / maxCount) * (baseY - PAD.t - 14);
        svgRoot.appendChild(svg("rect", {
          x: PAD.l + i * bw, y: baseY - h, width: Math.max(bw - 1, 1), height: h,
          fill: "var(--keep)", opacity: 0.35,
        }));
      });

      // real deltas as a rug along the axis (each judged item)
      d.deltas.forEach(function (v) {
        svgRoot.appendChild(svg("line", {
          x1: sc.x(v), x2: sc.x(v), y1: baseY + 1, y2: baseY + 7,
          stroke: "var(--muted)", "stroke-width": 1, opacity: 0.5,
        }));
      });

      // axis
      svgRoot.appendChild(svg("line", {
        x1: PAD.l, x2: W - PAD.r, y1: baseY, y2: baseY, stroke: "var(--rule)", "stroke-width": 1,
      }));
      [sc.lo, 0, sc.hi].forEach(function (t) {
        svgRoot.appendChild(svg("line", {
          x1: sc.x(t), x2: sc.x(t), y1: baseY, y2: baseY + 4,
          stroke: t === 0 ? "var(--accent)" : "var(--rule)", "stroke-width": 1,
        }));
        // edge labels anchor inward so they are never clipped by the viewBox
        var anchor = t === sc.lo ? "start" : (t === sc.hi ? "end" : "middle");
        var lab = svg("text", {
          x: sc.x(t), y: H - 8, "text-anchor": anchor, "font-size": 11,
          fill: t === 0 ? "var(--accent)" : "var(--muted)", "font-family": "var(--mono)",
        });
        lab.textContent = (t > 0 ? "+" : "") + t.toFixed(2);
        svgRoot.appendChild(lab);
      });
      var zeroLab = svg("text", {
        x: sc.x(0), y: PAD.t + 10, "text-anchor": "middle", "font-size": 11,
        fill: "var(--accent)", "font-family": "var(--sans)",
      });
      zeroLab.textContent = "0 = 与原文持平";
      svgRoot.appendChild(zeroLab);

      // observed mean marker
      svgRoot.appendChild(svg("line", {
        x1: sc.x(d.mean), x2: sc.x(d.mean), y1: PAD.t, y2: baseY,
        stroke: "var(--ink)", "stroke-width": 1.5, "stroke-dasharray": "3 3",
      }));

      // CI band from the accumulated resamples
      var sorted = means.slice().sort(function (a, b) { return a - b; });
      if (sorted.length >= 50) {
        var lo = quantile(sorted, 2.5), hi = quantile(sorted, 97.5);
        svgRoot.appendChild(svg("rect", {
          x: sc.x(lo), y: PAD.t, width: Math.max(sc.x(hi) - sc.x(lo), 1), height: baseY - PAD.t,
          fill: "var(--accent)", opacity: 0.12,
        }));
      }
    }

    function update() {
      var d = levelData();
      var sorted = means.slice().sort(function (a, b) { return a - b; });
      var simMean = means.length ? means.reduce(function (a, b) { return a + b; }, 0) / means.length : NaN;
      var lo = quantile(sorted, 2.5), hi = quantile(sorted, 97.5);

      stats.innerHTML =
        "档位 <b>" + d.level.toFixed(1) + "</b> ｜ 已模拟 <b>" + means.length + "</b> 次" +
        " ｜ 每次抽 <b>" + n + "</b> 条 ｜ 模拟均值 <b>" +
        (means.length ? fmt(simMean) : "—") + "</b>";

      verdict.innerHTML = means.length >= 50
        ? "本次模拟的 95% 区间：<b>[" + fmt(lo) + ", " + fmt(hi) + "]</b> ｜ " +
          "判据（下界不为负）：<b>" + (lo >= 0 ? "通过" : "不通过") + "</b><br>" +
          "<span style='opacity:.75'>冻结报告：均值 " + fmt(d.mean) + "，CI [" +
          fmt(d.ci[0]) + ", " + fmt(d.ci[1]) + "]（RNG 种子 " +
          cp.bootstrap_meta.seed + "，与本次演示的随机数不同，数字会略有差异——这正是要找的可审计出处）</span>"
        : "再多抽几次（至少 50 次），区间才会稳定下来。";

      draw();
    }

    function resample(times) {
      var d = levelData();
      for (var t = 0; t < times; t++) {
        var sum = 0;
        for (var i = 0; i < n; i++) {
          sum += d.deltas[Math.floor(Math.random() * d.deltas.length)];
        }
        means.push(sum / n);
      }
      update();
    }

    levels.forEach(function (lv) {
      var b = el("button", null, lv.toFixed(1));
      b.type = "button";
      b.addEventListener("click", function () {
        level = lv;
        means = [];
        Array.prototype.forEach.call(bar.children, function (x) {
          x.setAttribute("aria-pressed", x === b ? "true" : "false");
        });
        update();
      });
      bar.appendChild(b);
    });
    bar.children[levels.indexOf(level)] && bar.children[levels.indexOf(level)].setAttribute("aria-pressed", "true");

    controls.addEventListener("click", function (ev) {
      var act = ev.target && ev.target.dataset ? ev.target.dataset.act : null;
      if (act === "step") resample(200);
      if (act === "run") resample(Math.max(0, 10000 - means.length));
      if (act === "reset") { means = []; update(); }
    });
    controls.querySelector("select").addEventListener("change", function (ev) {
      n = parseInt(ev.target.value, 10);
      means = [];
      update();
    });

    update();
  }

  window.BootstrapSim = { mount: mount };
})();
