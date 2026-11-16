/* 一節まとめのタブ(まとめ・前検・日ごと)。開いたタブはアドレスの # に残す(戻る・共有で同じタブが開く) */
(function () {
  "use strict";
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".stabs [data-tab]"));
  if (!tabs.length) return;
  var names = tabs.map(function (b) { return b.getAttribute("data-tab"); });
  function show(name, push) {
    if (names.indexOf(name) < 0) name = names[0];
    tabs.forEach(function (b) { var on = b.getAttribute("data-tab") === name; b.classList.toggle("on", on); b.setAttribute("aria-selected", on ? "true" : "false"); });
    Array.prototype.forEach.call(document.querySelectorAll(".pane"), function (p) { p.hidden = p.id !== "pane-" + name; });
    if (push) { try { history.replaceState(null, "", "#" + name); } catch (e) { /* 古いブラウザ */ } }
  }
  tabs.forEach(function (b) {
    b.addEventListener("click", function () {
      show(b.getAttribute("data-tab"), true);
      var bar = document.querySelector(".stabs");
      if (bar && bar.getBoundingClientRect().top < 0) bar.scrollIntoView({ block: "start" });
    });
  });
  window.addEventListener("hashchange", function () { var x = (location.hash || "").replace("#", ""); if (names.indexOf(x) >= 0) show(x, false); });
  var h = (location.hash || "").replace("#", "");
  if (h && names.indexOf(h) >= 0) show(h, false);
  else { var on = tabs.filter(function (b) { return b.classList.contains("on"); })[0]; show(on ? on.getAttribute("data-tab") : names[0], false); }
  // 選んでいるタブが横にはみ出していたら、真ん中あたりへ
  var cur = document.querySelector(".stabs button.on"), bar = document.querySelector(".stabs");
  if (cur && bar && cur.offsetLeft + cur.offsetWidth > bar.clientWidth) bar.scrollLeft = cur.offsetLeft - (bar.clientWidth - cur.offsetWidth) / 2;
})();
