/* ==========================================================================
   delivery-verify.js — the drop-in contract clinic.

   Mounts a widget that lets a reader break a candidate checkpoint one way
   at a time and watch the verdict move. The check ids, the detail strings
   and the remedy strings are lifted verbatim from the real verifier
   (src/leia/delivery.py): the same seven checks, the same wording, the
   same pass / violation / unverified three-state rule. Only the toggles
   are invented — the code paths they represent are real export mistakes.

   Default state (every toggle off) is the frozen pilot checkpoint
   `runs/train/pilot-v1/checkpoint`, whose `verify-report.json` is the
   source of the default details.

   Contract:
     <div class="sim" id="sim-verify"></div>
     <script src="../assets/delivery-verify.js"></script>
     <script>DeliveryVerify.mount(document.getElementById("sim-verify"));</script>
   ========================================================================== */

(function () {
  "use strict";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  var KNOBS = [
    { id: "deps", label: "没装 torch", title: "这台机器跑不了加载层" },
    { id: "slow", label: "只带 vocab.txt", title: "tokenizer 是慢的（无 tokenizer.json）" },
    { id: "invert", label: "id2label 写反", title: "0: keep / 1: drop" },
    { id: "three", label: "头改成 3 标签", title: "num_labels = 3" },
    { id: "xlmr", label: "底座换 XLM-R 类", title: "RobertaForTokenClassification" },
  ];

  // Remedies are the verifier's own strings, verbatim, so a reader who
  // hits one of these for real recognises it.
  var REMEDY = {
    architecture_class:
      "export the checkpoint so config.json architectures includes " +
      "'BertForTokenClassification' (AutoModelForTokenClassification.save_pretrained)",
    num_labels:
      "export the classification head with exactly 2 labels (keep/drop); " +
      "the host reads a 2-column logits tensor",
    id2label_semantics:
      "swap id2label so index 0 names the drop class and index 1 the keep " +
      "class; the host computes keep probability as softmax(logits)[..., 1]",
    fast_tokenizer:
      "ship a fast tokenizer (tokenizer.json): the host calls the tokenizer " +
      "with return_offsets_mapping=True, which slow tokenizers cannot serve",
    offsets_available: "fix the fast-tokenizer asset first (see fast_tokenizer)",
    fast_tokenizer_runtime:
      "the runtime tokenizer must be fast with usable offsets (return_offsets_mapping)",
    dot_bert_attribute:
      "the host similarity guardrail calls model.bert(**inputs) directly — only " +
      "BertForTokenClassification-family bases qualify (decisions.md §6; XLM-R's " +
      ".roberta fails here)",
  };

  // What each violated item costs in the host. Coordinates are against
  // tokencamp-pro HEAD 6b03be5 (2026-10-14).
  var IMPACT = {
    architecture_class:
      "契约第 ④ 条（与现网同架构基底）同时不成立——延迟档案与内存占用不再可比，延迟闸失去意义。",
    num_labels:
      "宿主只读第 1 列当保留概率（<code>softmax(logits)[..., 1]</code>）。列数变了，索引语义跟着变。",
    id2label_semantics:
      "<b>最危险的一条</b>：能加载、不报错、压缩照跑，只是保留与删除反了。切换后「看起来生效了」，质量却往下走。",
    fast_tokenizer:
      "强制保留靠 offsets 把事实区间映射到 token；没有 fast tokenizer，数字事实的保护直接失效。",
    offsets_available:
      "同上——静态层在这里就已经拦住了，不必等到运行时。",
    fast_tokenizer_runtime:
      "静态层过了不等于运行时能给 offsets。这一条要真的实例化 tokenizer 才验得出来。",
    dot_bert_attribute:
      "<code>refiner.py:338</code> 的相似度 guardrail 直接调 <code>self.compressor.model.bert(**inputs)</code>；XLM-R 的 <code>.roberta</code> 在这里抛异常，请求回落到原文（fail-open，不报错但白干）。",
  };

  function evaluate(s) {
    var staticChecks = [];
    var loadChecks = [];

    staticChecks.push({
      id: "architecture_class",
      status: s.xlmr ? "violation" : "pass",
      detail: s.xlmr
        ? "architectures = ['RobertaForTokenClassification']"
        : "architectures = ['BertForTokenClassification']",
    });

    staticChecks.push({
      id: "num_labels",
      status: s.three ? "violation" : "pass",
      detail: s.three
        ? "num_labels = 3 (id2label has 3 entries)"
        : "num_labels = 2 (id2label has 2 entries)",
    });

    var labelDetail = "id2label = {0: 'drop', 1: 'keep'}";
    var labelBad = s.three || s.invert;
    if (s.invert) {
      labelDetail =
        "id2label = {0: 'keep', 1: 'drop'} — names contradict positional semantics";
    } else if (s.three) {
      labelDetail = "id2label = {0: 'drop', 1: 'keep', 2: 'other'}";
    }
    staticChecks.push({
      id: "id2label_semantics",
      status: labelBad ? "violation" : "pass",
      detail: labelDetail,
    });

    staticChecks.push({
      id: "fast_tokenizer",
      status: s.slow ? "violation" : "pass",
      detail: s.slow
        ? "no loadable tokenizer.json under <checkpoint>"
        : "tokenizer.json loads with the fast-tokenizer library",
    });

    staticChecks.push({
      id: "offsets_available",
      status: s.slow ? "violation" : "pass",
      detail: s.slow
        ? "cannot check offsets: no loadable fast tokenizer"
        : "probe encodes to 12 tokens, 12 non-degenerate offset spans",
    });

    var load;
    if (s.deps) {
      load = {
        status: "unverified",
        reason:
          "transformers/torch not installed — enable with `uv sync --group load` " +
          "to verify by real instantiation",
        checks: [],
      };
    } else {
      loadChecks.push({
        id: "fast_tokenizer_runtime",
        status: s.slow ? "violation" : "pass",
        detail: s.slow ? "is_fast=False, 0 offset spans" : "is_fast=True, 14 offset spans",
      });
      loadChecks.push({
        id: "dot_bert_attribute",
        status: s.xlmr ? "violation" : "pass",
        detail: s.xlmr
          ? "model type RobertaForTokenClassification lacks `.bert`"
          : "model type BertForTokenClassification exposes `.bert`",
      });
      var bad = loadChecks.some(function (c) { return c.status === "violation"; });
      load = { status: bad ? "violation" : "pass", reason: "", checks: loadChecks };
    }

    var staticBad = staticChecks.some(function (c) { return c.status === "violation"; });
    var staticStatus = staticBad ? "violation" : "pass";
    var overall =
      staticStatus === "violation" || load.status === "violation" ? "violation" : "pass";
    return { static: staticChecks, staticStatus: staticStatus, load: load, overall: overall };
  }

  function checkRow(c) {
    var row = el("div", "chk " + c.status);
    row.appendChild(el("div", "verdict", c.status.toUpperCase()));
    var body = el("div");
    body.appendChild(el("span", "id", c.id));
    var detail = el("span", "detail");
    detail.textContent = c.detail;
    body.appendChild(detail);
    if (c.status === "violation") {
      var remedy = el("span", "remedy");
      remedy.innerHTML = "remedy: " + REMEDY[c.id];
      body.appendChild(remedy);
      var impact = el("span", "impact");
      impact.innerHTML = "宿主后果：" + IMPACT[c.id];
      body.appendChild(impact);
    }
    row.appendChild(body);
    return row;
  }

  function mount(root) {
    if (!root) return;
    var state = {};
    KNOBS.forEach(function (k) { state[k.id] = false; });

    var head = el("div", "sim-head");
    head.appendChild(el("div", "sim-title", "契约体检台：一次只弄坏一处，看判定怎么动"));
    root.appendChild(head);

    var intro = el("div", "sim-stats");
    intro.innerHTML =
      "默认状态 = 真实 pilot 产物 <code>runs/train/pilot-v1/checkpoint</code>" +
      "（digest <code>8c35908db52f…</code>）。下面五个开关各自代表一种真实的导出失误。";
    root.appendChild(intro);

    var toggles = el("div", "sim-levels");
    var buttons = KNOBS.map(function (k) {
      var b = el("button", null, k.label);
      b.type = "button";
      b.title = k.title;
      b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", function () {
        state[k.id] = !state[k.id];
        b.setAttribute("aria-pressed", state[k.id] ? "true" : "false");
        render();
      });
      toggles.appendChild(b);
      return b;
    });
    root.appendChild(toggles);

    var staticHead = el("div", "sim-stats");
    staticHead.style.marginBottom = ".2rem";
    root.appendChild(staticHead);
    var staticList = el("div", "chk-list");
    root.appendChild(staticList);

    var loadHead = el("div", "sim-stats");
    loadHead.style.marginTop = ".9rem";
    loadHead.style.marginBottom = ".2rem";
    root.appendChild(loadHead);
    var loadList = el("div", "chk-list");
    root.appendChild(loadList);

    var verdict = el("div", "sim-stats");
    verdict.style.borderTop = "1px dashed var(--rule)";
    verdict.style.paddingTop = ".5rem";
    verdict.style.marginTop = ".9rem";
    root.appendChild(verdict);

    function layerLine(label, status, passed, total) {
      var cls = status === "pass" ? "ok" : status === "violation" ? "off" : "";
      return (
        label + "：" +
        '<b class="sim-verdict ' + cls + '">' + status.toUpperCase() + "</b>" +
        (total ? "（" + passed + "/" + total + " 项通过）" : "")
      );
    }

    function render() {
      var r = evaluate(state);

      var sPassed = r.static.filter(function (c) { return c.status === "pass"; }).length;
      staticHead.innerHTML = layerLine(
        "<b>静态层</b>（config.json + tokenizer.json，默认依赖）",
        r.staticStatus, sPassed, r.static.length
      );
      staticList.textContent = "";
      r.static.forEach(function (c) { staticList.appendChild(checkRow(c)); });

      loadList.textContent = "";
      if (r.load.status === "unverified") {
        loadHead.innerHTML =
          layerLine("<b>加载层</b>（真实例化）", "unverified") +
          '<br><span style="font-size:.74rem">' + r.load.reason + "</span>";
      } else {
        var lPassed = r.load.checks.filter(function (c) { return c.status === "pass"; }).length;
        loadHead.innerHTML = layerLine(
          "<b>加载层</b>（真实例化）", r.load.status, lPassed, r.load.checks.length
        );
        r.load.checks.forEach(function (c) { loadList.appendChild(checkRow(c)); });
      }

      var overallCls = r.overall === "pass" ? "ok" : "off";
      var caveat =
        r.overall === "pass" && r.load.status === "unverified"
          ? "——但加载层这次没验：<b>UNVERIFIED 不是 PASS</b>。"
          : r.overall === "pass"
            ? "——两层都过了，这才是可以交付的状态。"
            : "——契约不过就不许打包（<code>delivery pack</code> 会拒绝）。";
      verdict.innerHTML =
        "overall：" +
        '<b class="sim-verdict ' + overallCls + '">' + r.overall.toUpperCase() + "</b> " +
        caveat;
    }

    render();
  }

  window.DeliveryVerify = { mount: mount };
})();
