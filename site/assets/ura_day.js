/* 裏水面ノートの今日のレース: 直前の荒れ(展示のあとの万舟の見込み・ura.json)と、今日の万舟(結果)を読み直して出す。
   大荒れ注意になったレースは、このページを開いている間だけ通知もできる(ブラウザの通知を許可したとき)。 */
(function () {
  "use strict";
  var el = document.getElementById("ura-day");
  if (!el) return;
  var C = JSON.parse(el.textContent);
  var getLive = window.suimenGet ? function (rel) { return window.suimenGet("live", rel); } : function (rel) {
    return fetch("https://raw.githubusercontent.com/mikazuki07120609-beep/boatrace/main/data/live/" + rel + "?t=" + Math.floor(Date.now() / 15000), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; });
  };
  function $(s) { return document.querySelector(s); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function wk(w) { return '<span class="waku w' + w + '">' + w + "</span>"; }
  function nowJst() { var t = new Date(Date.now() + 9 * 3600e3); return { iso: t.toISOString().slice(0, 10), min: t.getUTCHours() * 60 + t.getUTCMinutes() }; }
  function toMin(hm) { var a = String(hm || "0:0").split(":"); return +a[0] * 60 + +a[1]; }
  function href(k) { var p = k.split("-"); return C.pfx + C.ymd + "/" + p[0] + "/" + ("0" + p[1]).slice(-2) + ".html"; }
  function rname(k) { var p = k.split("-"); return (C.vn[p[0]] || p[0]) + " " + p[1] + "R"; }
  var LV = { "大荒れ注意": "L3", "荒れ気味": "L2", "ふつう": "L1", "平穏": "L0" };
  var U = null;

  // ---- 直前の荒れ(展示のあとで荒れ気味以上になった、これからのレース)
  function renderLive() {
    var box = $("#uraLive"), strip = $("#uraStrip");
    if (!box || !U) return;
    var n = nowJst(), today = n.iso === C.date;
    var rows = Object.keys(U.races || {}).map(function (k) { return { k: k, x: U.races[k], dl: C.dl[k] }; })
      .filter(function (r) { return (r.x.lv === "大荒れ注意" || r.x.lv === "荒れ気味") && (!today || !r.dl || toMin(r.dl) > n.min); })
      .sort(function (a, b) { return toMin(a.dl) - toMin(b.dl); });
    var at = $("#uraLiveAt");
    if (at && U.updated) at.textContent = U.updated + " 時点(展示のあとで計算し直した万舟の見込み)";
    box.innerHTML = rows.length ? '<div class="scroll"><table class="race-list ulist"><thead><tr><th>レース</th><th class="num">締切</th><th>荒れの見込み<small class="th2">展示のあと</small></th></tr></thead><tbody>' +
      rows.map(function (r) {
        var x = r.x, ul = x.ul;
        return '<tr><td><a class="rno" href="' + href(r.k) + '">' + esc(rname(r.k)) + '</a></td><td class="num"><span class="dl">' + esc(r.dl || "") + "</span></td>" +
          '<td class="uman"><span class="ubox"><b class="upct">' + Math.round(x.pm * 100) + '<small>%</small></b><span class="ulv ' + (LV[x.lv] || "L1") + '">' + esc(x.lv) + "</span></span>" +
          (ul ? '<span class="uln">' + wk(ul[0]) + '<span class="uline">' + ul[1] + "コース <span class=\"nw\">" + esc(ul[2]) + "</span></span></span>" : "") + "</td></tr>";
      }).join("") + "</tbody></table></div>"
      : '<p class="sub">' + (today ? "いまのところ、展示のあとで荒れ気味以上になったこれからのレースはありません。" : "この日の展示のあとの計算はありません。") + "</p>";
    var hot = rows.filter(function (r) { return r.x.lv === "大荒れ注意"; });
    if (strip) {
      strip.hidden = !hot.length;
      strip.innerHTML = hot.length ? '<span class="ust-k">直前で大荒れ注意</span>' + hot.slice(0, 4).map(function (r) {
        return '<a href="' + href(r.k) + '">' + esc(rname(r.k)) + " <small>" + esc(r.dl || "") + "</small></a>";
      }).join("") : "";
    }
    notify(hot);
  }

  // ---- 通知(このページを開いている間だけ。許可は端末ごと)
  var NKEY = "suimen.ura.notify", SKEY = "suimen.ura.notified." + C.ymd, seen = {};
  try { (JSON.parse(localStorage.getItem(SKEY) || "[]") || []).forEach(function (k) { seen[k] = 1; }); } catch (e) {}
  function notifyOn() { try { return "Notification" in window && Notification.permission === "granted" && localStorage.getItem(NKEY) === "1"; } catch (e) { return false; } }
  function paintBtn() {
    var b = $("#uraNotify");
    if (!b) return;
    if (!("Notification" in window)) { b.disabled = true; b.textContent = "この端末では通知を使えません"; return; }
    var on = notifyOn();
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.classList.toggle("on", on);
    b.textContent = on ? "大荒れ注意を通知中(押すと止める)" : "大荒れ注意を通知する";
  }
  function notify(hot) {
    var fresh = hot.filter(function (r) { return !seen[r.k]; });
    if (!fresh.length) return;
    fresh.forEach(function (r) { seen[r.k] = 1; });
    try { localStorage.setItem(SKEY, JSON.stringify(Object.keys(seen))); } catch (e) {}
    if (!notifyOn()) return;
    fresh.slice(0, 3).forEach(function (r) {
      try {
        var x = r.x, ul = x.ul;
        var nt = new Notification("大荒れ注意 " + rname(r.k) + (r.dl ? "(" + r.dl + "締切)" : ""), {
          body: "万舟の見込み " + Math.round(x.pm * 100) + "%" + (ul ? "・裏本線 " + ul[1] + "コース" + ul[2] : ""), tag: "ura-" + C.ymd + "-" + r.k });
        nt.onclick = function () { window.focus(); location.href = href(r.k); };
      } catch (e) {}
    });
  }
  function setupNotify() {
    var b = $("#uraNotify");
    if (!b) return;
    paintBtn();
    b.addEventListener("click", function () {
      if (!("Notification" in window)) return;
      if (notifyOn()) { try { localStorage.setItem(NKEY, "0"); } catch (e) {} paintBtn(); return; }
      var go = function (p) { if (p === "granted") { try { localStorage.setItem(NKEY, "1"); } catch (e) {} } paintBtn(); };
      try {
        var r = Notification.requestPermission(go);
        if (r && r.then) r.then(go);
      } catch (e) { paintBtn(); }
    });
  }

  // ---- 今日の万舟(結果。締切前の裏本線が当たったかも)
  function renderMan(list) {
    var box = $("#uraMan");
    if (!box) return;
    if (!list.length) { box.innerHTML = '<p class="sub">まだ万舟はありません。</p>'; return; }
    list.sort(function (a, b) { return toMin(b.dl) - toMin(a.dl); });
    box.innerHTML = '<div class="scroll"><table class="race-list ulist"><thead><tr><th>レース</th><th>結果</th><th>展示のあとの裏本線</th></tr></thead><tbody>' +
      list.map(function (m) {
        var ul = U && U.races && U.races[m.k] ? U.races[m.k].ul : null, hit = "";
        if (ul) hit = ul[1] === m.wc && ul[2] === m.kim ? '<span class="uhit">当たり</span>' : ul[1] === m.wc ? '<span class="uhit2">艇は当たり</span>' : '<span class="dim">外れ</span>';
        return '<tr><td><a class="rno" href="' + href(m.k) + '">' + esc(rname(m.k)) + '</a><span class="small">' + esc(m.dl || "") + "</span></td>" +
          '<td class="res"><span class="tri small-tri">' + m.tri.map(wk).join("-") + '</span><span class="small">' + Number(m.pay).toLocaleString() + "円" +
          (m.pop ? "・" + m.pop + "番人気" : "") + '</span><span class="small">1着 ' + (m.wc ? m.wc + "コース " : "") + esc(m.kim || "") + "</span></td>" +
          '<td class="uln2">' + (ul ? wk(ul[0]) + " " + ul[1] + "コース" + esc(ul[2]) + "<br>" + hit : '<span class="dim">—</span>') + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<p class="note">展示のあとの裏本線は、スタート展示のあとに記録した裏本線です(レースのページでは、そのあとのオッズも入れて計算し直します)。</p>';
  }
  function loadMan() {
    var codes = Object.keys(C.vn), left = codes.length, list = [];
    if (!left) return;
    codes.forEach(function (c) {
      getLive(C.ymd + "/" + c + ".json").then(function (j) {
        var res = (j && j.result) || {};
        Object.keys(res).forEach(function (no) {
          var x = res[no];
          if (!x || !(x.pay >= 10000) || !x.tri || x.tri.length !== 3) return;
          var cw = x.course && x.course.length === 6 ? x.course : null;
          list.push({ k: c + "-" + no, tri: x.tri, pay: x.pay, pop: x.pop, kim: x.kimarite, wc: cw ? cw.indexOf(x.tri[0]) + 1 : null, dl: C.dl[c + "-" + no] });
        });
      }).catch(function () {}).then(function () { if (--left === 0) renderMan(list); });
    });
  }

  function load() {
    getLive(C.ymd + "/ura.json").then(function (j) { if (j) { U = j; renderLive(); } loadMan(); })
      .catch(function () { loadMan(); });
  }
  setupNotify();
  load();
  // 開いている間は1分ごとに読み直す(通知をオンにしているときは、ほかのタブを見ている間も)
  setInterval(function () { if ((!document.hidden || notifyOn()) && nowJst().iso === C.date) load(); }, 60000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden && nowJst().iso === C.date) load(); });
})();
