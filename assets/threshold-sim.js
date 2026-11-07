/* ==========================================================================
   threshold-sim.js — the compressor's decision rule, made draggable.

   Mounts a widget that replays a REAL measured forward pass: every token
   of an example text with the keep-probability the production checkpoint
   (llmlingua-2-bert-base-multilingual-cased-meetingbank) actually assigned
   it, plus the real decoded output at each swept level.

   Contract:
     <div class="sim" id="sim-1"></div>
     <script src="../assets/data/trace-zh.js"></script>
     <script src="../assets/threshold-sim.js"></script>
     <script>
       ThresholdSim.mount(document.getElementById("sim-1"), window.BEAM_TRACE_ZH, {
         levels: [0.1, 0.2, 0.3, 0.4, 0.5],   // optional
         initial: 0.2,                         // optional
         title: "…"                            // optional
       });
     </script>

   Trace shape (see assets/data/*.js):
     { text, tokens: [{surface, token, p, fact, special}], levels: { "0.2": {kept, total, ...} } }

   The rule replayed is compressor.py `_compress_one`, minus the optional
   min_tokens floor / max_tokens cap (this demo runs neither):
     keep  ⇔  p >= level        (forced tokens have p = 1.0)
   ========================================================================== */

(function () {
  "use strict";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function pct(x) { return (x * 100).toFixed(1) + "%"; }

  function mount(root, trace, opts) {
    if (!root || !trace) return;
    opts = opts || {};
    var levels = opts.levels || [0.1, 0.2, 0.3, 0.4, 0.5];
    var level = opts.initial !== undefined ? opts.initial : 0.2;

    var head = el("div", "sim-head");
    head.appendChild(el("div", "sim-title", opts.title || "真实前向：拖动档位，看 token 生死"));
    var levelBar = el("div", "sim-levels");
    head.appendChild(levelBar);
    root.appendChild(head);

    var strip = el("div", "tok-strip");
    root.appendChild(strip);

    var legend = el("div", "legend");
    legend.innerHTML =
      '<span class="l-kept">保留（p ≥ 档位）</span>' +
      '<span class="l-drop">删除（p &lt; 档位）</span>' +
      '<span class="l-force">强制保留（事实 / 结构 token）</span>';
    root.appendChild(legend);

    var stats = el("div", "sim-stats");
    root.appendChild(stats);

    var out = el("div", "sim-out");
    root.appendChild(out);

    var guessWrap = el("div", "sim-guess");
    guessWrap.innerHTML =
      '<label>先猜：档位 0.2 时保留几个 token？</label>' +
      '<input type="number" min="0" step="1" inputmode="numeric" aria-label="猜测保留的 token 数">' +
      '<button type="button">对答案</button>' +
      '<span class="sim-verdict"></span>';
    root.appendChild(guessWrap);

    var input = guessWrap.querySelector("input");
    var gbtn = guessWrap.querySelector("button");
    var verdict = guessWrap.querySelector(".sim-verdict");

    var chips = trace.tokens.map(function (t) {
      var c = el("div", "tok");
      c.appendChild(el("span", "s", t.surface === "" ? "∅" : t.surface));
      c.appendChild(el("span", "p", t.p.toFixed(2).replace(/^0/, "")));
      c.title = t.token + " · p(keep) = " + t.p + (t.fact ? " · 被事实正则强制保留" : "");
      if (t.special) c.classList.add("special", "forced");
      if (t.fact) c.classList.add("forced");
      return c;
    });
    chips.forEach(function (c) { strip.appendChild(c); });

    var buttons = levels.map(function (lv) {
      var b = el("button", null, lv.toFixed(1));
      b.type = "button";
      b.addEventListener("click", function () { render(lv); });
      levelBar.appendChild(b);
      return b;
    });

    function render(lv) {
      level = lv;
      buttons.forEach(function (b) {
        b.setAttribute("aria-pressed", parseFloat(b.textContent) === lv ? "true" : "false");
      });

      var kept = 0;
      trace.tokens.forEach(function (t, i) {
        var keep = t.p >= lv;
        if (keep) kept++;
        var c = chips[i];
        c.classList.toggle("kept", keep);
        c.classList.toggle("dropped", !keep);
      });

      var total = trace.tokens.length;
      var measured = trace.levels[String(lv)];
      var realKept = measured ? measured.kept : kept;
      stats.innerHTML =
        "档位 <b>" + lv.toFixed(1) + "</b>（阈值，非比例） ｜ 保留 <b>" + realKept + "/" + total +
        "</b> ｜ 保留率 <b>" + pct(realKept / total) + "</b> ｜ 压缩率 <b>" +
        pct(1 - realKept / total) + "</b>";
      out.textContent = measured
        ? measured.text
        : "（此档位没有实测 decode，仅显示规则判定）";
    }

    gbtn.addEventListener("click", function () {
      var v = parseFloat(input.value);
      if (isNaN(v)) { verdict.className = "sim-verdict"; verdict.textContent = "先填一个数字。"; return; }
      var actual = trace.tokens.filter(function (t) { return t.p >= 0.2; }).length;
      var d = Math.abs(v - actual);
      if (d === 0) {
        verdict.className = "sim-verdict ok";
        verdict.textContent = "正好 " + actual + " 个。这个数不是猜出来的，是可数出来的——这正是下一节要讲的。";
      } else {
        verdict.className = "sim-verdict off";
        verdict.textContent = "实际是 " + actual + " 个，差 " + d + " 个。数一遍：把 p ≥ 0.20 的 token 逐个标出来。";
      }
    });

    render(level);
  }

  window.ThresholdSim = { mount: mount };
})();
