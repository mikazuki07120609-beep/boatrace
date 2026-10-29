/* レース検索: {ymd}/search.json(出走表・警報・モーター評価・見立て・今節成績)と、取り込んだ直前情報・結果(data/live)から、
   条件に当てはまるレースを探す。時刻はこの端末の時計を日本時間に直して数える。 */
(function () {
  "use strict";
  // 直前情報・結果の読み込み(ページの頭の suimenGet: 先に Cloudflare、だめなら GitHub)。古いページと組み合わさったときは GitHub だけ
  var getData = window.suimenGet || function (k, rel) {
    return fetch("https://raw.githubusercontent.com/mikazuki07120609-beep/boatrace/" + (k === "odds" ? "odds/data/odds/" : "main/data/live/") + rel + "?t=" + Math.floor(Date.now() / 15000), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; });
  };
  var AL_LV = { 3: "特別警報", 2: "警報", 1: "注意報" };
  var PTS = { 1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1 };
  var S = null, LIVE = {}, BORDER = {}, SPAN = {}, spanTried = false, liveTimer = null, loadSeq = 0;
  var ON = {};                                        // 選んでいる条件
  function $(s) { return document.querySelector(s); }
  function $$(s) { return [].slice.call(document.querySelectorAll(s)); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function nowJst() { var t = new Date(Date.now() + 9 * 3600e3); return { iso: t.toISOString().slice(0, 10), min: t.getUTCHours() * 60 + t.getUTCMinutes() }; }
  function toMin(hm) { var a = (hm || "0:0").split(":"); return +a[0] * 60 + +a[1]; }
  function waku(w) { return '<span class="waku w' + w + '">' + w + "</span>"; }
  function liveOf(r) { return LIVE[r.c] || {}; }
  function rawBefore(r) { return (liveOf(r).before || {})[String(r.no)] || null; }
  function beforeOf(r) { var b = rawBefore(r); return b && b.ready ? b : null; }
  function resultOf(r) { return (liveOf(r).result || {})[String(r.no)] || null; }
  function isToday() { return !!S && S.date === nowJst().iso; }
  function finished(r) {
    if (resultOf(r)) return true;
    if (!S) return false;
    var n = nowJst();
    return S.date < n.iso || (S.date === n.iso && toMin(r.dl) <= n.min);
  }

  // ---- 準優の勝負駆け: 今節の着順(番組表の今節成績+今日すでに終わったレース)を点数にした得点率で、18位をボーダーの目安にする
  function seriesPoints(marks) {
    var pts = 0, n = 0;
    marks.forEach(function (d) {
      String(d || "").split("").forEach(function (ch) {
        if (PTS[ch]) { pts += PTS[ch]; n++; }
        else if ("SFL".indexOf(ch) >= 0) n++;           // 失格・フライング・出遅れは0点で1走(欠場は数えない)
      });
    });
    return [pts, n];
  }
  function todayMarks(code) {
    var res = (LIVE[code] || {}).result || {}, out = {};
    Object.keys(res).map(Number).sort(function (a, b) { return a - b; }).forEach(function (no) {
      (res[String(no)].order || []).forEach(function (o) {
        var st = o.status || "";
        var ch = o.rank ? String(o.rank) : st.indexOf("F") >= 0 ? "F" : st.indexOf("L") >= 0 ? "L" : st.indexOf("欠") >= 0 ? "K" : st ? "S" : "";
        if (ch) out[o.toban] = (out[o.toban] || "") + ch;
      });
    });
    return out;
  }
  function dayDiff(a, b) { return Math.round((Date.parse(b) - Date.parse(a)) / 864e5); }
  function computeBorders() {
    BORDER = {};
    if (!S) return;
    Object.keys(S.venues || {}).forEach(function (code) {
      var V = S.venues[code];
      if (V.phase !== "yosen" || !V.day || V.day < 2) return;
      // 予選の最終日か: 明日の番組に準優があるか。明日の番組がまだなら、節の最終日の2日前か(公式ページの日付の並びから)。
      // どちらも分からなければ、3日目以降を候補にする
      var last = V.last, sp = SPAN[code];
      if (last == null && sp && sp.first && sp.last && dayDiff(sp.first, S.date) + 1 === V.day) last = dayDiff(S.date, sp.last) === 2;
      if (!(last === true || (last == null && V.day >= 3))) return;
      var tm = isToday() ? todayMarks(code) : {}, rows = [], left = {};
      (S.races || []).forEach(function (r) {
        if (r.c === code && !finished(r)) r.e.forEach(function (e) { left[e.t] = (left[e.t] || 0) + 1; });
      });
      Object.keys(V.roster || {}).forEach(function (t) {
        var p = seriesPoints((V.roster[t].s || []).concat([tm[t] || ""]));
        if (p[1]) rows.push({ t: t, pts: p[0], n: p[1], rate: p[0] / p[1], left: left[t] || 0 });
      });
      if (rows.length < 18) return;
      rows.sort(function (a, b) { return b.rate - a.rate; });
      rows.forEach(function (x) { x.rank = 1 + rows.filter(function (y) { return y.rate > x.rate + 1e-9; }).length; });
      var line = rows[17].rate, near = {};
      rows.forEach(function (x) {
        if (!x.left) return;
        if (x.left === 1) {                               // 残り1走: この1走の着順でボーダーの目安を越えるかが変わる選手
          var need = null;
          for (var k = 6; k >= 1; k--) if ((x.pts + PTS[k]) / (x.n + 1) >= line - 1e-9) { need = k; break; }
          if (need != null && need < 6) { x.need = need; near[x.t] = x; }
        } else if ((x.rank >= 12 && x.rank <= 24) || Math.abs(x.rate - line) <= 0.8) near[x.t] = x;
      });
      BORDER[code] = { line: line, near: near, total: rows.length, last: last, day: V.day };
    });
  }

  // ---- モーター評価(展示タイムが4艇以上そろったら、レースの平均との差を加える。レースのページと同じ式)
  function motorGrades(r) {
    var bi = rawBefore(r);
    var ex = r.e.map(function (e) { var x = bi && bi.ex ? bi.ex[String(e.w)] : null; return x == null || !isFinite(x) ? null : x; });
    var ok = ex.filter(function (x) { return x != null && x > 6 && x < 7.6; });
    var m = ok.length >= 4 ? ok.reduce(function (s, x) { return s + x; }, 0) / ok.length : null;
    return r.e.map(function (e, i) {
      if (e.z == null) return e.g || null;
      var z = e.z;
      if (m != null && ex[i] != null) { var zt = Math.max(-3, Math.min(3, (m - ex[i]) / 0.047)); z = (0.55 * z + 0.45 * zt) / Math.sqrt(0.55 * 0.55 + 0.45 * 0.45); }
      if (e.sp && z >= 0.65) return "S+";                                   // 全国で飛び抜けたモーター(展示で大きく崩れていなければ)
      return z >= 1.4 ? "S" : z >= 0.65 ? "A" : z >= 0 ? "B" : z >= -0.65 ? "C" : z >= -1.4 ? "D" : "E";
    });
  }
  function exBest(r) {
    var bi = beforeOf(r); if (!bi || !bi.ex) return null;
    var best = null;
    r.e.forEach(function (e) { var x = bi.ex[String(e.w)]; if (x != null && x > 6 && x < 7.6 && (!best || x < best.x)) best = { w: e.w, x: x }; });
    return best;
  }
  function nigeText(r) { return "1号艇の逃げ " + Math.round(r.p1 * 100) + "%" + (r.pre ? "(展示前の見立て)" : ""); }

  // ---- 条件。test(r) は、当てはまれば理由(HTML)の配列、当てはまらなければ null。live は直前情報を使うもの
  var GROUPS = [
    ["警報・見立て", [
      { id: "in", label: "イン飛び警報", test: function (r) {
        var lv = (r.al || {})["in"]; return lv ? ['<span class="al al-in' + lv + ' sm">イン飛び ' + AL_LV[lv] + "</span>"] : null; } },
      { id: "kado", label: "カドまくり警報", test: function (r) {
        var lv = (r.al || {}).kado; return lv ? ['<span class="al al-kado' + lv + ' sm">カドまくり ' + AL_LV[lv] + "</span>"] : null; } },
      { id: "nigeHigh", label: "逃げが堅い(60%以上)", test: function (r) { return r.p1 != null && r.p1 >= 0.6 ? [nigeText(r)] : null; } },
      { id: "nigeLow", label: "逃げが危ない(40%以下)", test: function (r) {
        if (r.p1 == null || r.p1 > 0.4) return null;
        var t = r.lead && r.lead[1] !== 1 ? "本線は" + r.lead[0] + "号艇の" + r.lead[2] + "(1着の見込み" + Math.round(r.lead[3] * 100) + "%)" :
          r.top && r.top[0] && r.top[0][2] !== "逃げ" ? "本線は" + r.top[0][0] + "号艇の" + r.top[0][2] + " " + Math.round(r.top[0][3] * 100) + "%" : "";
        return [nigeText(r)].concat(t ? [t] : []); } },
      { id: "leadOut", label: "本線が1号艇以外", test: function (r) {
        if (!r.lead || r.lead[1] === 1) return null;
        return [waku(r.lead[0]) + " " + r.lead[1] + "コースの" + esc(r.lead[2]) + "(1着の見込み" + Math.round(r.lead[3] * 100) + "%・1コースは" + Math.round(r.lead[4] * 100) + "%)" +
          (r.pre ? '<span class="dim">(展示前の見立て)</span>' : "")]; } }
    ]],
    ["選手・節間", [
      { id: "junyu", label: "準優の勝負駆け", test: function (r) {
        var B = BORDER[r.c]; if (!B || finished(r)) return null;
        var hits = r.e.filter(function (e) { return B.near[e.t]; });
        if (!hits.length) return null;
        return hits.map(function (e) { var x = B.near[e.t];
          return waku(e.w) + " " + esc(e.n) + (e.fm ? '<span class="fem">♥</span>' : "") + ' <span class="dim">得点率' + x.rate.toFixed(2) + "・" + x.rank + "位</span> " +
            (x.need ? "<b>" + x.need + "着以内</b>でボーダー(目安)" : (isToday() ? "今日あと" : "明日") + x.left + "走"); })
          .concat(['<span class="dim">' + (B.last ? "予選最終日" : "予選" + B.day + "日目") + "・18位の得点率 " + B.line.toFixed(2) + "(" + B.total + "人中)</span>"]); } },
      { id: "main", label: "優勝戦・準優・ドリーム", test: function (r) { return /優勝|準優|ドリーム/.test(r.nm || "") ? [esc(r.nm)] : null; } },
      { id: "b1", label: "1号艇がB級", test: function (r) {
        var e = r.e.filter(function (x) { return x.w === 1; })[0]; return e && /^B/.test(e.k || "") ? [waku(1) + " " + esc(e.n) + (e.fm ? '<span class="fem">♥</span>' : "") + " " + esc(e.k)] : null; } },
      { id: "a1out", label: "4〜6号艇にA1級", test: function (r) {
        var hit = r.e.filter(function (e) { return e.w >= 4 && e.k === "A1"; });
        return hit.length ? hit.map(function (e) { return waku(e.w) + " " + esc(e.n) + (e.fm ? '<span class="fem">♥</span>' : "") + " A1"; }) : null; } },
      { id: "fhold", label: "F持ちがいる", test: function (r) {
        var hit = r.e.filter(function (e) { return e.f > 0; });
        return hit.length ? hit.map(function (e) { return waku(e.w) + " " + esc(e.n) + (e.fm ? '<span class="fem">♥</span>' : "") + ' <span class="fon">F' + e.f + "</span>"; }) : null; } }
    ]],
    ["モーター・直前情報", [
      { id: "motorS", label: "モーター評価S以上", test: function (r) {
        var g = motorGrades(r), hit = r.e.map(function (e, i) { return [e, g[i]]; }).filter(function (x) { return x[1] === "S" || x[1] === "S+"; });
        return hit.length ? hit.map(function (x) { return waku(x[0].w) + ' <b class="g ' + (x[1] === "S+" ? "gSp" : "gS") + '">' + x[1] + "</b>"; }) : null; } },
      { id: "tilt", label: "チルトを跳ねた選手", live: true, test: function (r) {
        var bi = beforeOf(r); if (!bi || !bi.tilt) return null;
        var hit = r.e.filter(function (e) { var v = bi.tilt[String(e.w)]; return v != null && v >= 0.5; });
        return hit.length ? hit.map(function (e) { return waku(e.w) + " " + esc(e.n) + (e.fm ? '<span class="fem">♥</span>' : "") + " チルト+" + bi.tilt[String(e.w)].toFixed(1); }) : null; } },
      { id: "shinnyu", label: "前づけ・進入が動いた", live: true, test: function (r) {
        var bi = beforeOf(r); if (!bi || !bi.course || bi.course.length !== 6) return null;
        var moved = bi.course.some(function (w, i) { return w !== i + 1; });
        if (!moved) return null;
        var mz = bi.course.some(function (w, i) { return w > i + 1 && w >= 3; });
        return ["展示の進入 " + bi.course.join("") + (mz ? "(前づけ)" : "")]; } },
      { id: "exOuter", label: "展示タイム1位が4〜6号艇", live: true, test: function (r) {
        var b = exBest(r); return b && b.w >= 4 ? [waku(b.w) + " 展示1位 " + b.x.toFixed(2)] : null; } },
      { id: "parts", label: "部品・プロペラ交換", live: true, test: function (r) {
        var bi = beforeOf(r); if (!bi) return null;
        var hit = r.e.map(function (e) {
          var w = String(e.w), p = ((bi.parts || {})[w] || []).slice();
          if ((bi.prop || {})[w]) p.push("プロペラ" + bi.prop[w]);
          return { e: e, p: p };
        }).filter(function (x) { return x.p.length; });
        return hit.length ? hit.map(function (x) { return waku(x.e.w) + " " + esc(x.p.join(" ")); }) : null; } },
      { id: "wind", label: "風が強い(5m以上)", live: true, test: function (r) {
        var bi = beforeOf(r), w = bi && bi.weather ? bi.weather.wind : null; return w != null && w >= 5 ? ["風速" + w + "m"] : null; } }
    ]]
  ];
  var CONDS = [];
  GROUPS.forEach(function (g) { CONDS = CONDS.concat(g[1]); });

  function active() { return CONDS.filter(function (c) { return ON[c.id] && (!c.live || isToday()); }); }
  function nameQuery() { return ($("#sName").value || "").replace(/[\s　]/g, ""); }
  function render() {
    var list = $("#sList"), count = $("#sCount");
    if (!S) return;
    computeBorders();
    $$("#sConds .tog").forEach(function (b) {
      var c = CONDS.filter(function (x) { return x.id === b.getAttribute("data-id"); })[0];
      b.disabled = !!(c && c.live && !isToday());
    });
    var conds = active(), mode = ($("input[name=sMode]:checked") || {}).value || "and";
    var venue = $("#sVenue").value, upcoming = $("#sUpcoming").checked, q = nameQuery();
    var rows = [];
    (S.races || []).forEach(function (r) {
      if (venue && r.c !== venue) return;
      if (upcoming && finished(r)) return;
      var why = [], hits = 0;
      if (q) {
        var who = r.e.filter(function (e) { return (e.n || "").replace(/[\s　]/g, "").indexOf(q) >= 0 || String(e.t) === q; });
        if (!who.length) return;
        why.push({ label: "選手", w: who.map(function (e) { return waku(e.w) + " " + esc(e.n) + (e.fm ? '<span class="fem">♥</span>' : "") + ' <span class="dim">' + esc(e.t) + " " + esc(e.k || "") + "</span>"; }) });
      }
      conds.forEach(function (c) { var w = c.test(r); if (w) { hits++; why.push({ label: c.id === "in" || c.id === "kado" ? "" : c.label, w: w }); } });
      if (conds.length && (mode === "and" ? hits < conds.length : hits === 0)) return;
      rows.push({ r: r, why: why });
    });
    rows.sort(function (a, b) { return toMin(a.r.dl) - toMin(b.r.dl) || (a.r.c < b.r.c ? -1 : a.r.c > b.r.c ? 1 : a.r.no - b.r.no); });
    count.textContent = (conds.length || q ? "当てはまるレース " : "レース ") + rows.length + "件";
    jumpText = conds.length || q ? "当てはまるレース " + rows.length + "件を見る ↓" : "";
    paintJump();
    if (!rows.length) {
      var live = CONDS.some(function (c) { return ON[c.id] && c.live; });
      list.innerHTML = '<p class="sub">当てはまるレースはありません。' +
        (live && isToday() ? "直前情報の条件は、スタート展示のあとに取り込んだレースだけが対象です。" : "") +
        (upcoming && isToday() ? "終わったレースも探すときは「これからのレースだけ」を外してください。" : "") + "</p>";
      return;
    }
    list.innerHTML = rows.map(function (x) {
      var r = x.r, V = S.venues[r.c] || {}, res = resultOf(r), done = finished(r);
      var tri = res && res.tri ? '<span class="small-tri">' + res.tri.map(waku).join("") + "</span>" : done ? '<span class="dim">結果待ち</span>' : "";
      return '<a class="scard' + (done ? " done" : "") + '" href="' + S.ymd + "/" + r.c + "/" + String(r.no).padStart(2, "0") + '.html">' +
        '<span class="shead"><b>' + esc(V.name || r.c) + " " + r.no + 'R</b><span class="sdl">' + esc(r.dl || "") + "</span>" +
        '<span class="snm">' + esc(r.nm || "") + "</span>" + tri + "</span>" +
        (x.why.length ? '<span class="swhy">' + x.why.map(function (y) {
          return '<span class="wy">' + (y.label ? '<span class="wl">' + esc(y.label) + "</span>" : "") +
            y.w.map(function (t) { return '<span class="wi">' + t + "</span>"; }).join("") + "</span>";
        }).join("") + "</span>" : "") +
        "</a>";
    }).join("");
  }
  // 今日の分の直前情報・結果を読む。明日を見ているときは、今日のファイルから節の日付の並び(span)だけを使う
  function fetchLive() {
    if (!S || (!isToday() && spanTried)) { render(); return; }
    var today = isToday(), ymd = today ? S.ymd : nowJst().iso.replace(/-/g, "");
    if (!today) spanTried = true;
    var seq = loadSeq, codes = Object.keys(S.venues || {}).filter(function (c) { return today || !SPAN[c]; }), left = codes.length;
    if (!left) { render(); return; }
    codes.forEach(function (code) {
      getData("live", ymd + "/" + code + ".json")
        .then(function (j) {
          if (!j || seq !== loadSeq) return;
          if (j.span) SPAN[code] = j.span;
          if (today) LIVE[code] = j;
        })
        .catch(function () {})
        .then(function () { left--; if (!left && seq === loadSeq) render(); });
    });
  }
  function load(day) {
    var seq = ++loadSeq;
    S = null; LIVE = {}; spanTried = false;
    $$("#sDates [data-ymd]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-ymd") === day); });
    $("#sList").innerHTML = '<p class="sub">読み込み中…</p>';
    fetch(day + "/search.json", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (seq !== loadSeq) return;
      if (!j) { $("#sList").innerHTML = '<p class="sub">この日のデータがまだありません。</p>'; return; }
      S = j;
      var sel = $("#sVenue"), cur = sel.value;
      sel.innerHTML = '<option value="">すべての場</option>' + Object.keys(S.venues).sort().map(function (c) {
        var V = S.venues[c];
        return '<option value="' + c + '"' + (c === cur ? " selected" : "") + ">" + esc(V.name) + (V.day ? " " + V.day + "日目" : "") + "</option>";
      }).join("");
      render();
      fetchLive();
    }).catch(function () { if (seq === loadSeq) $("#sList").innerHTML = '<p class="sub">読み込めませんでした。時間をおいて開き直してください。</p>'; });
  }
  // 条件を選んでいる間、結果が画面の下に隠れていれば、件数のボタンを下に出す
  var jumpText = "", countSeen = true;
  function paintJump() { var b = $("#sJump"); if (b) { b.textContent = jumpText; b.hidden = !jumpText || countSeen; } }
  function save() {
    try { localStorage.setItem("suimen.search", JSON.stringify({ c: Object.keys(ON).filter(function (k) { return ON[k]; }), m: ($("input[name=sMode]:checked") || {}).value })); } catch (e) {}
  }
  function setup() {
    $("#sConds").innerHTML = GROUPS.map(function (g) {
      return '<div class="sgrp"><span class="sgl">' + esc(g[0]) + '</span><div class="chips">' + g[1].map(function (c) {
        return '<button type="button" class="chip tog" data-id="' + c.id + '" aria-pressed="false">' + esc(c.label) +
          (c.live ? '<i class="lv" title="スタート展示のあとに使えます">直前</i>' : "") + "</button>";
      }).join("") + "</div></div>";
    }).join("");
    try {                                               // 前に選んだ条件を戻す(この端末だけ)
      var saved = JSON.parse(localStorage.getItem("suimen.search") || "{}");
      (saved.c || []).forEach(function (id) { ON[id] = true; });
      if (saved.m) { var m = document.querySelector('input[name=sMode][value="' + saved.m + '"]'); if (m) m.checked = true; }
    } catch (e) {}
    function paint() { $$("#sConds .tog").forEach(function (b) { b.setAttribute("aria-pressed", ON[b.getAttribute("data-id")] ? "true" : "false"); }); }
    paint();
    $$("#sConds .tog").forEach(function (b) {
      b.addEventListener("click", function () { var id = b.getAttribute("data-id"); ON[id] = !ON[id]; paint(); save(); render(); });
    });
    $("#sClear").addEventListener("click", function () { ON = {}; $("#sName").value = ""; paint(); save(); render(); });
    $$("input[name=sMode], #sUpcoming, #sVenue").forEach(function (el) { el.addEventListener("change", function () { save(); render(); }); });
    $("#sName").addEventListener("input", render);
    $$("#sDates [data-ymd]").forEach(function (b) { b.addEventListener("click", function () { load(b.getAttribute("data-ymd")); }); });
    var on = $("#sDates .on") || $("#sDates [data-ymd]");
    if (on) load(on.getAttribute("data-ymd"));
    $("#sJump").addEventListener("click", function () { $("#sCount").scrollIntoView({ behavior: "smooth", block: "start" }); });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (es) { countSeen = es[0].isIntersecting || es[0].boundingClientRect.top < 0; paintJump(); })
        .observe($("#sCount"));
    }
    clearInterval(liveTimer);
    liveTimer = setInterval(function () { if (!document.hidden) fetchLive(); }, 60000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) fetchLive(); });
  }
  setup();
})();
