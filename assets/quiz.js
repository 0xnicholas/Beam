/* ==========================================================================
   quiz.js — reusable retrieval-practice widgets for Beam lessons.
   Vanilla JS, no dependencies, works from file://.

   Markup contracts (all optional; auto-initialised on DOMContentLoaded):

   1) Single-answer multiple choice
      <div class="quiz">
        <p class="quiz-q">问题？</p>
        <button class="quiz-opt" data-correct="true">选项</button>
        <button class="quiz-opt">选项</button>
        <p class="quiz-fb"><strong>对/不对。</strong>解释…</p>
      </div>

   2) Multi-answer ("选出所有正确项"): add data-multi="true" to .quiz and a
      result button; every option needs data-correct true/false.
      <div class="quiz" data-multi="true"> … <button class="quiz-check">检查</button>

   3) Write-then-reveal (self-graded recall)
      <div class="recall" data-key="lesson-id:1">
        <textarea placeholder="…"></textarea>
        <div class="recall-bar"><button class="recall-btn">对照参考答案</button></div>
        <div class="recall-answer">…</div>
      </div>
      The draft is persisted (localStorage, best effort) so a later visit
      lets the learner compare against their own earlier words.
   ========================================================================== */

(function () {
  "use strict";

  var store = {
    get: function (k) {
      try { return window.localStorage.getItem(k); } catch (e) { return null; }
    },
    set: function (k, v) {
      try { window.localStorage.setItem(k, v); } catch (e) { /* file:// or private mode */ }
    },
  };

  function feedback(quiz, text, cls) {
    var fb = quiz.querySelector(".quiz-fb");
    if (!fb) return;
    fb.innerHTML = text;
    fb.classList.add("show");
    if (cls) fb.classList.add(cls);
  }

  function initSingle(quiz) {
    var opts = Array.prototype.slice.call(quiz.querySelectorAll(".quiz-opt"));
    var answered = false;
    opts.forEach(function (opt) {
      opt.addEventListener("click", function () {
        if (answered) return;
        answered = true;
        opts.forEach(function (o) {
          o.disabled = true;
          if (o.dataset.correct === "true") {
            o.classList.add("correct");
            var m = document.createElement("span");
            m.className = "mark";
            m.textContent = "正确答案";
            o.appendChild(m);
          }
        });
        if (opt.dataset.correct !== "true") opt.classList.add("wrong");
        quiz.dataset.result = opt.dataset.correct === "true" ? "correct" : "wrong";
        var fb = quiz.querySelector(".quiz-fb");
        if (fb && fb.dataset.correctText && fb.dataset.wrongText) {
          feedback(quiz, opt.dataset.correct === "true" ? fb.dataset.correctText : fb.dataset.wrongText);
        } else if (fb) {
          fb.classList.add("show");
        }
        document.dispatchEvent(new CustomEvent("quiz:answered", {
          detail: { result: quiz.dataset.result },
        }));
      });
    });
  }

  function initMulti(quiz) {
    var opts = Array.prototype.slice.call(quiz.querySelectorAll(".quiz-opt"));
    var btn = quiz.querySelector(".quiz-check");
    var done = false;

    opts.forEach(function (opt) {
      opt.addEventListener("click", function () {
        if (done) return;
        var on = opt.getAttribute("aria-pressed") === "true";
        opt.setAttribute("aria-pressed", on ? "false" : "true");
        opt.classList.toggle("correct", !on);
      });
    });

    if (!btn) return;
    btn.addEventListener("click", function () {
      if (done) return;
      done = true;
      var wrong = 0;
      var missed = 0;
      opts.forEach(function (opt) {
        var picked = opt.getAttribute("aria-pressed") === "true";
        var right = opt.dataset.correct === "true";
        opt.disabled = true;
        if (picked && !right) { opt.classList.add("wrong"); opt.classList.remove("correct"); wrong++; }
        if (!picked && right) { opt.classList.add("correct"); missed++; }
      });
      quiz.dataset.result = wrong === 0 && missed === 0 ? "correct" : "wrong";
      feedback(
        quiz,
        wrong === 0 && missed === 0
          ? "<strong>全对。</strong>漏选和多选都是零。"
          : "<strong>还差一点：</strong>多选了 " + wrong + " 项，漏选 " + missed + " 项。绿色是正确集合。"
      );
      btn.disabled = true;
    });
  }

  function initRecall(box, index) {
    var ta = box.querySelector("textarea");
    var btn = box.querySelector(".recall-btn");
    var ans = box.querySelector(".recall-answer");
    var key = "beam-recall:" + (box.dataset.key || "item-" + index);

    if (ta) {
      var saved = store.get(key);
      if (saved) {
        ta.value = saved;
        var bar = box.querySelector(".recall-bar");
        if (bar) {
          var note = document.createElement("span");
          note.textContent = "已恢复你上次写的内容";
          bar.appendChild(note);
        }
      }
      ta.addEventListener("input", function () { store.set(key, ta.value); });
    }

    if (btn && ans) {
      btn.addEventListener("click", function () {
        var open = ans.classList.toggle("show");
        btn.textContent = open ? "收起参考答案" : "对照参考答案";
      });
    }
  }

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll(".quiz"), function (q) {
      if (q.dataset.multi === "true") initMulti(q); else initSingle(q);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".recall"), initRecall);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.BeamQuiz = { init: init };
})();
