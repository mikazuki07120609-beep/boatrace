/* 開催場の一覧: 次のレースの締切が近い順に並べ替え、「10R 10分前」のように出す(10分を切ったら赤)。
   レース一覧: 次のレースに印を付け、締切までの時間を出す。時刻はこの端末の時計(日本時間に直して)で数える。 */
(function () {
  "use strict";
  function nowJst() {                                  // 日本時間の「日付」と「0時からの分」
    var t = new Date(Date.now() + 9 * 3600e3);
    return { iso: t.toISOString().slice(0, 10), min: t.getUTCHours() * 60 + t.getUTCMinutes() + t.getUTCSeconds() / 60 };
  }
  function toMin(hm) { var a = hm.split(":"); return +a[0] * 60 + +a[1]; }
  var URA = document.body.classList.contains("ura");   // 裏水面ノートの一覧(結果の万舟に印)
  // 取り込んだ直前情報・結果・締切の変更の読み込み(ページの頭の suimenGet: 先に Cloudflare、だめなら GitHub)。
  // data-live などに URL がそのまま入った古いページや、suimenGet のない古いページと組み合わさったときは、GitHub を直接読む
  function getLive(rel) {
    var t = "?t=" + Math.floor(Date.now() / 15000);
    if (window.suimenGet && !/^https?:/.test(rel)) return window.suimenGet("live", rel);
    var u = /^https?:/.test(rel) ? rel : "https://raw.githubusercontent.com/mikazuki07120609-beep/boatrace/main/data/live/" + rel;
    return fetch(u + t, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; });
  }
  function label(left) {
    if (left < 1) return "まもなく締切";
    if (left < 60) return Math.floor(left) + "分前";
    return Math.floor(left / 60) + "時間" + (Math.floor(left) % 60) + "分前";
  }
  var AL_NAME = { "in": "イン飛び", "kado": "カドまくり" }, AL_LV = { 3: "特別警報", 2: "警報", 1: "注意報" };
  function cards() {
    var box = document.querySelector(".cards[data-date]");
    if (!box) return;
    var now = nowJst(), day = box.getAttribute("data-date"), list = [].slice.call(box.querySelectorAll(".vcard"));
    list.forEach(function (c) {
      var races = (c.getAttribute("data-dl") || "").split(",").filter(Boolean).map(function (x) { var p = x.split("-"); return { no: +p[0], m: toMin(p[1]) }; });
      var nx = null, left = null, el = c.querySelector(".next");
      if (day === now.iso) {
        for (var i = 0; i < races.length; i++) if (races[i].m > now.min) { nx = races[i]; break; }
        left = nx ? nx.m - now.min : null;
      } else if (day > now.iso && races.length) { nx = races[0]; }
      c.classList.toggle("soon", left != null && left <= 10);
      c.classList.toggle("done", day === now.iso && !nx);
      if (el) el.textContent = day === now.iso ? (nx ? nx.no + "R " + label(left) : "本日の発売は終了") : (nx ? nx.no + "R から" : "");
      // 次のレースの警戒アラートを、場の名前の横に出す
      var box = c.querySelector(".als"), als = (c.getAttribute("data-al") || "").split(",").filter(Boolean).map(function (x) {
        var p = x.split(":"); return { no: +p[0], k: p[1].replace(/\d$/, ""), lv: +p[1].slice(-1) };
      });
      if (box) box.innerHTML = nx ? als.filter(function (a) { return a.no === nx.no; }).map(function (a) {
        return '<span class="al al-' + a.k + a.lv + '">' + AL_NAME[a.k] + " " + AL_LV[a.lv] + "</span>";
      }).join("") : "";
      c._key = day === now.iso ? (nx ? nx.m : 1e6 + (races.length ? races[races.length - 1].m : 0)) : (races.length ? races[0].m : 1e6);
    });
    list.sort(function (a, b) { return a._key - b._key; }).forEach(function (c) { box.appendChild(c); });
  }
  function raceList() {
    var tbl = document.querySelector(".race-list[data-date]");
    if (!tbl) return;
    var now = nowJst(), day = tbl.getAttribute("data-date"), found = false;
    [].slice.call(tbl.querySelectorAll("tr[data-deadline]")).forEach(function (tr) {
      var left = day === now.iso ? toMin(tr.getAttribute("data-deadline")) - now.min : null, cd = tr.querySelector(".cd");
      var isNext = left != null && left > 0 && !found;
      if (isNext) found = true;
      tr.classList.toggle("next", isNext);
      tr.classList.toggle("soon", isNext && left <= 10);
      if (cd) cd.textContent = isNext ? label(left) : "";
    });
  }
  // レース一覧の結果: ページを作ったあとに出た結果は、取り込んだ結果(data/live)を読みに行って埋める
  var resBusy = false;
  function fillResults() {
    var tbl = document.querySelector(".race-list[data-live]");
    if (!tbl || resBusy) return;
    var now = nowJst(), day = tbl.getAttribute("data-date");
    if (day > now.iso) return;
    var want = [].slice.call(tbl.querySelectorAll("tr[data-deadline]")).filter(function (tr) {
      var cell = tr.querySelector(".res");
      return cell && !cell.textContent.trim() && (day < now.iso || toMin(tr.getAttribute("data-deadline")) - now.min < -3);
    });
    if (!want.length) return;
    resBusy = true;
    getLive(tbl.getAttribute("data-live"))
      .then(function (j) {
        var res = (j && j.result) || {};
        want.forEach(function (tr) {
          var x = res[tr.getAttribute("data-no")], cell = tr.querySelector(".res");
          if (!x || !cell) return;
          var tri = x.tri && x.tri.length === 3 ? x.tri : null;
          if (!tri) {                                                   // 3連単がない(返還など)ときは着順から
            var fin = (x.order || []).filter(function (y) { return y.rank; }).sort(function (a, b) { return a.rank - b.rank; });
            if (fin.length >= 3) tri = fin.slice(0, 3).map(function (y) { return y.waku; });
          }
          if (!tri) return;
          cell.innerHTML = '<span class="tri small-tri">' + tri.map(function (w) { return '<span class="waku w' + w + '">' + w + "</span>"; }).join("-") + "</span>"
            + (x.pay ? '<span class="small">' + (x.pay / 100).toFixed(1) + "倍</span>" : "")
            + (URA && x.pay >= 10000 ? '<span class="uman-tag sm">万舟</span>' : "");
        });
      })
      .catch(function () {})
      .then(function () { resBusy = false; });
  }
  // 公式の締切が変わったレース(遅れ): 取り込んだ dl.json を読んで、カードとレース一覧の締切を合わせ直す(今日のページだけ、1分ごと)
  var dlBusy = false, dlAt = 0;
  function syncDeadlines() {
    var el = document.querySelector("[data-dlurl]");
    if (!el || dlBusy || Date.now() - dlAt < 55000) return;
    if (el.getAttribute("data-date") !== nowJst().iso) return;
    dlBusy = true; dlAt = Date.now();
    getLive(el.getAttribute("data-dlurl"))
      .then(function (j) {
        var M = (j && j.dl) || {}, moved = false;
        [].slice.call(document.querySelectorAll(".vcard[data-code]")).forEach(function (c) {
          var m = M[c.getAttribute("data-code")];
          if (!m) return;
          var nv = (c.getAttribute("data-dl") || "").split(",").filter(Boolean).map(function (x) { var p = x.split("-"); return p[0] + "-" + (m[p[0]] || p[1]); }).join(",");
          if (nv !== c.getAttribute("data-dl")) { c.setAttribute("data-dl", nv); moved = true; }
        });
        var tbl = document.querySelector(".race-list[data-code]"), m2 = tbl ? M[tbl.getAttribute("data-code")] : null;
        if (m2) [].slice.call(tbl.querySelectorAll("tr[data-deadline]")).forEach(function (tr) {
          var nd = m2[tr.getAttribute("data-no")], sp = tr.querySelector(".dl");
          if (!nd || nd === tr.getAttribute("data-deadline")) return;
          tr.setAttribute("data-deadline", nd); moved = true;
          if (sp) { sp.textContent = nd; sp.classList.add("moved"); sp.title = "レースが遅れたため、公式の締切が変わりました"; }
        });
        if (moved) { cards(); raceList(); }
      })
      .catch(function () {})
      .then(function () { dlBusy = false; });
  }
  function tick() { cards(); raceList(); fillResults(); syncDeadlines(); }
  tick();
  setInterval(tick, 30000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) tick(); });
})();
