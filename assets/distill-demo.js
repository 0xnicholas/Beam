/* ==========================================================================
   distill-demo.js — how a teacher's prose becomes training labels.

   Mounts a widget over REAL distillation samples (assets/data/distill-samples.js,
   from the frozen pilot run training/distill/pilot-v1): the teacher's
   compressed output, the word-level keep/drop labels the matcher derived
   from it, and the quality-control metrics that decide whether the sample
   may enter the training set at all.

   Contract:
     <div class="sim" id="sim-distill"></div>
     <script src="../assets/data/distill-samples.js"></script>
     <script src="../assets/distill-demo.js"></script>
     <script>DistillDemo.mount(document.getElementById("sim-distill"), window.BEAM_DISTILL);</script>

   Token labels are the frozen run's own output: [word, 1=keep | 0=drop].
   The QC verdict reproduces the pipeline's rank rule: drop the top 5% by
   Variation Rate, then the top 10% of survivors by Alignment Gap — the
   per-sample display compares against the thresholds those cuts landed on.
   ========================================================================== */

(function () {
  "use strict";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  var TAGS = {
    rag: "RAG 长文",
    system_prompt: "system prompt",
    dialogue: "多轮对话",
    boundary: "边界样本",
  };

  function mount(root, data) {
    if (!root || !data) return;
    var samples = data.samples || [];
    if (!samples.length) return;
    var current = 0;

    var head = el("div", "sim-head");
    head.appendChild(el("div", "sim-title", "真实蒸馏样本：教师写了什么，标签怎么来"));
    var bar = el("div", "sim-levels");
    head.appendChild(bar);
    root.appendChild(head);

    var info = el("div", "sim-stats");
    root.appendChild(info);

    var outHead = el("div", "sim-stats");
    outHead.style.marginBottom = ".2rem";
    outHead.innerHTML = "<b>教师输出</b>（模型只许删词）";
    root.appendChild(outHead);

    var teacher = el("div", "sim-out");
    root.appendChild(teacher);

    var labHead = el("div", "sim-stats");
    labHead.style.marginTop = ".8rem";
    labHead.style.marginBottom = ".2rem";
    labHead.innerHTML = "<b>原词打标</b>（匹配器对齐回原文后的 keep / drop）";
    root.appendChild(labHead);

    var strip = el("div", "tok-strip");
    root.appendChild(strip);

    var legend = el("div", "legend");
    legend.innerHTML =
      '<span class="l-kept">保留</span><span class="l-drop">删除</span>';
    root.appendChild(legend);

    var metrics = el("div", "sim-stats");
    metrics.style.borderTop = "1px dashed var(--rule)";
    metrics.style.paddingTop = ".5rem";
    root.appendChild(metrics);

    var buttons = samples.map(function (s, i) {
      var b = el("button", null, TAGS[s.label] || TAGS[s.load_type] || s.load_type);
      b.type = "button";
      b.addEventListener("click", function () { render(i); });
      bar.appendChild(b);
      return b;
    });

    function pct(x) { return (x * 100).toFixed(2) + "%"; }

    function render(i) {
      current = i;
      var s = samples[i];
      buttons.forEach(function (b, j) {
        b.setAttribute("aria-pressed", j === i ? "true" : "false");
      });

      var shown = s.window.length;
      var winNote = shown < s.window_total
        ? "显示前 " + shown + " 个词（整块共 " + s.window_total + " 个词）"
        : "整块 " + shown + " 个词，全部显示";
      info.innerHTML =
        "<code>" + s.id + "</code> ｜ " + winNote +
        " ｜ 来源：" + s.source.dataset + "/" + s.source.subset +
        "（" + s.source.split + "）";

      teacher.textContent = s.compressed_head +
        (s.compressed_head.length >= 320 ? " …（截断显示）" : "");

      strip.textContent = "";
      s.window.forEach(function (tok) {
        var c = el("div", "tok");
        c.appendChild(el("span", "s", tok[0]));
        if (tok[1]) c.classList.add("kept"); else c.classList.add("dropped");
        c.title = tok[0] + (tok[1] ? " · 保留" : " · 删除");
        strip.appendChild(c);
      });

      var m = s.metrics;
      var qc = data.qc;
      var vrOver = m.variation_rate >= qc.vr_threshold;
      var agOver = m.alignment_gap >= qc.ag_threshold;
      var verdict = vrOver
        ? '<b style="color:var(--accent)">丢弃</b>（变差率 ' + m.variation_rate.toFixed(4) +
          " ≥ 边界 " + qc.vr_threshold + "）"
        : agOver
          ? '<b style="color:var(--accent)">压线保留</b>（对齐间隙 ' + m.alignment_gap.toFixed(4) +
            " = 边界 " + qc.ag_threshold + "，这一批里被保留的最后一名）"
          : '<b style="color:var(--keep)">通过质控</b>（两项都在边界内）';

      metrics.innerHTML =
        "教师保留率 <b>" + pct(m.word_compressed_rate) + "</b>（原文里 " +
        Math.round(m.matching_rate * s.window_total) + "/" + s.window_total + " 个词带上了保留标签）" +
        " ｜ 变差率 <b>" + m.variation_rate.toFixed(4) + "</b>（边界 " + qc.vr_threshold + "）" +
        " ｜ 对齐间隙 <b>" + m.alignment_gap.toFixed(4) + "</b>（边界 " + qc.ag_threshold + "）" +
        "<br>质控判定：" + verdict;
    }

    render(0);
  }

  window.DistillDemo = { mount: mount };
})();
