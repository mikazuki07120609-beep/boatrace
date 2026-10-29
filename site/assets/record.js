/* 見立ての成績のページ: 日ごとの「本線の艇が1着」と「毎回1号艇(1コース)と言った場合」の折れ線(SVG)。
   数字は下の表にもある(グラフは目安)。指やマウスを近づけると、その日の数字を出す。キーボードの左右でも動かせる。 */
(function () {
  "use strict";
  var el = document.getElementById("rec-data"), box = document.getElementById("recChart");
  if (!el || !box) return;
  var DAYS = (JSON.parse(el.textContent).days || []).filter(function (x) { return x.boat != null && x.one != null; });
  if (!DAYS.length) return;
  var NS = "http://www.w3.org/2000/svg";
  var SER = [{ k: "boat", name: "本線の艇が1着", cls: "main" }, { k: "one", name: "毎回1号艇(1コース)", cls: "base" }];
  var tip = document.createElement("div");
  tip.className = "rtip"; tip.hidden = true;
  box.appendChild(tip);
  var cur = null, geo = null;

  function mk(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(n);
    return n;
  }
  function md(iso) { return +iso.slice(5, 7) + "/" + +iso.slice(8, 10); }

  function draw() {
    var old = box.querySelector("svg");
    if (old) old.remove();
    var W = Math.max(300, box.clientWidth), H = 236, L = 34, R = 46, T = 14, B = 30;
    var vals = [];
    DAYS.forEach(function (x) { vals.push(x.boat, x.one); });
    var lo = Math.floor((Math.min.apply(null, vals) - 2) / 10) * 10, hi = Math.ceil((Math.max.apply(null, vals) + 2) / 10) * 10;
    if (hi - lo < 20) hi = lo + 20;
    var n = DAYS.length, pw = W - L - R, ph = H - T - B;
    function X(i) { return L + (n === 1 ? pw / 2 : pw * i / (n - 1)); }
    function Y(v) { return T + ph * (hi - v) / (hi - lo); }
    var svg = mk("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, tabindex: "0", focusable: "true",
                          "aria-label": "日ごとの成績の折れ線。左右のキーで日を選べます" });
    box.insertBefore(svg, tip);
    // 目盛り(10%ごと。細い実線)
    for (var v = lo; v <= hi; v += 10) {
      mk("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: "grid" }, svg);
      mk("text", { x: L - 6, y: Y(v) + 4, class: "tick", "text-anchor": "end" }, svg).textContent = v + "%";
    }
    // 日付(重ならないよう間引く)
    var step = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(pw / 38))));
    DAYS.forEach(function (x, i) {
      if (i % step && i !== n - 1) return;
      mk("text", { x: X(i), y: H - 9, class: "tick", "text-anchor": "middle" }, svg).textContent = md(x.d);
    });
    // 線(1号艇は控えめに、本線は強く)。終わりに点
    SER.slice().reverse().forEach(function (s) {
      var d = DAYS.map(function (x, i) { return (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(x[s.k]).toFixed(1); }).join(" ");
      if (n > 1) mk("path", { d: d, class: "ln " + s.cls }, svg);
      mk("circle", { cx: X(n - 1), cy: Y(DAYS[n - 1][s.k]), r: 4, class: "dot " + s.cls }, svg);
    });
    // 終わりの数字(2つが近すぎるときは出さず、凡例と下の表に任せる)
    var a = Y(DAYS[n - 1].boat), b = Y(DAYS[n - 1].one);
    if (Math.abs(a - b) >= 14) {
      SER.forEach(function (s) {
        mk("text", { x: X(n - 1) + 8, y: Y(DAYS[n - 1][s.k]) + 4, class: "endl" }, svg).textContent = Math.round(DAYS[n - 1][s.k]) + "%";
      });
    }
    // 縦の線(近い日に合わせる)
    var cross = mk("line", { x1: 0, x2: 0, y1: T, y2: T + ph, class: "cross" }, svg);
    cross.style.display = "none";
    var hot = [];
    SER.forEach(function (s) { var c = mk("circle", { r: 5, class: "dot hot " + s.cls }, svg); c.style.display = "none"; hot.push(c); });
    geo = { X: X, Y: Y, n: n, W: W, L: L, R: R, T: T, cross: cross, hot: hot, svg: svg };
    svg.addEventListener("pointermove", function (ev) {
      var r = svg.getBoundingClientRect(), x = ev.clientX - r.left, best = 0;
      for (var i = 1; i < n; i++) if (Math.abs(X(i) - x) < Math.abs(X(best) - x)) best = i;
      show(best);
    });
    svg.addEventListener("pointerleave", function () { if (document.activeElement !== svg) hide(); });
    svg.addEventListener("focus", function () { show(cur == null ? n - 1 : cur); });
    svg.addEventListener("blur", hide);
    svg.addEventListener("keydown", function (ev) {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      ev.preventDefault();
      show(Math.max(0, Math.min(n - 1, (cur == null ? n - 1 : cur) + (ev.key === "ArrowLeft" ? -1 : 1))));
    });
    if (cur != null) show(cur);
  }
  function show(i) {
    if (!geo) return;
    cur = i;
    var x = DAYS[i], px = geo.X(i);
    geo.cross.setAttribute("x1", px); geo.cross.setAttribute("x2", px); geo.cross.style.display = "";
    SER.forEach(function (s, j) { geo.hot[j].setAttribute("cx", px); geo.hot[j].setAttribute("cy", geo.Y(x[s.k])); geo.hot[j].style.display = ""; });
    tip.textContent = "";
    var h = document.createElement("div"); h.className = "th"; h.textContent = md(x.d) + "・" + x.n + "レース"; tip.appendChild(h);
    SER.forEach(function (s) {
      var row = document.createElement("div"); row.className = "tr";
      var k = document.createElement("span"); k.className = "k " + s.cls; row.appendChild(k);
      var b = document.createElement("b"); b.textContent = x[s.k].toFixed(1) + "%"; row.appendChild(b);
      var t = document.createElement("span"); t.className = "tn"; t.textContent = s.name; row.appendChild(t);
      tip.appendChild(row);
    });
    tip.hidden = false;
    var tw = tip.offsetWidth, left = px + 12;
    if (left + tw > geo.W - 4) left = px - tw - 12;
    tip.style.left = Math.max(4, left) + "px";
    tip.style.top = geo.T + "px";
  }
  function hide() {
    if (!geo) return;
    tip.hidden = true; geo.cross.style.display = "none";
    geo.hot.forEach(function (c) { c.style.display = "none"; });
  }
  draw();
  var rt = null;
  window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(draw, 120); });
})();
