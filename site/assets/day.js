/* 開催場の一覧: 次のレースの締切が近い順に並べ替え、「10R 10分前」のように出す(10分を切ったら赤)。
   レース一覧: 次のレースに印を付け、締切までの時間を出す。時刻はこの端末の時計(日本時間に直して)で数える。 */
(function () {
  "use strict";
  function nowJst() {                                  // 日本時間の「日付」と「0時からの分」
    var t = new Date(Date.now() + 9 * 3600e3);
    return { iso: t.toISOString().slice(0, 10), min: t.getUTCHours() * 60 + t.getUTCMinutes() + t.getUTCSeconds() / 60 };
  }
  function toMin(hm) { var a = hm.split(":"); return +a[0] * 60 + +a[1]; }
  function label(left) {
    if (left < 1) return "まもなく締切";
    if (left < 60) return Math.floor(left) + "分前";
    return Math.floor(left / 60) + "時間" + (Math.floor(left) % 60) + "分前";
  }
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
  function tick() { cards(); raceList(); }
  tick();
  setInterval(tick, 30000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) tick(); });
})();
