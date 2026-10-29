/* レースのページのオッズのタブ。締切の15分前から締切までは、1分ごとに取り込んでいるオッズ(Cloudflare か odds ブランチ)を読み直して出す。
   締切のあとは締切時オッズ。矢印は、ひとつ前の取り込み(約1分前)からの変化。 */
(function () {
  "use strict";
  var el = document.getElementById("race-data"), box = document.getElementById("odBox");
  if (!el || !box) return;
  var D = JSON.parse(el.textContent);
  var REL = D.race.ymd + "/" + D.venue.code + "/" + ("0" + D.race.no).slice(-2) + ".json";
  // オッズの読み込み(ページの頭の suimenGet: 先に Cloudflare、だめなら GitHub の odds ブランチ)。古いページと組み合わさったときは GitHub だけ
  var getData = window.suimenGet || function (k, rel) {
    return fetch("https://raw.githubusercontent.com/mikazuki07120609-beep/boatrace/" + (k === "odds" ? "odds/data/odds/" : "main/data/live/") + rel + "?t=" + Math.floor(Date.now() / 15000), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; });
  };
  var WINDOW = 15, O = null, kind = "3t", first = 1, timer = null, lastFetch = 0;
  var names = {}, fems = {};
  D.entries.forEach(function (e) { names[e.waku] = e.name; fems[e.waku] = !!e.fem; });
  function $(s) { return document.querySelector(s); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function wk(w) { return '<span class="waku w' + w + '">' + w + "</span>"; }
  function nowJst() { var t = new Date(Date.now() + 9 * 3600e3); return { iso: t.toISOString().slice(0, 10), min: t.getUTCHours() * 60 + t.getUTCMinutes() + t.getUTCSeconds() / 60 }; }
  function minsLeft() {
    var n = nowJst(), a = (D.race.deadline || "0:0").split(":"), dl = +a[0] * 60 + +a[1];
    return n.iso === D.race.date ? dl - n.min : (n.iso < D.race.date ? 1e4 : -1e4);
  }
  function fmt(v) { return v == null || !(v > 0) ? "—" : v >= 100 ? Math.round(v).toLocaleString() : v.toFixed(1); }   // 0.0(票がない)は出さない
  function move(cur, prev) {                     // ひとつ前からの変化(5%以上)
    if (cur == null || prev == null || !isFinite(cur) || !isFinite(prev) || prev <= 0 || cur <= 0) return "";
    var r = cur / prev;
    if (r <= 0.95) return '<i class="mv dn" title="' + fmt(prev) + "→" + fmt(cur) + '">↓</i>';
    if (r >= 1.05) return '<i class="mv up" title="' + fmt(prev) + "→" + fmt(cur) + '">↑</i>';
    return "";
  }
  function pane() { return document.getElementById("pane-odds"); }
  // 一番低いオッズ(1番人気)は赤、2番目は青
  function favs(vals) {
    var u = vals.filter(function (v) { return v != null && v > 0; }).sort(function (a, b) { return a - b; });
    return { a: u.length ? u[0] : null, b: u.length > 1 && u[1] > u[0] ? u[1] : null };
  }
  function favCls(v, f) { return v != null && v > 0 && v === f.a ? " fav" : v != null && v > 0 && v === f.b ? " fav2" : ""; }
  function visible() { var p = pane(); return p && !p.hidden && !document.hidden; }
  var URA = document.body.classList.contains("ura");   // 裏: オッズのタブを開いていなくても読む(人気とのずれを、万舟の見込みと裏本線に入れるため)
  function fetching() { return URA ? !document.hidden : visible(); }

  function stamp() {
    var at = $("#odAt");
    if (!at) return;
    if (!O) { at.textContent = ""; return; }
    at.textContent = O.final ? "締切時オッズ" : (O.t ? O.t + " 時点" : "") + (O.at ? "(取り込み " + O.at.slice(0, 5) + ")" : "");
  }
  function waitText() {
    var left = minsLeft();
    if (left > WINDOW) {
      var a = (D.race.deadline || "0:0").split(":"), m = +a[0] * 60 + +a[1] - WINDOW;
      return "締切の15分前(" + Math.floor(m / 60) + ":" + ("0" + (m % 60)).slice(-2) + "ごろ)から、1分ごとにオッズを表示します。";
    }
    if (left > -2) return "オッズを読み込んでいます…(締切の15分前から1分ごとに取り込んでいます)";
    return "このレースのオッズは取り込めていません。";
  }

  // ---- 表示
  function render() {
    stamp();
    if (!O) { box.innerHTML = '<p class="wait">' + esc(waitText()) + "</p>"; return; }
    var P = O.prev || {};
    if (kind === "3t") box.innerHTML = view3t(O["3t"] || {}, P["3t"] || {});
    else if (kind === "2t") box.innerHTML = view2(O["2t"] || {}, P["2t"] || {}, O["2f"] || {}, P["2f"] || {});
    else box.innerHTML = viewTf(O.tan || {}, P.tan || {}, O.fuku || {});
  }
  function view3t(T, PT) {
    var keys = Object.keys(T).filter(function (k) { return T[k] != null && T[k] > 0; }).sort(function (a, b) { return T[a] - T[b]; });
    if (!keys.length) return '<p class="wait">3連単のオッズがまだありません。</p>';
    var top = keys.slice(0, 20).map(function (k, i) {
      var c = k.split("-");
      return "<tr><td class=\"num rk\">" + (i + 1) + '</td><td class="cmb">' + wk(c[0]) + wk(c[1]) + wk(c[2]) + '</td><td class="num od' + (i === 0 ? " fav" : i === 1 && T[k] > T[keys[0]] ? " fav2" : "") + '">' + fmt(T[k]) + move(T[k], PT[k]) + "</td></tr>";
    }).join("");
    var heads = [1, 2, 3, 4, 5, 6].map(function (w) { return '<button type="button" class="chip' + (w === first ? " on" : "") + '" data-first="' + w + '">' + wk(w) + "</button>"; }).join("");
    // 1着を決めた3連単の表(行が2着、列が3着)。この表の中で一番低いオッズは赤、2番目は青
    var others = [1, 2, 3, 4, 5, 6].filter(function (b) { return b !== first; });
    var fv = favs([].concat.apply([], others.map(function (b) { return others.filter(function (c) { return c !== b; }).map(function (c) { return T[first + "-" + b + "-" + c]; }); })));
    var g3 = '<div class="scroll"><table class="odm g3t" aria-label="1着が' + first + '号艇の3連単(行が2着・列が3着)"><thead><tr><th class="g3h"><span class="g3k">' + wk(first) + '1着</span><span class="g3x">2着＼3着</span></th>' +
      others.map(function (c) { return "<th>" + wk(c) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      others.map(function (b) {
        return "<tr><th>" + wk(b) + "</th>" + others.map(function (c) {
          if (c === b) return '<td class="off"></td>';
          var k = first + "-" + b + "-" + c, v = T[k];
          return '<td class="num' + favCls(v, fv) + '">' + fmt(v) + move(v, PT[k]) + "</td>";
        }).join("") + "</tr>";
      }).join("") + "</tbody></table></div>";
    return '<div class="odsub">人気順(オッズの低い順)</div><div class="scroll"><table class="odt"><thead><tr><th class="num">人気</th><th>組</th><th class="num">オッズ</th></tr></thead><tbody>' + top + "</tbody></table></div>" +
      '<div class="odsub">1着から見る</div><div class="chips odfirst">' + heads + "</div>" + g3;
  }
  function matrix(T, PT, sep, tri) {
    var fv = favs(Object.keys(T).map(function (k) { return T[k]; }));
    var head = '<tr><th></th>' + [1, 2, 3, 4, 5, 6].map(function (w) { return "<th>" + wk(w) + "</th>"; }).join("") + "</tr>";
    var rows = [1, 2, 3, 4, 5, 6].map(function (a) {
      return "<tr><th>" + wk(a) + "</th>" + [1, 2, 3, 4, 5, 6].map(function (b) {
        if (a === b || (tri && b < a)) return '<td class="off"></td>';
        var k = a + sep + b, v = T[k];
        return '<td class="num' + favCls(v, fv) + '">' + fmt(v) + move(v, PT[k]) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return '<div class="scroll"><table class="odm"><thead>' + head + "</thead><tbody>" + rows + "</tbody></table></div>";
  }
  function view2(T, PT, F, PF) {
    return '<div class="odsub">2連単(行が1着・列が2着)</div>' + matrix(T, PT, "-", false) +
      '<div class="odsub">2連複</div>' + matrix(F, PF, "=", true);
  }
  function viewTf(T, PT, F) {
    var fv = favs([1, 2, 3, 4, 5, 6].map(function (w) { return T[w]; }));
    return '<div class="scroll"><table class="odt odtf"><thead><tr><th>艇</th><th>選手</th><th class="num">単勝</th><th class="num">複勝</th></tr></thead><tbody>' +
      [1, 2, 3, 4, 5, 6].map(function (w) {
        var f = F[w];
        return "<tr><td>" + wk(w) + "</td><td>" + esc(names[w] || "") + (fems[w] ? '<span class="fem">♥</span>' : "") + '</td><td class="num od' + favCls(T[w], fv) + '">' + fmt(T[w]) + move(T[w], PT[w]) +
          '</td><td class="num">' + (f && f[1] > 0 ? fmt(f[0]) + "〜" + fmt(f[1]) : "—") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  // ---- 読み込み(締切の15分前から。締切時オッズが入ったら止める)
  function load() {
    lastFetch = Date.now();
    return getData("odds", REL)
      .then(function (j) {
        if (j && j.dl && /^\d{1,2}:\d{2}$/.test(j.dl)) D.race.deadline = j.dl;          // 公式の今の締切(レースが遅れると変わる)
        if (j && (!O || JSON.stringify(j) !== JSON.stringify(O))) {
          O = j; render();
          try { document.dispatchEvent(new CustomEvent("suimen:odds", { detail: O })); } catch (e) {}
        } else if (!O) render();
      })
      .catch(function () { if (!O) render(); });
  }
  function want() {                                   // 読みに行く時間帯か
    var left = minsLeft();
    return left <= WINDOW + 0.5 && left > -60 && !(O && O.final);
  }
  function tick() {
    clearTimeout(timer);
    if (fetching() && want() && Date.now() - lastFetch >= 25000) load();
    else if (visible() && !O) render();
    timer = setTimeout(tick, 5000);
  }
  // タブを開いたとき・画面に戻ったときは、すぐ読み直す
  document.addEventListener("click", function (e) {
    var t = e.target.closest(".tabs [data-tab]");
    if (t && t.getAttribute("data-tab") === "odds") setTimeout(function () { if (want() || !O) load(); else render(); }, 30);
    var k = e.target.closest("#odKinds [data-k]");
    if (k) {
      kind = k.getAttribute("data-k");
      [].slice.call(document.querySelectorAll("#odKinds [data-k]")).forEach(function (b) { b.classList.toggle("on", b === k); });
      render();
    }
    var f = e.target.closest("#odBox [data-first]");
    if (f) { first = +f.getAttribute("data-first"); render(); }
  });
  document.addEventListener("visibilitychange", function () { if (fetching() && want()) load(); });
  document.addEventListener("suimen:deadline", function (e) { if (e.detail) { D.race.deadline = e.detail; if (!O) render(); } });   // race.js が読んだ公式の締切
  if (visible() || (URA && (want() || minsLeft() < -1))) load(); else render();   // 裏: 締切のあとに開いたときも、締切時オッズを1回読む
  tick();
})();
