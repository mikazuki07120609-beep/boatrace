/* レースページ。出走表と選手の成績(ページに埋め込んだJSON)と、締切の前後に取り込む直前情報・結果(data/live)から、
   スタート展示のあとに、スタートの見立て(model.js)→ 展開の見立て → 1周1マークの映像(turn1.js)を作る。
   直前情報と結果は、開いている間も1分ごとに読み直す。買い目は出さない。 */
(function () {
  "use strict";
  var el = document.getElementById("race-data");
  if (!el) return;
  var D = JSON.parse(el.textContent);
  var V = D.venue;
  var PARAMS = window.SUIMEN_PARAMS || null, MODEL = window.SuimenModel || null;
  var KIM = ["逃げ", "捲り", "差し", "捲り差し", "抜き", "恵まれ"];
  var SHRINK = 10; // 走数が少ない選手の成績を、場の平均に寄せる強さ(学習済みの重みがないときの簡易モデル用)
  var LIVE_REL = D.race.ymd + "/" + V.code + ".json";
  // 直前情報・結果の読み込み(ページの頭の suimenGet: 先に Cloudflare、だめなら GitHub)。古いページと組み合わさったときは GitHub だけ
  var getData = window.suimenGet || function (k, rel) {
    return fetch("https://raw.githubusercontent.com/mikazuki07120609-beep/boatrace/" + (k === "odds" ? "odds/data/odds/" : "main/data/live/") + rel + "?t=" + Math.floor(Date.now() / 15000), { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; });
  };
  var NO = String(D.race.no);
  var BI = D.before || null, LR = D.live || null, OG = D.orig || null;     // 直前情報・レース直後の結果・場のオリジナル展示データ
  var URA = document.body.classList.contains("ura") && !!window.SuimenUraPage;   // 裏水面ノートのページ(ura_page.js が裏の部分を描く)
  var VW = null;                       // 同じ場の、いちばん新しい直前情報の風・波(展示の前の、裏の見込みの目安に使う)
  function $(s) { return document.querySelector(s); }
  function $$(s) { return [].slice.call(document.querySelectorAll(s)); }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function fmt(n, d) { return n == null || isNaN(n) ? "—" : Number(n).toFixed(d == null ? 1 : d); }
  function st2(x) { return x == null || isNaN(x) ? "—" : (x < 0 ? "F" : "") + Math.abs(x).toFixed(2).replace(/^0/, ""); }
  function avg(a) { var v = a.filter(function (x) { return x != null && !isNaN(x); }); return v.length ? v.reduce(function (s, x) { return s + x; }, 0) / v.length : null; }
  function pct(a, b) { return b ? Math.round(a / b * 100) : null; }
  function nowJst() { var t = new Date(Date.now() + 9 * 3600e3); return { iso: t.toISOString().slice(0, 10), min: t.getUTCHours() * 60 + t.getUTCMinutes() + t.getUTCSeconds() / 60 }; }
  function dlMin() { var a = (D.race.deadline || "0:0").split(":"); return +a[0] * 60 + +a[1]; }
  function minsLeft() { var n = nowJst(); return n.iso === D.race.date ? dlMin() - n.min : (n.iso < D.race.date ? 1e4 : -1e4); }

  // このコースでの決まり手の割合: 選手が勝ったときの決まり手を、場の傾向(4勝分の重み)で補う
  function kimDist(b) {
    var vk = V.kimarite[b.course - 1] || [0, 0, 0, 0, 0, 0], vt = vk.reduce(function (s, x) { return s + x; }, 0) || 1;
    var km = (b.csNow && b.csNow.km) || {}, tot = 0;
    KIM.forEach(function (k) { tot += km[k] || 0; });
    return KIM.map(function (k, j) { return ((km[k] || 0) + 4 * vk[j] / vt) / (tot + 4); });
  }
  // 選手のタイプ(捲り型・差し型など)。このコースで2勝以上し、6割以上が同じ決まり手なら
  function tacType(cs) {
    var km = (cs && cs.km) || {}, items = ["捲り", "捲り差し", "差し"].map(function (k) { return [k, km[k] || 0]; }).filter(function (x) { return x[1]; });
    items.sort(function (a, b) { return b[1] - a[1]; });
    var tot = items.reduce(function (s, x) { return s + x[1]; }, 0);
    return { text: items.map(function (x) { return x[0] + x[1]; }).join("・"), type: tot >= 2 && items[0][1] / tot >= 0.6 ? items[0][0] + "型" : "" };
  }

  // ---- 直前情報・結果
  function resEntry(waku) { return D.result ? D.result.entries.filter(function (x) { return x.waku === waku; })[0] || null : null; }
  function finished() { return !!(D.result || LR); }
  function beforeReady() { return !!(BI && BI.ready); }
  function ready() { return beforeReady() || finished(); }
  function courseOf(waku) {
    if (beforeReady() && BI.course && BI.course.length) { var i = BI.course.indexOf(waku); if (i >= 0) return i + 1; }
    var r = resEntry(waku);
    if (r && r.course) return r.course;
    if (LR && LR.course && LR.course.length) { var j = LR.course.indexOf(waku); if (j >= 0) return j + 1; }
    return waku;
  }
  function exOf(waku) {
    var v = BI && BI.ex ? BI.ex[String(waku)] : null;
    if (v == null) { var r = resEntry(waku); v = r ? r.ex : null; }
    return v == null || !isFinite(v) ? null : v;
  }
  function estOf(waku) { var v = beforeReady() && BI.est ? BI.est[String(waku)] : null; return v == null ? null : v; }
  function windSpeed() {
    if (BI && BI.weather && BI.weather.wind != null) return Math.round(BI.weather.wind);
    if (D.result && D.result.wind != null) return D.result.wind;
    return 2;
  }
  function readState() {
    return D.entries.map(function (e) {
      var b = Object.assign({}, e);
      b.ex = exOf(e.waku);
      b.course = courseOf(e.waku);
      return b;
    });
  }
  function windState() { var w = windSpeed(); return { wind: "none", wspd: w, strong: w >= 4 }; }

  // ---- 表(縦: 列が1〜6号艇、行が項目)。ランキングにできる項目は、1位を赤、2位を青で塗る
  var KS = { "逃げ": "逃げ", "捲り": "捲り", "差し": "差し", "捲り差し": "捲差", "抜き": "抜き", "恵まれ": "恵まれ" };
  var SECOND_ORDER = ["差し", "捲り", "捲り差し", "残し", "道中", "差され", "捲られ", "捲り差され", "抜かれ", "その他"];
  function winText(cs, course) {
    if (!cs || !cs.n) return "—";
    var km = cs.km || {};
    if (course === 1) return "逃げ" + (km["逃げ"] || 0) + (km["抜き"] ? " 抜き" + km["抜き"] : "");
    var items = Object.keys(km).filter(function (k) { return km[k] > 0 && k !== "恵まれ"; }).sort(function (a, b) { return km[b] - km[a]; }).slice(0, 2);
    return items.map(function (k) { return (KS[k] || k) + km[k]; }).join(" ") || "—";
  }
  function secondText(cs) {
    var s2 = (cs && cs.s2) || {};
    var items = Object.keys(s2).filter(function (k) { return s2[k] > 0 && k !== "その他"; }).sort(function (a, b) {
      return s2[b] - s2[a] || SECOND_ORDER.indexOf(a) - SECOND_ORDER.indexOf(b); }).slice(0, 2);
    return items.map(function (k) { return (KS[k] || k) + s2[k]; }).join(" ") || "—";
  }
  function tops(vals, dir) {
    var ok = vals.filter(function (v) { return v != null && isFinite(v); });
    if (ok.length < 2) return vals.map(function () { return false; });
    var best = dir === "min" ? Math.min.apply(null, ok) : Math.max.apply(null, ok);
    if (ok.every(function (v) { return Math.abs(v - best) < 1e-9; })) return vals.map(function () { return false; });
    return vals.map(function (v) { return v != null && isFinite(v) && Math.abs(v - best) < 1e-9; });
  }
  // 1位(赤)と2位(青)。1位が2艇以上で並んだときは2位を付けない。2位が3艇以上で並んだときも付けない
  function rank12(vals, dir) {
    var ok = vals.filter(function (v) { return v != null && isFinite(v); });
    if (ok.length < 2) return vals.map(function () { return 0; });
    var u = ok.slice().sort(function (a, b) { return dir === "min" ? a - b : b - a; }).filter(function (v, i, a) { return i === 0 || Math.abs(v - a[i - 1]) > 1e-9; });
    if (u.length < 2) return vals.map(function () { return 0; });
    function cnt(x) { return ok.filter(function (v) { return Math.abs(v - x) < 1e-9; }).length; }
    var two = cnt(u[0]) === 1 && cnt(u[1]) <= 2 && ok.length >= 3;
    return vals.map(function (v) {
      if (v == null || !isFinite(v)) return 0;
      if (Math.abs(v - u[0]) < 1e-9) return 1;
      return two && Math.abs(v - u[1]) < 1e-9 ? 2 : 0;
    });
  }
  function rkClass(r) { return r === 1 ? "top" : r === 2 ? "top2" : ""; }
  function vrow(label, cells, vals, dir, cls) {
    var t = vals ? rank12(vals, dir) : null;
    return '<tr class="' + (cls || "") + '"><th scope="row">' + label + "</th>" +
      cells.map(function (c, i) { return '<td class="' + (t ? rkClass(t[i]) : "") + '">' + c + "</td>"; }).join("") + "</tr>";
  }
  function femMark(e) { return e && e.fem ? '<span class="fem" title="女子レーサー" aria-label="女子レーサー">♥</span>' : ""; }
  // 欠場: 直前情報で欠場の印がある艇・スタート展示に出ず展示タイムもない艇、結果で「欠」の艇
  function absentWakus() {
    return D.entries.map(function (e) { return e.waku; }).filter(function (w) {
      var k = String(w);
      if (BI && BI.absent && BI.absent.indexOf(w) >= 0) return true;
      if (BI && BI.ready && BI.course && BI.course.length && BI.course.indexOf(w) < 0 && (!BI.ex || BI.ex[k] == null)) return true;
      var o = LR && LR.order ? LR.order.filter(function (x) { return x.waku === w; })[0] : null;
      if (o && o.status && /^欠/.test(o.status)) return true;
      var r = resEntry(w);
      return !!(r && r.status && /^K/.test(r.status));
    });
  }
  function absMark(e) { return e && absentWakus().indexOf(e.waku) >= 0 ? '<span class="abs">欠場</span>' : ""; }
  // 表の見出し(枠番)。names を付けると、選手名も見出しに入れる(下へ動かしても上に残る)
  function vhead(names) {
    return '<thead><tr><th class="corner"></th>' + D.entries.map(function (e) {
      var ab = absMark(e);
      return '<th class="bw w' + e.waku + (ab ? " absent" : "") + '"><span class="bn">' + e.waku + "</span>" + (names ? '<span class="hn">' + esc(e.name) + femMark(e) + "</span>" : "") + ab + "</th>";
    }).join("") + "</tr></thead>";
  }
  function p0(a, b) { return b ? Math.round(a / b * 100) : null; }
  function cell(v, suf, d) { return v == null || !isFinite(v) ? "—" : (d != null ? Number(v).toFixed(d) : v) + (suf ? '<span class="u">' + suf + "</span>" : ""); }
  var SM = { "S": "失", "F": "F", "L": "L", "K": "欠" };

  // モーター評価(艇ごと、D.entries の順): 展示タイムが4艇以上そろったら、レースの平均との差を加える(重みは scripts/motor.py と同じ)
  function motorZs() {
    var E = D.entries, exs = E.map(function (e) { return exOf(e.waku); }), okx = exs.filter(function (x) { return x != null && x > 6 && x < 7.6; });
    var exMean = okx.length >= 4 ? avg(okx) : null;
    return E.map(function (e, i) {
      if (!e.mg) return null;
      var z = e.mg.z;
      if (exMean != null && exs[i] != null) { var zt = Math.max(-3, Math.min(3, (exMean - exs[i]) / 0.047)); z = (0.55 * z + 0.45 * zt) / Math.sqrt(0.55 * 0.55 + 0.45 * 0.45); }
      return z;
    });
  }
  function grade(z) { return z == null ? "—" : z >= 1.4 ? "S" : z >= 0.65 ? "A" : z >= 0 ? "B" : z >= -0.65 ? "C" : z >= -1.4 ? "D" : "E"; }
  // S+: 全国で飛び抜けたモーター(motor.py の sp)。直前の展示で大きく崩れていなければ S+ のまま
  function gradeOf(z, mg) { return mg && mg.sp && z != null && z >= 0.65 ? "S+" : grade(z); }
  function gBadge(g) { return '<b class="g ' + (g === "S+" ? "gSp" : "g" + g) + '">' + g + "</b>"; }

  // 出走表
  function renderCard() {
    var box = $("#cardBox");
    if (!box) return;
    var E = D.entries, C = E.map(function (e) { return courseOf(e.waku); }), moved = E.some(function (e, i) { return C[i] !== e.waku; });
    var CS = E.map(function (e, i) { return (e.cs || {})[String(C[i])] || null; });
    var mz = motorZs();
    var rows = [];
    rows.push(vrow("級別・登番", E.map(function (e) { return '<b class="cls c' + esc(e.cls) + '">' + esc(e.cls) + '</b><span class="dim">' + esc(e.toban) + "</span>"; })));
    rows.push(vrow("支部・年齢", E.map(function (e) { return '<span class="dim">' + esc(e.branch || "") + "<br>" + esc(e.age) + "歳 " + (e.weight ? e.weight + "kg" : "") + "</span>"; })));
    rows.push(vrow("F・L", E.map(function (e) { return '<span class="' + (e.fp ? "fon" : "") + '">F' + (e.fp || 0) + "</span>" + (e.lp != null ? ' <span class="dim">L' + e.lp + "</span>" : ""); })));
    rows.push(vrow("平均ST", E.map(function (e) { return st2(e.ast); }), E.map(function (e) { return e.ast; }), "min"));
    rows.push(vrow("全国勝率", E.map(function (e) { return cell(e.rate, "", 2); }), E.map(function (e) { return e.rate; }), "max"));
    rows.push(vrow("全国2連率", E.map(function (e) { return cell(e.rate2, "%", 1); }), E.map(function (e) { return e.rate2; }), "max"));
    rows.push(vrow("当地勝率", E.map(function (e) { return cell(e.local, "", 2); }), E.map(function (e) { return e.local; }), "max"));
    rows.push(vrow("当地2連率", E.map(function (e) { return cell(e.local2, "%", 1); }), E.map(function (e) { return e.local2; }), "max"));
    rows.push('<tr class="grp"><th colspan="7">このコース(' + (moved ? "展示の進入" : "枠と同じ") + ")の直近1年</th></tr>");
    rows.push(vrow("コース", C.map(function (c) { return c; })));
    var r1 = CS.map(function (cs) { return cs && cs.n ? p0(cs.w1, cs.n) : null; }), r2 = CS.map(function (cs) { return cs && cs.n ? p0(cs.w2, cs.n) : null; }),
        r3 = CS.map(function (cs) { return cs && cs.n ? p0(cs.w3, cs.n) : null; });
    rows.push(vrow("1着率", r1.map(function (v) { return cell(v, "%"); }), r1, "max"));
    rows.push(vrow("2着率", r2.map(function (v) { return cell(v, "%"); }), r2, "max"));
    rows.push(vrow("3着率", r3.map(function (v) { return cell(v, "%"); }), r3, "max"));
    rows.push(vrow("ST", CS.map(function (cs) { return cs ? st2(cs.st) : "—"; }), CS.map(function (cs) { return cs && cs.n >= 3 ? cs.st : null; }), "min"));
    rows.push(vrow("走数", CS.map(function (cs) { return cs ? cs.n : 0; })));
    rows.push(vrow("勝ち方", CS.map(function (cs, i) { return '<span class="tx">' + esc(winText(cs, C[i])) + "</span>"; })));
    rows.push(vrow("2着の時", CS.map(function (cs) { return '<span class="tx">' + esc(secondText(cs)) + "</span>"; })));
    rows.push(vrow("逃げ・逃がし", CS.map(function (cs, i) {
      if (!cs || !cs.n || C[i] > 2) return "—";
      return '<span class="dim">' + (C[i] === 1 ? "逃げ" : "逃がし") + "</span>" + p0(C[i] === 1 ? (cs.km || {})["逃げ"] || 0 : cs.ng || 0, cs.n) + "%";
    })));
    // このレースの区分(女子戦・SG・G1・G2・G3・一般)のときの、このコースの成績(直近1年)
    if (D.cat) {
      var G = E.map(function (e, i) {
        var g = (e.csg || {})[String(C[i])];
        if (Array.isArray(g)) g = g[0] ? { n: g[0], w1: g[1], w2: g[2], w3: g[3], km: {} } : null;   // 前の形([走数, 1着, 2着, 3着])
        return g && g.n ? g : null;
      });
      function gr(k) { return G.map(function (g) { return g ? p0(g["w" + k], g.n) : null; }); }
      function gv(k) { return G.map(function (g) { return g && g.n >= 3 ? p0(g["w" + k], g.n) : null; }); }   // 3走未満は1位・2位の色を付けない
      rows.push('<tr class="grp gcat"><th colspan="7"><span class="cattag">' + esc(D.cat) + "</span>のときのこのコース(直近1年)</th></tr>");
      [1, 2, 3].forEach(function (k) { rows.push(vrow(k + "着率", gr(k).map(function (v) { return cell(v, "%"); }), gv(k), "max")); });
      rows.push(vrow("ST", G.map(function (g) { return g ? st2(g.st) : "—"; }), G.map(function (g) { return g && g.n >= 3 && g.st != null ? g.st : null; }), "min"));
      rows.push(vrow("走数", G.map(function (g) { return g ? g.n : 0; })));
      rows.push(vrow("勝ち方", G.map(function (g, i) { return '<span class="tx">' + esc(winText(g, C[i])) + "</span>"; })));
      rows.push(vrow("2着の時", G.map(function (g) { return '<span class="tx">' + esc(secondText(g)) + "</span>"; })));
      rows.push(vrow("逃げ・逃がし", G.map(function (g, i) {
        if (!g || !g.n || C[i] > 2) return "—";
        return '<span class="dim">' + (C[i] === 1 ? "逃げ" : "逃がし") + "</span>" + p0(C[i] === 1 ? (g.km || {})["逃げ"] || 0 : g.ng || 0, g.n) + "%";
      })));
    }
    rows.push('<tr class="grp"><th colspan="7">モーター・ボート</th></tr>');
    rows.push(vrow("モーター評価", mz.map(function (z, i) { return gBadge(gradeOf(z, E[i].mg)); }), mz.map(function (z, i) { return gradeOf(z, E[i].mg) === "S+" ? 99 : z; }), "max", "mo"));
    rows.push(vrow("モーター", E.map(function (e) { return '<span class="dim">' + esc(e.motor) + "号機</span>" + cell(e.motor2, "%", 1); }), E.map(function (e) { return e.motor2; }), "max"));
    rows.push(vrow("ボート", E.map(function (e) { return '<span class="dim">' + esc(e.boat) + "号艇</span>" + cell(e.boat2, "%", 1); }), E.map(function (e) { return e.boat2; }), "max"));
    rows.push('<tr class="grp"><th colspan="7">今節</th></tr>');
    rows.push(vrow("着順", E.map(function (e) {
      var days = (e.series_days || []).filter(Boolean);
      return days.length ? '<span class="days">' + days.map(function (d) {
        return "<em>" + d.split("").map(function (ch) { return SM[ch] ? '<i class="ng">' + SM[ch] + "</i>" : ch === "1" ? '<i class="top1">1</i>' : "<i>" + ch + "</i>"; }).join("") + "</em>";
      }).join("") + "</span>" : "—";
    }), null, null, "series"));
    rows.push(vrow("節間順位", E.map(function (e) { return e.srank ? e.srank[0] + '<span class="dim">/' + e.srank[1] + "</span>" : "—"; }),
      E.map(function (e) { return e.srank ? e.srank[0] : null; }), "min"));
    box.innerHTML = '<div class="vt-wrap stick"><table class="vt rcv">' + vhead(true) + "<tbody>" + rows.join("") + "</tbody></table></div>";
  }

  // ---- コース別の戦法: 選手ごと・コースごとの戦い方(直近1年)。1着の決まり手・2着/3着の時の動き(推定)・スタートで内より先に出た割合・
  //      その選手がそのコースにいたときの1コースの逃げと、外の艇の差し・捲り差しの割合(全国の割合と比べる)
  var TAC = { w: null }, TAC_MV = ["捲り", "差し", "捲り差し"], TAC_N = 15;
  function cnt(o, k) { return (o || {})[k] || 0; }
  function tacNat() {
    var nt = D.nt || {}, races = (nt["1"] || {}).n || 0, out = { nige: null, sa: {} };
    if (!races) return out;
    out.nige = cnt((nt["1"] || {}).km, "逃げ") / races;
    for (var c = 2; c <= 6; c++) { var km = (nt[String(c)] || {}).km || {}; out.sa[c] = (cnt(km, "差し") + cnt(km, "捲り差し")) / races; }
    return out;
  }
  function tacOf(cs, c, NR) {
    cs = cs || {};
    var n = cs.n || 0, wc = cs.wc || {}, mv = {}, tot = 0;
    TAC_MV.forEach(function (k) { mv[k] = cnt(cs.km, k) + cnt(cs.s2, k) + cnt(cs.s3, k); tot += mv[k]; });
    var top = TAC_MV.slice().sort(function (a, b) { return mv[b] - mv[a]; }), type = "—";
    if (c === 1) { if (n >= 5) { var r = cnt(cs.km, "逃げ") / n; type = r >= 0.62 ? "逃げが堅い" : r <= 0.42 ? "逃げが弱い" : "逃げは標準"; } else if (n) type = "記録が少ない"; }
    else if (tot >= 5) type = mv[top[0]] / tot >= 0.5 ? top[0] + "型" : top[0] + "・" + top[1];
    else if (n) type = "記録が少ない";
    var osa = 0, osaNat = 0;
    for (var k = c + 1; k <= 6; k++) { osa += cnt(wc, k + "差し") + cnt(wc, k + "捲り差し"); osaNat += NR.sa[k] || 0; }
    return { n: n, mv: mv, tot: tot, top: top, type: type, cs: cs,
             nige: n && Object.keys(wc).length ? cnt(wc, "1逃げ") / n : null, nigeNat: NR.nige,
             osa: n && c < 6 && Object.keys(wc).length ? osa / n : null, osaNat: c < 6 ? osaNat : null,
             lead: c >= 2 && cs.sn ? (cs.sl || 0) / cs.sn : null };
  }
  function tacList(o, keys) {                        // 決まり手・動きの回数を多い順に(上位3つ)
    o = o || {};
    var items = Object.keys(o).filter(function (k) { return o[k] > 0 && k !== "その他" && (!keys || keys.indexOf(k) >= 0); })
      .sort(function (a, b) { return o[b] - o[a]; }).slice(0, 3);
    return items.length ? '<span class="tx">' + items.map(function (k) { return esc(KS[k] || k) + o[k]; }).join(" ") + "</span>" : "—";
  }
  function tacRate(v, nat, n, gap) {               // 割合と全国の割合。15走以上で全国と大きく違えば ▲▼
    if (v == null) return "—";
    var mark = "", cls = "";
    if (nat != null && n >= TAC_N && Math.abs(v - nat) >= gap) { mark = v > nat ? "▲" : "▼"; cls = v > nat ? "up" : "dn"; }
    return '<span class="rt"><b class="' + cls + '">' + mark + Math.round(v * 100) + "%</b>" + (nat != null ? '<span class="dim">全国' + Math.round(nat * 100) + "%</span>" : "") + "</span>";
  }
  function tacRows(list, cols, todayIdx) {           // list: [{t, c}] (t: tacOf の結果, c: コース)。cols: 列の見出し(thead)。todayIdx: 今日のコースの列
    function vrow(label, cells, vals, dir) {
      var t = vals ? rank12(vals, dir) : null;
      return '<tr><th scope="row">' + label + "</th>" + cells.map(function (c, i) {
        return '<td class="' + ((t ? rkClass(t[i]) : "") + (i === todayIdx ? " today" : "")).trim() + '">' + c + "</td>"; }).join("") + "</tr>";
    }
    var rows = [];
    rows.push(vrow("走数", list.map(function (x) { return x.t.n ? String(x.t.n) : "—"; })));
    rows.push(vrow("タイプ", list.map(function (x) { return x.t.type === "—" ? "—" : '<span class="ty">' + esc(x.t.type) + "</span>"; })));
    rows.push(vrow("1着の時", list.map(function (x) { return tacList(x.t.cs.km); })));
    rows.push(vrow("2着の時", list.map(function (x) { return tacList(x.t.cs.s2); })));
    rows.push(vrow("3着の時", list.map(function (x) { return tacList(x.t.cs.s3); })));
    rows.push(vrow("内より<br>先に出た", list.map(function (x) { return x.t.lead == null ? "—" : Math.round(x.t.lead * 100) + "%"; }),
      list.map(function (x) { return x.t.lead != null && x.t.n >= 5 ? x.t.lead : null; }), "max"));
    rows.push(vrow("1コースの<br>逃げ", list.map(function (x) { return tacRate(x.t.nige, x.t.nigeNat, x.t.n, 0.08); })));
    rows.push(vrow("外の差し・<br>捲り差し", list.map(function (x) { return x.c >= 6 ? "—" : tacRate(x.t.osa, x.t.osaNat, x.t.n, 0.05); })));
    return '<div class="vt-wrap"><table class="vt tact">' + cols + "<tbody>" + rows.join("") + "</tbody></table></div>";
  }
  function renderTactics() {
    var now = $("#tacNow"), notes = $("#tacNotes"), boxB = $("#tacBoats"), all = $("#tacAll");
    if (!now) return;
    var NR = tacNat(), E = D.entries, C = E.map(function (e) { return courseOf(e.waku); });
    var list = E.map(function (e, i) { return { e: e, c: C[i], t: tacOf((e.cs || {})[String(C[i])], C[i], NR) }; });
    var head = '<thead><tr><th class="corner"></th>' + list.map(function (x) {
      var ab = absMark(x.e);
      return '<th class="bw w' + x.e.waku + (ab ? " absent" : "") + '"><span class="bn">' + x.e.waku + '</span><span class="hn">' + esc(x.e.name) + femMark(x.e) + "</span>" + ab +
        '<small class="hc">' + x.c + "コース</small></th>";
    }).join("") + "</tr></thead>";
    now.innerHTML = tacRows(list, head);
    // このレースのポイント: 今日のコースで目立つ戦い方
    var pts = [];
    list.slice().sort(function (a, b) { return a.c - b.c; }).forEach(function (x) {
      var t = x.t, nm = x.c + "コースの" + x.e.name, parts = [];
      if (x.c === 1) {
        if (t.n >= 10 && t.nige != null && t.nigeNat != null && Math.abs(t.nige - t.nigeNat) >= 0.10) {
          var ls = t.cs.ls || {}, lk = ["差し", "捲り", "捲り差し"].filter(function (k) { return ls[k]; }).sort(function (a, b) { return ls[b] - ls[a]; })[0];
          pts.push(nm + "は、1コースの逃げ" + Math.round(t.nige * 100) + "%(全国" + Math.round(t.nigeNat * 100) + "%)と" + (t.nige > t.nigeNat ? "高い。" : "低い。") +
            (t.nige < t.nigeNat && lk ? "負けたときは" + ({ "差し": "差され", "捲り": "捲られ", "捲り差し": "捲り差され" })[lk] + "が多い(" + ls[lk] + "回)。" : ""));
        }
        return;
      }
      if (t.tot >= 6 && t.mv[t.top[0]] / t.tot >= 0.5)
        parts.push(x.c + "コースでは" + t.top[0] + "が多い(" + TAC_MV.filter(function (k) { return t.mv[k]; }).map(function (k) { return k + t.mv[k]; }).join("・") + "。1〜3着の合計)");
      if (t.lead != null && t.n >= 10 && t.lead >= 0.3) parts.push("スタートで内より先に出ることが多く(" + Math.round(t.lead * 100) + "%)、握って攻めやすい");
      if (t.n >= TAC_N && t.nige != null && t.nigeNat != null && t.nige <= t.nigeNat - 0.08) parts.push("この選手が" + x.c + "コースにいると1コースの逃げが決まりにくい(" + Math.round(t.nige * 100) + "%・全国" + Math.round(t.nigeNat * 100) + "%)");
      if (t.n >= TAC_N && t.nige != null && t.nigeNat != null && t.nige >= t.nigeNat + 0.08) parts.push("この選手が" + x.c + "コースにいると1コースが逃げやすい(" + Math.round(t.nige * 100) + "%・全国" + Math.round(t.nigeNat * 100) + "%)");
      if (t.n >= TAC_N && t.osa != null && t.osaNat != null && t.osa >= t.osaNat + 0.05) parts.push("外の艇の差し・捲り差しがよく決まる(" + Math.round(t.osa * 100) + "%・全国" + Math.round(t.osaNat * 100) + "%)ので、外の艇にもチャンス");
      if (parts.length) pts.push(nm + ": " + parts.join("。") + "。");
    });
    if (notes) notes.innerHTML = pts.slice(0, 5).map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("") ||
      "<li>" + esc("このレースの6人には、今日のコースで目立った戦い方の偏りはありません(走数が少ない選手は数えていません)。") + "</li>";
    // 選手を選んで、全コースの戦法
    if (!boxB || !all) return;
    if (TAC.w == null || !E.some(function (e) { return e.waku === TAC.w; })) TAC.w = E[0] ? E[0].waku : null;
    boxB.innerHTML = E.map(function (e, i) {
      var on = e.waku === TAC.w;
      return '<button type="button" class="' + (on ? "on" : "") + '" data-w="' + e.waku + '" aria-pressed="' + on + '">' + wk(e.waku) + esc(surname(e.name)) + femMark(e) + "</button>";
    }).join("");
    var me = E.filter(function (e) { return e.waku === TAC.w; })[0];
    if (!me) { all.innerHTML = ""; return; }
    var today = C[E.indexOf(me)];
    var list2 = [1, 2, 3, 4, 5, 6].map(function (c) { return { e: me, c: c, t: tacOf((me.cs || {})[String(c)], c, NR) }; });
    var head2 = '<thead><tr><th class="corner"></th>' + [1, 2, 3, 4, 5, 6].map(function (c) {
      return '<th class="cno' + (c === today ? " today" : "") + '">' + c + (c === today ? "<small>今日</small>" : "<small>コース</small>") + "</th>";
    }).join("") + "</tr></thead>";
    all.innerHTML = tacRows(list2, head2, today - 1);
  }
  function setupTactics() {
    var boxB = $("#tacBoats");
    if (!boxB) return;
    boxB.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-w]");
      if (!b) return;
      TAC.w = +b.getAttribute("data-w");
      renderTactics();
    });
  }

  // 直前情報(展示タイム・推定タイム・スタート展示など)
  function renderBefore() {
    var box = $("#beforeBox"), at = $("#beforeAt"), exb = $("#ex1Box");
    if (!box) return;
    var has = BI && BI.ex && Object.keys(BI.ex).some(function (k) { return BI.ex[k] != null; });
    var fromRes = !has && D.result;
    if (!has && !fromRes) {
      var left = minsLeft();
      box.innerHTML = '<p class="wait">' + (left < -5 || finished() ? "このレースの直前情報は取り込めませんでした。" : "展示航走のあと(締切の10〜15分前ごろ)に自動で入ります。") + "</p>";
      if (at) at.textContent = "";
      if (exb) exb.innerHTML = ex1Text([]);
      return;
    }
    var E = D.entries, exs = E.map(function (e) { return exOf(e.waku); });
    var okx = exs.filter(function (x) { return x != null && x > 6 && x < 7.6; }), exMean = okx.length >= 4 ? avg(okx) : null;
    var sorted = okx.slice().sort(function (a, b) { return a - b; });
    var PC = D.pace || null;
    var spd = exs.map(function (x) { return x ? 150 / x * 3.6 : null; });
    var lap = exs.map(function (x, i) {
      if (!PC || x == null || exMean == null) return null;
      var b = PC.boats[String(E[i].waku)] || { res: 0 };
      return PC.lap + b.res / 3 + PC.beta * (x - exMean) / 3;
    });
    var turn0 = E.map(function (e) { var b = PC && PC.boats[String(e.waku)]; return b ? b.turn / 3 : null; });
    var tm = avg(turn0), turn = turn0.map(function (v) { return v == null || tm == null ? null : v - tm; });   // 6艇の平均との差
    var est = E.map(function (e) { return has && BI.est ? BI.est[String(e.waku)] : null; });
    var rows = [];
    rows.push(vrow("展示タイム", exs.map(function (x) { return x == null ? "—" : "<b>" + x.toFixed(2) + '</b><span class="dim">' + (sorted.indexOf(x) + 1) + "位</span>"; }), exs, "min"));
    if (OG) {
      // 場が出している展示航走の計測タイム(短いほど良い。測り方は場ごとに違うので、6艇の中で比べる)
      [["lap", "一周"], ["half", "半周"], ["turn", "まわり足"], ["line", "直線"]].forEach(function (kv) {
        var m = OG[kv[0]];
        if (!m) return;
        var vals = E.map(function (e) { var x = m[String(e.waku)]; return x == null ? null : x; });
        var sortedV = vals.filter(function (x) { return x != null; }).sort(function (a, b) { return a - b; });
        rows.push(vrow(kv[1] + "<small>場の計測</small>", vals.map(function (x) { return x == null ? "—" : "<b>" + x.toFixed(2) + '</b><span class="dim">' + (sortedV.indexOf(x) + 1) + "位</span>"; }), vals, "min"));
      });
      // 場の直線の計測があるときは、展示タイムからの推定(食い違って見えることがある)は出さない
      if (!OG.line) rows.push(vrow("直線速度<small>推定</small>", spd.map(function (v) { return v == null ? "—" : v.toFixed(1) + '<span class="dim">km/h</span>'; }), spd, "max"));
    } else {
      rows.push(vrow("直線速度<small>推定</small>", spd.map(function (v) { return v == null ? "—" : v.toFixed(1) + '<span class="dim">km/h</span>'; }), spd, "max"));
      rows.push(vrow("一周タイム<small>推定</small>", lap.map(function (v) { return v == null ? "—" : v.toFixed(2); }), lap, "min"));
      rows.push(vrow("まわり足<small>推定</small>", turn.map(function (v) { return v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2); }), turn, "min"));
    }
    rows.push(vrow("進入", E.map(function (e) { var c = courseOf(e.waku); return c !== e.waku ? '<b class="moved">' + c + "</b>" : String(c); })));
    rows.push(vrow("展示ST", est.map(function (x) { return x == null ? "—" : x < 0 ? '<span class="fon">F' + st2(-x).replace("F", "") + "</span>" : st2(x); }),
      est.map(function (x) { return x != null && x >= 0 ? x : null; }), "min"));
    if (has) {
      rows.push(vrow("チルト", E.map(function (e) { var v = BI.tilt ? BI.tilt[String(e.waku)] : null; return v == null ? "—" : fmt(v, 1); })));
      rows.push(vrow("部品交換", E.map(function (e) {
        var w = String(e.waku), parts = (BI.parts && BI.parts[w] || []).slice();
        if (BI.prop && BI.prop[w]) parts.push("プロペラ" + BI.prop[w]);
        return parts.length ? '<span class="tx">' + esc(parts.join(" ")) + "</span>" : "—";
      })));
      rows.push(vrow("体重", E.map(function (e) {
        var w = String(e.waku), v = BI.weight ? BI.weight[w] : null, a = BI.adj ? BI.adj[w] : null;
        return (v == null ? "—" : fmt(v, 1)) + (a ? '<span class="dim">調整' + fmt(a, 1) + "</span>" : "");
      })));
    }
    var W = has ? BI.weather || {} : {};
    var wl = has ? [W.at ? W.at + "時点" : "", W.weather || "", W.temp != null ? "気温" + fmt(W.temp, 0) + "℃" : "", W.wind != null ? "風速" + fmt(W.wind, 0) + "m" : "",
                    W.wave != null ? "波高" + fmt(W.wave, 0) + "cm" : "", W.water != null ? "水温" + fmt(W.water, 0) + "℃" : ""].filter(Boolean).join("・")
                 : (D.result ? "風 " + (D.result.wind_dir || "") + (D.result.wind != null ? D.result.wind + "m" : "") + "(競走成績から)" : "");
    box.innerHTML = '<div class="vt-wrap stick"><table class="vt">' + vhead(true) + "<tbody>" + rows.join("") + "</tbody></table></div>" +
      (wl ? '<p class="sub">' + esc(wl) + "</p>" : "");
    if (at) at.textContent = has ? (BI.fetched ? BI.fetched + " 取り込み" : "") : "";
    // 展示タイム1位の艇の1着率
    var best = exMean != null ? Math.min.apply(null, okx) : null, bi = best != null ? exs.indexOf(best) : -1;
    var ex1b = best == null ? [] : E.filter(function (e, i) { return exs[i] === best; }).map(function (e) { return { e: e, c: courseOf(e.waku) }; });
    if (exb) exb.innerHTML = ex1Text(ex1b);
  }
  // 展示タイム1位の選手の成績: その選手が展示タイム1位だったとき(直近1年)の、コース別の回数と1着・2着・3着の割合。
  // 各マスの下に、全国(全選手)で展示タイム1位の艇の割合を小さく添える。同タイムで1位が2艇以上なら、それぞれ出す
  function ex1Text(bs) {
    var X = (D.pace && D.pace.ex1) || {}, RX = (D.pace && D.pace.ex1r) || {};
    var head = '<h3>展示タイム1位の選手の成績<small>展示1位だったとき・直近1年</small></h3>';
    if (!bs || !bs.length) return '<div class="ex1">' + head + '<p class="wait">展示航走のあと、展示タイム1位になった選手の、これまで展示1位だったときのコース別の成績を出します。</p></div>';
    function r(a, k) { return a && a[0] > 0 && a.length > k ? Math.round(a[k] / a[0] * 100) : null; }
    function rt(a, k) { var v = r(a, k); return v == null ? "—" : v + "%"; }
    function nat(a, k) { return a && a[0] >= 20 && a.length > k ? "全国" + Math.round(a[k] / a[0] * 100) + "%" : ""; }
    return '<div class="ex1">' + head + bs.map(function (b) {
      var m = RX[String(b.e.waku)] || {}, tot = [0, 0, 0, 0];
      Object.keys(m).forEach(function (c) { for (var k = 0; k < 4; k++) tot[k] += m[c][k] || 0; });
      var who = '<div class="ex1who"><span class="waku w' + b.e.waku + '">' + b.e.waku + "</span><b>" + esc(b.e.name) + "</b>" + femMark(b.e) +
        '<span class="sub">今日は' + b.c + "コース</span></div>";
      if (!tot[0]) return who + '<p class="sub">この選手は、直近1年で展示タイム1位になったレースがありません。</p>';
      var sum = '<div class="ex1s"><span class="lbl">全コース</span>' + [1, 2, 3].map(function (k) { return '<span class="rk r' + k + '">' + k + "着 <b>" + rt(tot, k) + "</b></span>"; }).join("") +
        '<span class="cnt">' + tot[0] + "回</span></div>";
      var rows = [1, 2, 3, 4, 5, 6].map(function (c) {
        var A = m[String(c)], N = (X.course || {})[String(c)], hit = b.c === c;
        return '<tr class="' + (hit ? "hit" : "") + (A && A[0] ? "" : " none") + '"><th scope="row"><span class="cn">' + c + "</span>" + (hit ? '<span class="here">今日</span>' : "") + "</th>" +
          "<td><b>" + (A ? A[0] : 0) + "</b></td>" +
          [1, 2, 3].map(function (k) { return '<td class="r' + k + '"><b>' + rt(A, k) + '</b><span class="dim">' + nat(N, k) + "</span></td>"; }).join("") + "</tr>";
      }).join("");
      return who + sum + '<div class="gridt-wrap"><table class="gridt ex1t"><thead><tr><th>コース</th><th>展示1位の回数</th><th>1着率</th><th>2着率</th><th>3着率</th></tr></thead><tbody>' +
        rows + "</tbody></table></div>";
    }).join("") + '<p class="sub">各マスの上がこの選手の数字、下の小さい数字は全国(全選手)で展示タイム1位だった艇の割合です。色の付いた行が、今日のコースです。</p></div>';
  }
  function topThree(order) {
    var fin = (order || []).filter(function (x) { return x.rank; }).sort(function (a, b) { return a.rank - b.rank; });
    return fin.length >= 3 ? fin.slice(0, 3).map(function (x) { return x.waku; }) : null;
  }
  // 結果(3連単の組と払戻金)
  function renderResult() {
    var bar = $("#resbar");
    if (!bar || !LR) return;
    var tri = LR.tri && LR.tri.length === 3 ? LR.tri : topThree(LR.order);       // 3連単がない(返還など)ときは着順から
    if (!tri) return;
    var t = tri.map(function (w) { return '<span class="waku w' + w + '">' + w + "</span>"; }).join('<span class="sep">-</span>');
    bar.innerHTML = '<span class="lbl">結果</span><span class="tri">' + t + "</span>" +
      (LR.pay ? '<b class="odds">' + (LR.pay / 100).toFixed(1) + "倍</b>" + (LR.pop ? '<span class="dim">' + LR.pop + "番人気</span>" : "") : "") +
      (URA && LR.pay >= 10000 ? '<span class="uman-tag">万舟</span>' : "") +
      (LR.kimarite ? '<span class="tag">' + esc(LR.kimarite) + "</span>" : "") + (LR.note ? '<span class="sub">' + esc(LR.note) + "</span>" : "");
    bar.hidden = false;
  }
  function renderDeadline() {
    var t = $("#dlTag");
    if (!t) return;
    var left = minsLeft(), s = "締切 " + D.race.deadline + (D.race.deadline0 ? "(変更)" : "");
    t.title = D.race.deadline0 ? "レースが遅れたため、公式の締切が" + D.race.deadline0 + "から" + D.race.deadline + "に変わりました" : "";
    if (finished()) s += "(終了)";
    else if (left > 0 && left < 600) s += "(あと" + Math.floor(left) + "分)";
    else if (left <= 0 && left > -600) s += "(締切済み)";
    t.textContent = s;
    t.classList.toggle("soon", !finished() && left > 0 && left <= 10);
  }
  // 欠場があるレース: 見立て・1周1マークの映像・展開ナビは6艇そろったレースだけで計算しているので、出せないことを説明する
  function absentText(ab) {
    return ab.map(function (w) { var e = D.entries.filter(function (x) { return x.waku === w; })[0]; return w + "号艇" + (e ? " " + e.name : ""); }).join("・") + "が欠場";
  }
  function showAbsent(ab) {
    var who = absentText(ab);
    setGated(false);
    $$(".gated").forEach(function (sec) {
      var w = sec.querySelector(".wait");
      if (!sec.querySelector("#stBox")) { sec.hidden = true; sec.setAttribute("data-abshide", "1"); return; }   // 展開の見立て・道中・解説文は、映像の説明だけにする
      if (!w) return;
      if (w.getAttribute("data-orig") == null) w.setAttribute("data-orig", w.textContent);
      w.textContent = who + "のため、このレースはスタートの見立てを出せません(見立ては6艇そろったレースだけで計算しています)。";
      w.classList.add("absent-note");
    });
    var tw = $("#t1Wait");
    if (tw) {
      if (tw.getAttribute("data-orig") == null) tw.setAttribute("data-orig", tw.textContent);
      tw.textContent = who + "のため、このレースは1周1マークの展開予想ができません(展開の見立て・映像は、6艇そろったレースだけで計算しています)。";
      tw.classList.add("absent-note");
    }
    var hl = $("#t1Head");
    if (hl) hl.hidden = true;
    var al = $("#alerts");
    if (al) al.innerHTML = "";
  }
  function restoreWait() {                                         // 欠場の説明を出したあとで、6艇そろっていたと分かったとき
    $$("[data-orig]").forEach(function (w) { w.textContent = w.getAttribute("data-orig"); w.removeAttribute("data-orig"); w.classList.remove("absent-note"); });
    $$("[data-abshide]").forEach(function (sec) { sec.hidden = false; sec.removeAttribute("data-abshide"); });
  }
  function setGated(on) {
    $$(".gated").forEach(function (sec) {
      var w = sec.querySelector(".wait"), b = sec.querySelector(".gbody");
      if (w) w.hidden = on;
      if (b) b.hidden = !on;
    });
    var tw = $("#t1Wait"), tb = $("#t1Body");
    if (tw) tw.hidden = on;
    if (tb) tb.hidden = !on;
  }

  // 風向き(追い風・向かい風)の影響は、場ごとの向きのデータがまだないので、目安として掛ける
  function windKw(W) {
    var kw = { "逃げ": 1, "捲り": 1, "差し": 1, "捲り差し": 1, "抜き": 1 };
    if (W.strong && W.wind === "head") { kw["捲り"] *= 1.15; kw["捲り差し"] *= 1.1; kw["逃げ"] *= 0.9; }
    if (W.strong && W.wind === "tail") { kw["差し"] *= 1.1; kw["捲り"] *= 0.9; }
    if (W.strong && W.wind === "side") { kw["逃げ"] *= 0.95; }
    return kw;
  }

  function prepBoats(B) {
    B.forEach(function (b) {
      b.power = b.rate == null ? null : (b.local ? b.rate * 0.7 + b.local * 0.3 : b.rate);
      var cs = (b.cs || {})[String(b.course)] || null;
      b.csNow = cs;
      b.stUse = cs && cs.st != null && cs.n >= 3 ? cs.st : (b.st_all != null ? b.st_all : null);
    });
  }

  // ---- 学習済みの見立てモデル(model.js)で計算する
  function analyzeModel(B, W) {
    var race = { vt: D.vt, nt: D.nt, wind: W.wspd, date: D.race.date, venue: V.code, name: D.race.name,
                 boats: B.map(function (b) { return { waku: b.waku, course: b.course, pts: b.pts || [0, 0], stx: b.stx || [0, 0, 0], r8: b.r8 || [], f: b.f || [], est: estOf(b.waku), cb: b.cb || [0, 0],
                                                      cs: b.cs || {}, motor2: b.motor2, motorR: b.motorR, lv: b.lv || [0, 0], ex: b.ex }; }) };
    var M = MODEL.predict(race, PARAMS, { samples: 400 });
    if (!M) return null;
    var kw = windKw(W), byC = {};
    B.forEach(function (b) { byC[b.course] = b; });
    var scen = M.classes.map(function (ck, i) { return { b: byC[ck[0]], kim: ck[1], w: M.p[i] * (kw[ck[1]] || 1), i: i }; });
    var tot = scen.reduce(function (s, x) { return s + x.w; }, 0) || 1;
    scen.forEach(function (s) { s.p = s.w / tot * 100; });
    scen.sort(function (a, b) { return b.p - a.p; });
    M.st.forEach(function (s) { byC[s.course].stf = s; });
    // 上位の決着パターンは、2着〜6着の並びも出す(枠番で)
    scen.slice(0, 8).forEach(function (s) {
      var o = M.order ? M.order(s.i) : null;
      if (!o) return;
      s.ord = o;
      s.ordW = o.order.map(function (c) { return byC[c] ? byC[c].waku : c; });
    });
    return { scen: scen, M: M, race: race };
  }

  // ---- 学習済みの重みがないときの簡易モデル(以前の見立て)
  function analyzeOld(B, W) {
    var aPow = avg(B.map(function (b) { return b.power; })), aSt = avg(B.map(function (b) { return b.stUse; }));
    var aMo = avg(B.map(function (b) { return b.motor2; })), aEx = avg(B.map(function (b) { return b.ex; }));
    B.forEach(function (b) {
      var base = ((V.place[b.course - 1] || [0])[0] || 0) / 100, fc = 1;
      if (b.csNow && base > 0) fc = Math.min(3, Math.max(0.3, ((b.csNow.w1 + SHRINK * base) / (b.csNow.n + SHRINK)) / base));
      var f = fc;
      if (b.power != null && aPow != null) f *= Math.pow(1.25, b.power - aPow);
      if (b.stUse != null && aSt != null) f *= Math.pow(1.15, (aSt - b.stUse) / 0.05);
      if (b.motor2 != null && aMo != null) f *= Math.pow(1.06, (b.motor2 - aMo) / 10);
      if (b.ex != null && aEx != null) f *= Math.pow(1.08, (aEx - b.ex) / 0.05);
      b.factor = f; b.base = base;
    });
    var kw = windKw(W), scen = [];
    B.forEach(function (b) {
      kimDist(b).forEach(function (p, j) {
        if (p > 0) scen.push({ b: b, kim: KIM[j], w: b.base * 100 * b.factor * p * (kw[KIM[j]] || 1) });
      });
    });
    var tot = scen.reduce(function (s, x) { return s + x.w; }, 0) || 1;
    scen.forEach(function (s) { s.p = s.w / tot * 100; });
    scen.sort(function (a, b) { return b.p - a.p; });
    return { scen: scen, M: null };
  }

  function analyze() {
    var B = readState(), W = windState();
    prepBoats(B);
    var R = (PARAMS && MODEL ? analyzeModel(B, W) : null) || analyzeOld(B, W);
    R.B = B; R.wind = W.wind; R.wspd = W.wspd; R.strong = W.strong;
    R.aPow = avg(B.map(function (b) { return b.power; })); R.aSt = avg(B.map(function (b) { return b.stUse; }));
    R.aMo = avg(B.map(function (b) { return b.motor2; })); R.aEx = avg(B.map(function (b) { return b.ex; }));
    B.forEach(function (b) { b.share = R.scen.filter(function (s) { return s.b === b; }).reduce(function (s, x) { return s + x.p; }, 0); });
    return R;
  }

  // 道中の強さ: ゴールで0.6秒差以内だった相手との勝ち負け(競り合い)と、抜きで勝った・抜かれて2着になった回数
  function dochu(b) {
    var cb = b.cb || [0, 0], nk = b.nk || [0, 0], w = cb[0], n = cb[1];
    var rate = (w + 5 * 0.5) / (n + 5);                       // 回数が少ないうちは5割に寄せる
    var parts = [];
    if (n >= 8) parts.push("競り合い(ゴールで0.6秒差以内) " + w + "勝" + (n - w) + "敗" + (rate >= 0.58 ? "で強い" : rate <= 0.42 ? "で弱い" : ""));
    if (nk[0]) parts.push("道中で抜いて1着 " + nk[0] + "回");
    if (nk[1]) parts.push("抜かれて2着 " + nk[1] + "回");
    return { w: w, n: n, rate: rate, text: parts.length ? "道中: " + parts.join("、") + "。" : "" };
  }

  function tier(p) {
    if (p >= 60) return ["イン天国", "1コースの逃げが決まりやすい水面"];
    if (p >= 52) return ["イン有利", "基本は1コース中心で、たまに外が届く水面"];
    if (p >= 45) return ["標準よりやや荒れ", "2〜4コースの差し・まくりも十分ある水面"];
    return ["荒れ水面", "1コースが苦戦しやすく、展開が読みにくい水面"];
  }
  function courseRecord(b) {
    var cs = b.csNow;
    if (!cs || !cs.n) return null;
    return b.course + "コースは直近" + cs.n + "走で1着" + cs.w1 + "回(" + pct(cs.w1, cs.n) + "%)";
  }
  function patName(s) { return s.b.course + "コース" + s.kim; }
  // ---- 裏水面ノート: ura_page.js に渡すもの(直前情報・オッズ・展示の順位など)
  function uraCtx(R) {
    var W = BI && BI.weather && BI.weather.wind != null ? BI.weather : null, pre = false;
    var wind = W ? Math.round(W.wind) : (D.result && D.result.wind != null ? D.result.wind : null);
    var wave = W && W.wave != null ? Math.round(W.wave) : (D.result && D.result.wave != null ? D.result.wave : null);
    if (wind == null && VW) { wind = Math.round(VW.wind); wave = VW.wave != null ? Math.round(VW.wave) : null; pre = true; }
    var exRank = null, exs = R.B.filter(function (b) { return b.ex != null && b.ex > 6 && b.ex < 7.6; });
    if (exs.length >= 4) { exRank = {}; exs.forEach(function (b) { exRank[b.waku] = 1 + exs.filter(function (x) { return x.ex < b.ex - 1e-9; }).length; }); }
    R.B.forEach(function (b) { b.mgGrade = (b.mg || {}).grade || null; });
    return { venue: V.code, vname: V.name, no: D.race.no, name: D.race.name, B: R.B, wind: wind, wave: wave, weatherPre: pre, exRank: exRank,
             place1: V.place && V.place[0] ? V.place[0][0] : null, odds: window.SuimenOdds || null, BI: BI, ready: beforeReady(), finished: finished(), nt: D.nt };
  }
  function uraRender(R) {
    if (!URA || !R || !R.M) return null;
    try { return window.SuimenUraPage.render(R, uraCtx(R)); } catch (e) { if (window.console) console.error(e); return null; }
  }
  function uraScen(R, i) { return R.scen.filter(function (x) { return x.i === i; })[0] || null; }
  function pkText(x) { return x >= 0.995 ? "99%以上" : Math.round(x * 100) + "%"; }   // オッズが全部100倍以上の決着は、ほぼ必ず万舟
  // 裏: 荒れたときの展開(裏本線と、荒れたときにありそうな決着の順。最後に表の本線を比べて出す)
  function renderUraScen(R, lead) {
    var U = R.U, tot = U.scen.reduce(function (a, s) { return a + s.s; }, 0) || 1;
    var list = U.cands.slice(0, 5), om = null;
    U.scen.forEach(function (s) { if (s.c === U.oc && s.k !== "抜き" && (!om || s.p > om.p)) om = s; });
    var max = Math.max.apply(null, list.map(function (c) { return c.s / tot; }).concat([0.01]));
    var rows = list.map(function (c, j) {
      var b = c.b, isL = U.lead && c.i === U.lead.i;
      return '<div class="scen-row' + (isL ? " lead" : "") + '"><span class="waku w' + b.waku + '">' + b.waku + "</span><div><div>" + c.c + "コース" + esc(c.k) +
        (isL ? '<span class="leadtag">裏本線</span>' : "") + '<span class="sub"> ・' + esc(b.name) + "</span></div>" +
        '<div class="bar"><i style="width:' + (c.s / tot / max * 100).toFixed(1) + '%"></i></div>' +
        '<div class="sub">この決着になる見込み ' + (c.p * 100).toFixed(c.p < 0.1 ? 1 : 0) + "%・そのとき万舟 " + pkText(c.pk) + "</div></div>" +
        '<span class="pct">' + Math.round(c.s / tot * 100) + "%</span></div>";
    });
    if (om) rows.push('<div class="scen-row omote"><span class="waku w' + om.b.waku + '">' + om.b.waku + "</span><div><div>" + om.c + "コース" + esc(om.k) +
      '<span class="leadtag omt">表の本線</span><span class="sub"> ・' + esc(om.b.name) + "</span></div>" +
      '<div class="sub">この決着になる見込み ' + Math.round(om.p * 100) + "%・そのとき万舟 " + pkText(om.pk) + "</div></div>" +
      '<span class="pct">' + Math.round(om.s / tot * 100) + "%</span></div>");
    var sc = $("#scen");
    if (sc) sc.innerHTML = rows.join("");
    var sl = $("#scenLead");
    if (sl) sl.textContent = U.lead ? "荒れるとしたら一番ありそうなのは「" + U.lead.c + "コース" + U.lead.k + "」。表の本線(" + U.oc + "コース)以外で、その決着になって、しかも万舟になる見込みが一番高い形です。" +
      "右の数字は、万舟になったとしたら、その決着だった割合の目安です。" : "";
    var p2box = $("#scen2");
    if (p2box) {
      var byCw = {};
      R.B.forEach(function (b) { byCw[b.course] = b; });
      var wins = R.B.slice().map(function (b) {
        return { b: b, v: U.scen.filter(function (s) { return s.c === b.course; }).reduce(function (a, s) { return a + s.s; }, 0) / tot };
      }).sort(function (a, b) { return b.v - a.v; }).map(function (x) {
        return '<span class="cand' + (lead && x.b === lead.b ? " on" : "") + '"><span class="waku w' + x.b.waku + '">' + x.b.waku + "</span>" + Math.round(x.v * 100) + "%</span>";
      }).join("");
      var o = lead && lead.ord;
      function cands(pp) {
        return Object.keys(pp).map(Number).sort(function (a, b) { return pp[b] - pp[a]; }).slice(0, 3).map(function (c) {
          var b = byCw[c]; return '<span class="cand"><span class="waku w' + b.waku + '">' + b.waku + "</span>" + Math.round(pp[c] * 100) + "%</span>";
        }).join("");
      }
      p2box.innerHTML = '<div class="p2row"><span class="lbl">荒れたときの1着</span>' + wins + "</div>" +
        (o ? '<div class="p2row"><span class="lbl">裏本線の2着</span>' + cands(o.p2) + '</div><div class="p2row"><span class="lbl">裏本線の3着</span>' + cands(o.p3) + "</div>" : "");
    }
  }
  // 本線: 1着になる見込み(勝ち方を全部足したもの)が一番高い艇の、一番起こりやすい勝ち方。
  // 1号艇の逃げ1つより、ほかの艇の勝ち方を足した方が高ければ、その艇を本線にする(1号艇以外の本線もはっきり出す)
  function leadScen(R) {
    if (!R || !R.scen || !R.scen.length) return null;
    if (URA && R.U && R.U.lead) {                                   // 裏: 表の本線の艇以外で、その決着になって万舟になる見込みが一番高い決着
      var us = uraScen(R, R.U.lead.i);
      if (us) {
        if (!us.ord && R.M) {
          var o0 = R.M.order(us.i);
          if (o0) { us.ord = o0; us.ordW = o0.order.map(function (c) { var bb = R.B.filter(function (x) { return x.course === c; })[0]; return bb ? bb.waku : c; }); }
        }
        return us;
      }
    }
    var best = null;
    R.B.forEach(function (b) { if (!best || (b.share || 0) > (best.share || 0) + 1e-9) best = b; });
    var ss = best ? R.scen.filter(function (x) { return x.b === best; }) : [];
    var s = ss.filter(function (x) { return x.kim !== "抜き" && x.kim !== "恵まれ"; })[0] || ss[0] || R.scen[0];
    if (s && !s.ord && R.M && s.i != null) {
      var o = R.M.order(s.i);
      if (o) { s.ord = o; s.ordW = o.order.map(function (c) { var bb = R.B.filter(function (x) { return x.course === c; })[0]; return bb ? bb.waku : c; }); }
    }
    return s;
  }

  // ---- スタートの見立て
  function sgn(x) { return (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(3).replace(/^0/, ""); }
  function stReasons(b, R) {
    var s = b.stf, q = s.parts || {}, out = [], n = (b.stx || [0])[0];
    out.push(n ? "平均ST" + st2(b.stx[1] / n) + "(直近1年" + n + "走)" : "STの記録が少ない(全体の平均で見る)");
    if (q.n8 >= 4 && q.r8m != null && Math.abs(q.r8m - b.stx[1] / Math.max(1, n)) >= 0.02)
      out.push("最近は" + (q.r8m < b.stx[1] / n ? "早め" : "遅め") + "(直近" + q.n8 + "走の平均" + st2(q.r8m) + "、" + sgn(q.rec) + "秒)");
    if (s.scale >= 1.2) out.push("STのばらつきが大きい(一発もあるが、出遅れも多い)");
    else if (s.scale <= 0.85 && n >= 10) out.push("STが安定している");
    if (s.fp >= 2) out.push("今期フライング2回(かなり慎重になる。" + sgn(q.f + q.f2) + "秒)");
    else if (s.fp > 0) out.push("今期フライング持ち(慎重になりやすい。" + sgn(q.f) + "秒)");
    var nbRel = (q.nb || 0) - (R.nbMean || 0);               // メンバー全体の傾向とは別に、この艇の両隣だけの分
    if (Math.abs(nbRel) >= 0.004) out.push("両隣が" + (nbRel < 0 ? "スタートの早い選手で、つられて早くなりやすい" : "スタートの遅い選手で、つられて遅くなりやすい") + "(" + sgn(nbRel) + "秒)");
    if (b.course >= 2 && Math.abs(q.course || 0) >= 0.008) out.push(b.course + "コースは" + sgn(q.course) + "秒");
    var ccs = (b.cs || {})[String(b.course)] || {};
    if (Math.abs(q.cdev || 0) >= 0.004 && ccs.st != null) out.push(b.course + "コースでは、ふだんよりSTが" + (q.cdev < 0 ? "早い" : "遅い") + "(このコースの平均ST" + st2(ccs.st) + "・" + (ccs.sn || 0) + "本、" + sgn(q.cdev) + "秒)");
    if (Math.abs(q.exd || 0) >= 0.003) out.push("展示タイムが" + (q.exd < 0 ? "速く、行き足が良さそう" : "遅め") + "(" + sgn(q.exd) + "秒)");
    if (q.wind) out.push("風速" + R.wspd + "m(" + sgn(q.wind) + "秒)");
    var est = estOf(b.waku);
    if (est != null) out.push("展示ST" + (est < 0 ? "F" + st2(-est) : st2(est)) + (Math.abs(q.est || 0) >= 0.003 ? "(" + sgn(q.est) + "秒)" : ""));
    return out;
  }
  function renderStart(R) {
    var box = $("#stBox"), notes = $("#stNotes");
    if (!box) return;
    if (!R.M) { box.innerHTML = '<p class="wait">学習済みの見立てがまだありません。</p>'; return; }
    var B = R.B.slice().sort(function (a, b) { return a.course - b.course; }), M = R.M;
    R.nbMean = avg(B.map(function (b) { return (b.stf.parts || {}).nb || 0; }));
    // 一撃スタートのときに一番起こりやすい決着パターン
    var tops = B.map(function (b) {
      var wb = M.whenBoat(b.course - 1, "out");
      if (!wb) return null;
      var bi = 0;
      wb.p.forEach(function (p, i) { if (p > wb.p[bi]) bi = i; });
      return { c: M.classes[bi][0], k: M.classes[bi][1], p: Math.round(wb.p[bi] * 100) };
    });
    function meter(v) { return '<span class="meter"><i style="width:' + Math.min(100, v * 250).toFixed(0) + '%"></i></span>'; }
    var rows = [];
    rows.push(vrow("コース", B.map(function (b) { return '<b class="cn">' + b.course + "</b>"; })));
    rows.push(vrow("予想ST", B.map(function (b) { return "<b>" + st2(b.stf.mean) + '</b><span class="dim rg">' + st2(b.stf.lo) + "<br>〜" + st2(b.stf.hi) + "</span>"; }),
      B.map(function (b) { return b.stf.mean; }), "min"));
    rows.push(vrow("一撃<br>スタート", B.map(function (b) { return "<b>" + Math.round(b.stf.pOut * 100) + "%</b>" + meter(b.stf.pOut); }),
      B.map(function (b) { return b.stf.pOut; }), "max", "out"));
    rows.push(vrow("凹む", B.map(function (b) { return Math.round(b.stf.pDent * 100) + "%" + meter(b.stf.pDent); }), null, null, "dent"));
    rows.push(vrow("一撃スタート<br>の時の展開", tops.map(function (t) { return t ? '<span class="tx">' + t.c + "コース<br>" + esc(t.k) + "<br><b>" + t.p + "%</b></span>" : "—"; })));
    var head = '<thead><tr><th class="corner"></th>' + B.map(function (b) {
      return '<th class="bw w' + b.waku + '"><span class="bn">' + b.waku + '</span><span class="hn">' + esc(b.name) + femMark(b) + "</span></th>";
    }).join("") + "</tr></thead>";
    box.innerHTML = '<div class="vt-wrap"><table class="vt stv">' + head + "<tbody>" + rows.join("") + "</tbody></table></div>";
    var ven = (B[0].stf.parts || {}).ven || 0;
    notes.innerHTML = B.map(function (b) { return "<li><b>" + b.course + "コース " + esc(b.name) + femMark(b) + "</b>: " + esc(stReasons(b, R).join("、")) + "</li>"; }).join("") +
      (Math.abs(R.nbMean) >= 0.004 ? "<li>" + esc("メンバー全体が" + (R.nbMean < 0 ? "スタートの早い選手ぞろいで、そろって早いスタートになりやすい" : "スタートの遅めの選手が多く、そろって遅めのスタートになりやすい") +
        "(隣の艇につられる分、平均" + sgn(R.nbMean) + "秒)。") + "</li>" : "") +
      (Math.abs(ven) >= 0.005 ? "<li>" + esc(V.name + "は、全体にSTが" + (ven < 0 ? "早く" : "遅く") + "出やすい場です(" + sgn(ven) + "秒)。") + "</li>" : "");
  }

  // 警戒アラート(イン飛び・カドまくり)。スタート展示のあとは、展示の進入と予想ST(展示STを含む)で計算し直す。式は scripts/alerts.py と同じ
  var AL_NAME = { "in": "イン飛び", "kado": "カドまくり" }, AL_LV = { 3: "特別警報", 2: "警報", 1: "注意報" };
  function inAlert(cs1, cs2) {
    if (!cs1 || !cs2 || (cs1.n || 0) < 3 || (cs2.n || 0) < 3) return 0;
    var m = Math.max((cs1.w1 || 0) / cs1.n, (cs2.ng || 0) / cs2.n);
    return m <= 0.25 + 1e-9 ? 3 : m <= 0.33 + 1e-9 ? 2 : m <= 0.40 + 1e-9 ? 1 : 0;
  }
  function makuriTendency(cs4) { cs4 = cs4 || {}; var km = cs4.km || {}; return ((km["捲り"] || 0) + 0.5 * (km["捲り差し"] || 0) + 3 * 0.046) / ((cs4.n || 0) + 3); }
  function renderAlerts(R) {
    var box = $("#alerts");
    if (!box || !R || !R.M || !beforeReady()) return;
    var byC = {};
    R.B.forEach(function (b) { byC[b.course] = b; });
    if (!byC[1] || !byC[2] || !byC[4]) return;
    var al = { "in": inAlert((byC[1].cs || {})["1"], (byC[2].cs || {})["2"]), kado: 0 };
    if (makuriTendency((byC[4].cs || {})["4"]) >= 0.08) {
      var mu = {};
      R.M.st.forEach(function (s) { mu[s.course] = s.mu; });
      var dk = Math.min(mu[1], mu[2], mu[3]) - mu[4];
      al.kado = dk >= 0.02 - 1e-9 ? 3 : dk >= 0.01 - 1e-9 ? 2 : dk >= -1e-9 ? 1 : 0;
    }
    box.innerHTML = ["in", "kado"].filter(function (k) { return al[k]; }).map(function (k) {
      return '<span class="al al-' + k + al[k] + '">' + AL_NAME[k] + " " + AL_LV[al[k]] + "</span>";
    }).join("") + (al["in"] || al.kado ? '<span class="sub">(展示のあとで計算)</span>' : "");
  }

  function render() {
    renderDeadline();
    renderResult();
    renderCard();
    renderTactics();
    renderBefore();
    var ab = absentWakus();
    if (ab.length) { showAbsent(ab); navi(null); return; }
    restoreWait();
    var on = ready();
    setGated(on);
    if (!on) {                                                        // 展開ナビは展示の前でも出す(枠なり・ふだんのST)
      if (URA) { var R0 = analyze(); R0.U = uraRender(R0); }           // 裏: 展示の前の目安(枠なり・ふだんのST)
      navi(null); return;
    }
    var R = analyze(), B = R.B, scen = R.scen;
    if (URA) R.U = uraRender(R);
    navi(R);
    renderAlerts(R);
    function byCourse(c) { return B.filter(function (b) { return b.course === c; })[0]; }
    var p1 = V.place[0][0], t = tier(p1);
    renderStart(R);
    // 展開
    var lead = leadScen(R);
    if (URA && R.U) renderUraScen(R, lead);
    else {
    var top = scen.slice(0, 6), max = top.length ? top[0].p : 1;
    if (lead && top.indexOf(lead) < 0) top = top.slice(0, 5).concat([lead]);
    $("#scen").innerHTML = top.map(function (s) {
      return '<div class="scen-row' + (s === lead ? " lead" : "") + '"><span class="waku w' + s.b.waku + '">' + s.b.waku + '</span><div><div>' + patName(s) +
        (s === lead ? '<span class="leadtag">本線</span>' : "") + '<span class="sub"> ・' + esc(s.b.name) + '</span></div><div class="bar"><i style="width:' + (s.p / max * 100).toFixed(1) +
        '%"></i></div></div><span class="pct">' + s.p.toFixed(0) + "%</span></div>";
    }).join("");
    var b1L = byCourse(1), nige = scen.filter(function (x) { return x.b === b1L && x.kim === "逃げ"; })[0];
    $("#scenLead").textContent = !lead ? "" : lead.b.course === 1 ? "本線は「" + patName(lead) + "」。上位6つの決着パターンと、起こりやすさの目安です。" :
      "本線は「" + patName(lead) + "」。" + lead.b.waku + "号艇が1着になる見込み(勝ち方を全部足して" + Math.round(lead.b.share) + "%)が、" +
      (b1L ? b1L.waku + "号艇(" + Math.round(b1L.share) + "%" + (nige ? "。うち逃げ" + Math.round(nige.p) + "%" : "") + ")" : "1コース") + "より高いので、本線にしています。";
    var p2box = $("#scen2");
    if (p2box) {
      // 本線のときの2着・3着の候補(確率)
      var o = lead && lead.ord, byCw = {};
      B.forEach(function (b) { byCw[b.course] = b; });
      function cands(pp) {
        return Object.keys(pp).map(Number).sort(function (a, b) { return pp[b] - pp[a]; }).slice(0, 3).map(function (c) {
          var b = byCw[c]; return '<span class="cand"><span class="waku w' + b.waku + '">' + b.waku + "</span>" + Math.round(pp[c] * 100) + "%</span>";
        }).join("");
      }
      var wins = B.slice().sort(function (a, b) { return (b.share || 0) - (a.share || 0); }).map(function (b) {
        return '<span class="cand' + (lead && b === lead.b ? " on" : "") + '"><span class="waku w' + b.waku + '">' + b.waku + "</span>" + Math.round(b.share || 0) + "%</span>";
      }).join("");
      p2box.innerHTML = '<div class="p2row"><span class="lbl">1着の見込み</span>' + wins + "</div>" +
        (o ? '<div class="p2row"><span class="lbl">本線の2着</span>' + cands(o.p2) + '</div><div class="p2row"><span class="lbl">本線の3着</span>' + cands(o.p3) + "</div>" : "");
    }
    }
    // ポイント
    var pts = [];
    var b1 = byCourse(1), b2 = byCourse(2), b3 = byCourse(3), b4 = byCourse(4);
    if (b1) {
      var rec = courseRecord(b1);
      if (b1.share >= 55) pts.push("1コース" + b1.name + "が逃げる形が濃厚。" + V.name + "は" + t[0] + "(1コース1着率" + fmt(p1) + "%)。" + (rec ? rec + "。" : ""));
      else if (b1.share >= 40) pts.push("1コース" + b1.name + "が中心だが、絶対ではない。スタートで遅れると2コースの差しや捲りが届く。" + (rec ? rec + "。" : ""));
      else pts.push("1コース" + b1.name + "は数字的に苦しい。外からの攻めで主導権を取られる可能性が高い。" + (rec ? rec + "。" : ""));
    }
    if (R.M) {
      // スタートの見立てから: 凹みそうな艇と、出そうな艇
      var dent = B.filter(function (b) { return b.course >= 2 && b.course <= 4 && b.stf.pDent >= 0.15; }).sort(function (a, b) { return b.stf.pDent - a.stf.pDent; })[0];
      if (dent) pts.push(dent.course + "コース" + dent.name + "は凹む確率" + Math.round(dent.stf.pDent * 100) + "%。凹むと外の" + (dent.course + 1) +
        "コースが" + (dent.course === 2 ? "まくり差し" : "捲り") + "で攻めやすくなる。");
      var outB = B.filter(function (b) { return b.course >= 2 && b.stf.pOut >= 0.15; }).sort(function (a, b) { return b.stf.pOut - a.stf.pOut; })[0];
      if (outB) pts.push(outB.course + "コース" + outB.name + "は一撃スタートの確率" + Math.round(outB.stf.pOut * 100) + "%。" +
        (outB.course === 2 ? "1コースより先に出ると、ジカまくりも。" : outB.course === 4 ? "カドから一撃なら、絞ってのカドまくり。" : "一撃なら内を絞って攻める。"));
    } else if (b2 && b3 && b2.stUse != null && b3.stUse != null && b2.stUse - b3.stUse >= 0.03) {
      pts.push("2コースの平均ST(" + fmt(b2.stUse, 2) + ")が3コース(" + fmt(b3.stUse, 2) + ")より遅い。2コースが凹むと、3コースのまくりが入りやすい。");
    }
    if (b2 && b1 && b2.power != null && b1.power != null && b2.power > b1.power + 0.5)
      pts.push("2コース" + b2.name + "の方が1コースより勝率が上。差しが決まる場面に注意。");
    if (!R.M && b4 && R.aSt != null && b4.stUse != null && b4.stUse <= R.aSt - 0.02)
      pts.push("4コース(カド)" + b4.name + "はスタートが速い(平均ST" + fmt(b4.stUse, 2) + ")。内が凹めばカドまくりの展開。");
    // 道中: 本線のときの2着争い(着順のモデル)。拮抗していれば2マークの競りになりやすい
    if (lead && lead.ord) {
      var byCw2 = {};
      B.forEach(function (b) { byCw2[b.course] = b; });
      var c2 = Object.keys(lead.ord.p2).map(Number).sort(function (a, b) { return lead.ord.p2[b] - lead.ord.p2[a]; });
      var x1 = byCw2[c2[0]], x2 = byCw2[c2[1]], q1 = lead.ord.p2[c2[0]], q2 = lead.ord.p2[c2[1]];
      if (x1 && x2) {
        var d1 = dochu(x1), d2 = dochu(x2);
        var rec = function (b, d) { return d.n >= 6 ? b.waku + "号艇は僅差の競り合い" + d.w + "勝" + (d.n - d.w) + "敗" : ""; };
        var tail = [rec(x1, d1), rec(x2, d2)].filter(Boolean).join("、");
        if (q1 - q2 < 0.12) pts.push("本線(" + patName(lead) + ")のときの2着争いは、" + x1.waku + "号艇(" + Math.round(q1 * 100) + "%)と" + x2.waku + "号艇(" + Math.round(q2 * 100) +
          "%)が拮抗。1周2マークで競りになりやすい" + (tail ? "(" + tail + ")" : "") + "。");
        else pts.push("本線(" + patName(lead) + ")のときの2着は、" + x1.waku + "号艇が有力(" + Math.round(q1 * 100) + "%)。次が" + x2.waku + "号艇(" + Math.round(q2 * 100) + "%)。");
      }
    }
    // 道中: 2マーク以降の競り合いに強い艇・弱い艇、抜いて着を上げる・抜かれる可能性
    var dws = B.map(function (b) { return { b: b, d: dochu(b) }; }).filter(function (x) { return x.d.n >= 8; });
    var strongD = dws.filter(function (x) { return x.d.rate >= 0.58; }).sort(function (a, b) { return b.d.rate - a.d.rate; })[0];
    var weakD = dws.filter(function (x) { return x.d.rate <= 0.42; }).sort(function (a, b) { return a.d.rate - b.d.rate; })[0];
    if (strongD) pts.push("1周2マーク以降で競り合いになれば、" + strongD.b.course + "コース" + strongD.b.name + "が強い(ゴールで僅差だった相手に" +
      strongD.d.w + "勝" + (strongD.d.n - strongD.d.w) + "敗)。後ろからでも2マークで着を上げる可能性。");
    if (weakD) pts.push(weakD.b.course + "コース" + weakD.b.name + "は競り合いで負けやすい(僅差の相手に" + weakD.d.w + "勝" + (weakD.d.n - weakD.d.w) +
      "敗)。1マークを前で回っても、道中で抜かれる可能性。");
    var mTop = B.filter(function (b) { return b.motor2 != null; }).sort(function (a, b) { return b.motor2 - a.motor2; })[0];
    if (mTop && R.aMo != null && mTop.motor2 >= R.aMo + 8) pts.push("モーターは" + mTop.course + "コース" + mTop.name + "(2連率" + fmt(mTop.motor2) + "%)が抜けている。道中で伸びてくる可能性。");
    var eTop = B.filter(function (b) { return b.ex != null; }).sort(function (a, b) { return a.ex - b.ex; })[0];
    if (eTop && R.aEx != null && eTop.ex <= R.aEx - 0.04) pts.push("展示タイムは" + eTop.course + "コース" + eTop.name + "(" + fmt(eTop.ex, 2) + ")が一番。当日の足は良さそう。");
    var moved = B.filter(function (b) { return b.course !== b.waku; });
    if (moved.length) pts.push("進入は枠なりではない(" + moved.map(function (b) { return b.waku + "号艇→" + b.course + "コース"; }).join("、") + ")。");
    if (R.strong && R.wind === "head") pts.push("向かい風" + R.wspd + "m。内が伸びにくく、まくりが決まりやすい条件(目安)。");
    if (R.strong && R.wind === "tail") pts.push("追い風" + R.wspd + "m。1マークで流れやすく、差しが入りやすい条件(目安)。");
    if (R.wspd >= 6) pts.push("風速" + R.wspd + "mは強め。STが全体に遅れ、ばらつきも大きくなる。旋回の上手さと経験の差が出やすい。");
    if (!URA) $("#points").innerHTML = pts.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("");
    // 各艇
    var boatsBox = $("#boats");
    if (boatsBox) boatsBox.innerHTML = B.slice().sort(function (a, b) { return a.course - b.course; }).map(function (b) {
      var c = b.course - 1, k = V.kimarite[c] || [];
      var best = k.map(function (p, j) { return [p, KIM[j]]; }).filter(function (x) { return x[0] > 0; }).sort(function (a, b) { return b[0] - a[0]; })[0];
      var li = [];
      li.push(V.name + "の" + b.course + "コース1着率は" + fmt(V.place[c][0]) + "%。勝つときは「" + (best ? best[1] : "—") + "」が最多。");
      var rec = courseRecord(b);
      li.push(rec ? rec + "。" : b.course + "コースの直近の成績はまだありません。");
      var tt = tacType(b.csNow);
      if (b.course >= 2 && tt.text) li.push(b.course + "コースで勝ったときの決まり手は " + tt.text + (tt.type ? "(" + tt.type + ")" : "") + "。");
      if (b.course === 1 && b.csNow && b.csNow.ls) {
        var LN = { "差し": "差され", "捲り": "捲られ", "捲り差し": "捲り差され" };
        var lsTxt = ["差し", "捲り", "捲り差し"].filter(function (k) { return b.csNow.ls[k]; }).map(function (k) { return LN[k] + b.csNow.ls[k]; }).join("・");
        if (lsTxt) li.push("1コースで負けたときは " + lsTxt + "。");
      }
      if (b.power != null && R.aPow != null) { var d = b.power - R.aPow; li.push(d >= 0.8 ? "このメンバーでは勝率が上位。" : d <= -0.8 ? "このメンバーでは勝率が下位。展開の助けが必要。" : "勝率はメンバーの中で平均的。"); }
      if (b.stf) li.push("予想ST" + st2(b.stf.mean) + "。一撃スタート" + Math.round(b.stf.pOut * 100) + "%・凹む" + Math.round(b.stf.pDent * 100) + "%。");
      else if (b.stUse != null && R.aSt != null) { var ds = R.aSt - b.stUse; if (ds >= 0.02) li.push("STが速い(" + fmt(b.stUse, 2) + ")。先手を取れる。"); else if (ds <= -0.02) li.push("STが遅め(" + fmt(b.stUse, 2) + ")。スタートで後手に回りやすい。"); }
      if (b.local && b.rate) { var dl = b.local - b.rate; if (dl >= 0.4) li.push("当地勝率が全国より高い。この水面は得意。"); else if (dl <= -0.4) li.push("当地勝率が全国より低い。この水面は苦手寄り。"); }
      var dw = dochu(b);
      if (dw.text) li.push(dw.text);
      var grid = [1, 2, 3, 4, 5, 6].map(function (cn) {
        var cs = (b.cs || {})[String(cn)];
        return '<div class="' + (cn === b.course ? "cur" : "") + '">' + cn + "<b>" + (cs && cs.n ? pct(cs.w1, cs.n) + "%" : "—") + "</b>" + (cs && cs.n ? cs.n + "走" : "") + "</div>";
      }).join("");
      return '<div class="boat"><h3><span class="waku w' + b.waku + '">' + b.waku + "</span>" + esc(b.name) + femMark(b) + '<span class="tag">' + b.course + "コース</span>" +
        '<span class="sub">勝ち筋 ' + b.share.toFixed(0) + '%</span></h3><div class="courses" aria-label="コース別1着率">' + grid + "</div><ul>" +
        li.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>";
    }).join("");
    // 解説文
    var r = D.race, lines = ["【" + V.name + r.no + "R 展開メモ】", V.name + "は1コース1着率" + fmt(p1) + "%の" + t[0] + "。"];
    if (lead) lines.push("本線は" + lead.b.course + "コース" + lead.b.name + "の「" + lead.kim + "」。");
    var second = lead ? scen.filter(function (s) { return s.b !== lead.b; })[0] : null;
    if (second) lines.push("対抗の展開は" + second.b.course + "コース" + second.b.name + "の「" + second.kim + "」。");
    pts.slice(1, 3).forEach(function (p) { lines.push(p); });
    lines.push("", "※データから見た展開の目安です。舟券の推奨ではありません。", "#ボートレース #" + V.name);
    if (!URA) $("#post").value = lines.join("\n");
    updateView(R);
  }

  // ---- 1周1マーク展開ビュー(turn1.js)。展開の見立てと同じ決着パターンで、そのパターンになりやすいSTの組み合わせで動かす
  var view = null, viewSig = "", patKey = "", patIdx = 0, pats = [], lastR = null, viewTimer = null, started = false, wasPlaying = false;
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function viewTitle() { return V.name + " " + D.race.no + "R 1周1マーク"; }
  function entriesFor(R, stByCourse, courseByWaku) {
    return R.B.map(function (b) {
      var course = courseByWaku ? courseByWaku[b.waku] : b.course;
      var c = (courseByWaku ? (b.cs || {})[String(course)] : b.csNow) || {}, st = stByCourse ? stByCourse[course - 1] : b.stUse;
      return { waku: b.waku, course: course, name: b.name, st: st == null ? b.stUse : Math.round(st * 100) / 100, motor2: b.motor2, ex: b.ex,
               cls: b.cls, km: c.km, ls: c.ls, n: c.n, w1: c.w1 };
    });
  }
  function scenOf(i) {
    var s = pats[i];
    return { course: s.b.course, kim: s.kim, p: s.p, order: s.ord ? s.ord.order : null };
  }
  var custom = null;                 // 展開ナビで選んだ展開 {w: 軸の枠, k: 決まり手, a: 2着の枠, b: 3着の枠}。上の決着パターンを押すと戻る
  function customScen(R) {
    if (!custom || !R || !R.M) return null;
    var bw = nvBoat(R, custom.w), ba = nvBoat(R, custom.a), bb = custom.b ? nvBoat(R, custom.b) : null;
    var i = bw ? nvClass(bw.course, custom.k) : null;
    if (i == null || !ba) return null;
    var o = R.M.order(i);
    if (!o) return null;
    var head = [bw.course, ba.course].concat(bb ? [bb.course] : []);
    return { i: i, sc: { course: bw.course, kim: custom.k, p: nvP(R, i), chosen: true, order: head.concat(o.order.slice(1).filter(function (c) { return head.indexOf(c) < 0; })) } };
  }
  function current() {
    var cs = customScen(lastR);
    if (cs) return { sc: cs.sc, ents: entriesFor(lastR, lastR.M.postST(cs.i)) };
    custom = null;
    var s = pats[patIdx], post = lastR.M ? lastR.M.postST(s.i) : null;
    return { sc: scenOf(patIdx), ents: entriesFor(lastR, post) };
  }
  // ---- 1周1マークの見出し: 映像の展開を一言でまとめる(勝った艇の勝ち方・攻めた艇・止めた艇・続く艇から)。字の形と色は展開に合わせる
  function hlName(b) { return '<b class="hb hb' + b.waku + '">' + b.waku + "号艇" + esc(String(b.name || "").replace(/[\s　]+/g, "")) + "</b>"; }
  function headline(P) {
    if (!P || !P.boats || !P.labels || !P.labels.order || !P.labels.order.length) return null;
    var B = P.boats, W = P.labels.order[0], byC = {}, p = P.sc && P.sc.p != null ? +P.sc.p : null;
    var kind = (P.labels.byCourse[W.course] || {}).kind || P.want;
    B.forEach(function (b) { byC[b.course] = b; });
    var b1 = byC[1], kado = B.filter(function (b) { return b.dash; }).sort(function (a, b) { return a.course - b.course; })[0];
    var att = B.filter(function (b) { return (b.role === "makuri" || b.role === "nidan") && b !== W; }).sort(function (a, b) { return a.course - b.course; })[0];
    var kabe = B.filter(function (b) { return b.role === "kabe"; })[0];
    var sec = P.labels.order[1] || null, nW = hlName(W), text, theme;
    if (W.course === 1 && (kind === "nige" || !kind)) {
      if (att && kabe) { text = hlName(kabe) + "が" + att.waku + "号艇の攻めを止める！" + nW + "の逃げ切り"; theme = "guard"; }
      else if (att) { text = hlName(att) + "の捲り警戒も、" + nW + (b1 && b1.role === "nigeHari" ? "が張って逃げ切り！" : "の逃げ切り！"); theme = "guard"; }
      else if (p != null && p >= 55) { text = nW + "、楽勝の逃げ切り"; theme = "easy"; }
      else if (sec && sec.course === 2) { text = hlName(sec) + "の差しを振り切って、" + nW + "の逃げ切り！"; theme = "nige"; }
      else { text = nW + "が先マイ、そのまま逃げ切り！"; theme = "nige"; }
    } else if (kind === "makuri") {
      var F = byC[W.course + 1], fol = F && (F.role === "makurizashi" || F.role === "mark") ? F : null;
      var head = W === kado ? "カドから攻める" + nW + "！" : W.course === 2 ? nW + "のジカ捲り！" :
        (b1 && b1.role === "hari" ? "1号艇の張りを越えて、" + nW + "の捲り一発！" : nW + "、豪快に捲る！");
      text = head + (fol ? (fol.role === "makurizashi" ? "それに" + hlName(fol) + "のまくり差しチャンス！" : hlName(fol) + "もついて行く！") : "");
      theme = "makuri";
    } else if (kind === "makurizashi") {
      var O = (W.over || []).slice().sort(function (a, b) { return b.course - a.course; })[0];   // 前を横切った艇のうち、すぐ内の艇
      if (att) text = hlName(att) + "の捲りに乗って、" + nW + "のまくり差し！";
      else if (O) text = nW + "が" + O.waku + "号艇の前を横切って、まくり差し！";
      else text = nW + "のまくり差しが決まる！";
      theme = "mz";
    } else {
      if (att) text = hlName(att) + "の攻めで空いた内を、" + nW + "が差す！";
      else if (b1 && b1 !== W && (b1.role === "hari" || b1.role === "zensoku" || b1.flowOut)) text = "1号艇が流れた内を、" + nW + "が差し切る！";
      else text = nW + "が鋭く差し切る！";
      theme = "sashi";
    }
    if (p != null && p < 8 && theme !== "easy") theme += " upset";       // 起こりにくい展開(波乱)
    return { html: text.replace(/!/g, "！"), theme: theme };
  }
  function paintHead() {
    var hl = $("#t1Head");
    if (!hl) return;
    var h = headline(view && view.plan ? view.plan() : null);
    hl.hidden = !h;
    if (h) { hl.innerHTML = h.html; hl.className = "t1hl " + h.theme.split(" ").map(function (t) { return "hl-" + t; }).join(" "); }
  }
  function paintNote() {                                           // 展開ナビで選んだ展開を再生しているときの説明(映像の並びが選んだ並びと違えば、そう書く)
    paintHead();
    var note = $("#t1Note");
    if (note) {
      note.hidden = !custom;
      if (custom) {
        var got = "", P = view && view.plan ? view.plan() : null;
        if (P && P.order && lastR) {
          var wOf = function (c) { var b = lastR.B.filter(function (x) { return x.course === c; })[0]; return b ? b.waku : c; };
          var g1 = wOf(P.order[0]), g2 = wOf(P.order[1]), g3 = wOf(P.order[2]);
          if (g1 !== custom.w) got = "(この形の映像は作れず、映像では1着が" + wk(g1) + "になっています)";
          else if (g2 !== custom.a) got = "(この位置関係では選んだ並びに合わせきれず、映像では2着" + wk(g2) + "・3着" + wk(g3) + "になっています)";
          else if (custom.b && g3 !== custom.b) got = "(3着までは合わせきれず、映像では3着が" + wk(g3) + "になっています)";
        }
        note.innerHTML = "展開ナビで選んだ展開を再生しています: " + wk(custom.w) + "の" + esc(custom.k) + "、2着" + wk(custom.a) + (custom.b ? "、3着" + wk(custom.b) : "") + "。" + got +
          "下の決着パターンを押すと、見立ての上位に戻ります。";
      }
    }
  }
  function drawPats() {
    var box = $("#t1Pats");
    if (!box) return;
    paintNote();
    box.innerHTML = pats.map(function (s, i) {
      var on = !custom && i === patIdx;
      return '<button type="button" class="pat' + (on ? " on" : "") + '" data-i="' + i + '" aria-pressed="' + on + '"><span class="waku w' + s.b.waku + '">' + s.b.waku + "</span>" +
        '<span class="pn">' + (URA && i === 0 && lastR && lastR.U && lastR.U.lead && lastR.U.lead.i === s.i ? '<i class="ubtag">裏本線</i>' : "") + s.b.course + "コース " + s.kim + "</span>" +
        '<span class="p">' + s.p.toFixed(s.p < 10 ? 1 : 0) + "%" + (URA && lastR && lastR.U ? '<small class="upk">万舟' + pkText((lastR.U.scen[s.i] || {}).pk || 0) + "</small>" : "") + "</span></button>";
    }).join("");
  }
  var pendingR = null;
  function drawWaiting() {                                         // 映像ができるまでの表示
    var c = $("#t1view");
    if (!c || view) return;
    var dpr = Math.min(2, window.devicePixelRatio || 1), w = c.clientWidth || 640;
    c.width = Math.round(w * dpr); c.height = Math.round(c.width * 10 / 16);
    var g = c.getContext("2d");
    g.fillStyle = "#0b4d63"; g.fillRect(0, 0, c.width, c.height);
    g.fillStyle = "rgba(255,255,255,0.85)"; g.font = Math.round(c.width / 26) + "px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText("映像を作っています…", c.width / 2, c.height / 2);
  }
  function updateView(R) {
    lastR = R;
    var canvas = $("#t1view"), pane = $("#pane-t1");
    if (!canvas || !window.Turn1) return;
    if (pane && pane.hidden) { pendingR = R; return; }                   // 1S1Mのタブを開いたときに作る(ページを軽くするため)
    pendingR = null;
    var ld = leadScen(R);
    if (URA && R.U) {                                                   // 裏: 裏本線から、荒れたときにありそうな順(その決着になって万舟になる見込み)
      pats = ld && ld.kim !== "抜き" && ld.kim !== "恵まれ" ? [ld] : [];
      R.U.cands.forEach(function (c) { var s = uraScen(R, c.i); if (s && pats.length < 4 && pats.indexOf(s) < 0 && s.kim !== "抜き" && s.kim !== "恵まれ") pats.push(s); });
    } else {
    pats = R.scen.filter(function (s) { return s.kim !== "抜き" && s.kim !== "恵まれ" && s !== ld; }).slice(0, ld ? 3 : 4);
    if (ld && ld.kim !== "抜き" && ld.kim !== "恵まれ") pats.unshift(ld);                    // 本線(1着の見込みが一番高い艇)を最初に
    }
    if (!pats.length) return;
    var pk = pats.map(function (s) { return s.b.waku + s.kim; }).join(",");
    if (pk !== patKey) { patKey = pk; patIdx = 0; }
    drawPats();
    var cur = current(), sig = JSON.stringify([cur.sc.course, cur.sc.kim, cur.sc.order, cur.ents.map(function (e) { return [e.waku, e.course, e.st, e.ex]; })]);
    if (sig === viewSig) return;
    viewSig = sig;
    if (!view) {
      view = Turn1.mount(canvas, { entries: cur.ents, scen: cur.sc, title: viewTitle(), kimarite: V.kimarite, brand: URA ? "裏水面ノート" : "水面ノート", fixedST: !!cur.fixed,
                                   onEnd: function () { var b = $("#t1Pause"); if (b) b.textContent = "再生"; } });
      watch(canvas);
      paintNote();
    } else {
      clearTimeout(viewTimer);
      viewTimer = setTimeout(function () { view.setScenario(cur.sc, cur.ents, viewTitle(), !!cur.fixed); paintNote(); $("#t1Pause").textContent = "一時停止"; }, 700);
    }
  }
  function showNow() {
    var cur = current();
    viewSig = JSON.stringify([cur.sc.course, cur.sc.kim, cur.sc.order, cur.ents.map(function (e) { return [e.waku, e.course, e.st, e.ex]; })]);
    drawPats();
    view.setScenario(cur.sc, cur.ents, viewTitle(), !!cur.fixed); paintNote(); started = true; $("#t1Pause").textContent = "一時停止";
  }
  // 画面に見えたら再生し、見えなくなったら止める(電池と動作の重さのため)
  function watch(canvas) {
    if (reduceMotion) { view.seek(2.6); $("#t1Pause").textContent = "再生"; return; }
    if (!("IntersectionObserver" in window)) { view.play(); started = true; return; }
    new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting) {
          if (!started) { started = true; view.play(); $("#t1Pause").textContent = "一時停止"; }
          else if (wasPlaying) { view.play(); wasPlaying = false; }
        } else if (view.isPlaying()) { wasPlaying = true; view.pause(); }
      });
    }, { threshold: 0.35 }).observe(canvas);
  }
  function download(blob, name) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 5000);
  }
  function setupViewControls() {
    var pBox = $("#t1Pats"), pause = $("#t1Pause"), slow = $("#t1Slow"), save = $("#t1Save"), msg = $("#t1Msg"), out = $("#t1Out");
    if (!pBox) return;
    pBox.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-i]");
      if (!b || !view) return;
      var k = b.getAttribute("data-i");
      patIdx = +k; custom = null;
      showNow();
    });
    $("#t1Replay").addEventListener("click", function () { if (view) { view.replay(); started = true; pause.textContent = "一時停止"; } });
    pause.addEventListener("click", function () {
      if (!view) return;
      if (view.isPlaying()) { view.pause(); pause.textContent = "再生"; } else { view.play(); started = true; pause.textContent = "一時停止"; }
    });
    slow.addEventListener("click", function () {
      var on = slow.getAttribute("aria-pressed") !== "true";
      slow.setAttribute("aria-pressed", String(on)); slow.classList.toggle("on", on); if (view) view.setSpeed(on ? 0.5 : 1);
    });
    // 動画の保存: 録画(実際の長さぶん時間がかかる)→ 共有ボタン(Xなどへ)と保存ボタンを出す
    save.addEventListener("click", function () {
      if (!view) return;
      save.disabled = true; out.hidden = true; out.innerHTML = "";
      msg.textContent = "動画を作っています(約" + Math.round(view.duration()) + "秒)。この画面のままお待ちください。";
      view.record().then(function (blob) {
        var mp4 = blob.type.indexOf("mp4") >= 0, no = ("0" + D.race.no).slice(-2);
        var name = "suimen-" + D.race.date.replace(/-/g, "") + "-" + V.code + "-" + no + "R." + (mp4 ? "mp4" : "webm");
        var file = typeof File !== "undefined" ? new File([blob], name, { type: blob.type }) : null;
        var canShare = file && navigator.canShare && navigator.canShare({ files: [file] });
        out.innerHTML = (canShare ? '<button class="primary" type="button" id="t1Share">共有する</button>' : "") +
          '<button type="button" id="t1Dl">端末に保存</button>';
        out.hidden = false;
        if (canShare) $("#t1Share").addEventListener("click", function () {
          navigator.share({ files: [file], title: viewTitle(), text: V.name + D.race.no + "R 1周1マークの展開シミュレーション #ボートレース #" + V.name }).catch(function () {});
        });
        $("#t1Dl").addEventListener("click", function () { download(blob, name); });
        msg.textContent = mp4 ? "動画ができました(MP4)。" : "動画ができました(WebM形式)。Xに投稿するときは、MP4への変換が必要な場合があります。";
      }).catch(function () {
        msg.textContent = "このブラウザでは動画を作れませんでした。iPhoneのSafariか、パソコンのChromeでお試しください。";
      }).then(function () { save.disabled = false; pause.textContent = view.isPlaying() ? "一時停止" : "再生"; });
    });
  }

  // ---- 展開ナビ: 軸艇と戦術(決まり手)を選ぶと、そのときの2着・3着の考えられる展開を、言葉・確率・データで並べる
  //      確率は見立てのモデル(model.js)の、その決着パターンになったときの着順の見立て。全国の過去1年の割合も並べる
  var NV = { w: null, k: null }, naviR = null, naviPending = false;
  var NV_KS = ["逃げ", "差し", "捲り", "捲り差し", "抜き"];
  var NV_DESC = {
    "逃げ": "1コースが先にターンして、そのまま先頭に立つ",
    "差し": "内の艇がターンした、その内側を突いて先頭に立つ",
    "捲り": "内の艇より先に出て、外から内の艇を叩いて先頭に立つ",
    "捲り差し": "捲りに行った艇の内側から、さらに内の艇との間を突いて先頭に立つ",
    "抜き": "1マークは先頭でなくても、2マーク以降の道中で逆転する"
  };
  var NV_LS = { "差し": "差され", "捲り": "捲られ", "捲り差し": "捲り差され" };
  function nvBoat(R, waku) { return R ? R.B.filter(function (b) { return b.waku === waku; })[0] || null : null; }
  function nvClass(c, k) { var i = MODEL && MODEL.CI ? MODEL.CI[c + k] : null; return i == null ? null : i; }
  function nvP(R, i) { var s = R.scen.filter(function (x) { return x.i === i; })[0]; return s ? s.p : 0; }        // %(このレースの決着全体の中で)
  function pTxt(p) { return p < 1 ? "1%未満" : Math.round(p) + "%"; }
  function wk(w) { return '<span class="waku w' + w + '">' + w + "</span>"; }
  function surname(n) { return String(n || "").split(/[ 　]/)[0]; }
  function lean(b, c, a, x) {                       // このコースで、a の動き(2着の時・勝った時)の方が x より多いか(a・x は決まり手の並び)
    var cs = (b.cs || {})[String(c)] || {}, s2 = cs.s2 || {}, km = cs.km || {};
    function n(ks) { return ks.reduce(function (s, k) { return s + (s2[k] || 0) + (km[k] || 0); }, 0); }
    return n(a) > n(x);
  }
  // 2着・3着の艇の動きを言葉にする(1着の艇のコース w・決まり手 k と、その艇のコース c の位置関係から)
  function nvPhrase(k, w, c, b, rank) {
    var d = c - w, pos = rank === 3 ? "3番手" : "2番手";
    if (k === "逃げ") {
      if (c === 2) return "差して内から" + pos + "に続く";
      if (c === 3) return (lean(b, 3, ["捲り差し"], ["捲り"]) ? "捲り差しで" : "外から攻めて") + pos + "に";
      if (c === 4) return "カドから攻めて" + pos + "に";
      return "外から展開を突いて" + pos + "に";
    }
    if (k === "差し") {
      if (c === 1) return "差されたが、しっかり回って残す";
      if (d < 0) return "内で粘って残す";
      if (d === 1) return "捲って外から" + pos + "に";
      if (d === 2) return "さらに内を差して" + pos + "に";
      return "外から展開を突いて" + pos + "に";
    }
    if (k === "捲り") {
      if (c === 1) return "捲られながらも残す";
      if (d === -1 && c === 2) return "内を差して残す";
      if (d === -1) return "絞られてターンが苦しいが、粘って残す";
      if (d < -1) return "内を差して残す";
      if (d === 1) return lean(b, c, ["捲り差し", "差し"], ["捲り"]) ? "捲り差しで内に切り込んで" + pos + "に" : "捲りについて行って(マーク)" + pos + "に";
      if (d === 2) return "内の艇が流れて空いた最内を差して" + pos + "に";
      return "大外から展開を突いて" + pos + "に";
    }
    if (k === "捲り差し") {
      if (c === 1) return "内で回って残す";
      if (d === -1) return "捲りに行った艇が外から残す";
      if (d < -1) return "内で回って残す";
      if (d === 1) return "続いて差して" + pos + "に";
      return "外から展開を突いて" + pos + "に";
    }
    if (w !== 1 && c === 1) return "1マークは先頭も、道中で抜かれる";
    return "道中の競り合いで" + pos + "に";
  }
  // スタートの形: その決着パターンになるときのST(平均)から
  function nvStartText(k, w, post) {
    if (!post) return "";
    var t = function (c) { return post[c - 1]; }, s = function (c) { return st2(t(c)); };
    var inner = [], j;
    for (j = 1; j < w; j++) inner.push(t(j));
    var minIn = inner.length ? Math.min.apply(null, inner) : null;
    if (k === "逃げ") {
      var g = Math.min(t(2), t(3)) - t(1);
      return "1コースのSTが" + s(1) + "。" + (g >= 0.01 ? "2・3コースより" + g.toFixed(2).replace(/^0/, "") + "秒早く出て、先にターンする形。" : g <= -0.01 ? "2・3コースに少し遅れても、内から先に回って押し切る形。" : "2・3コースとほぼ並んで出て、内から先にターンする形。");
    }
    if (k === "捲り") {
      var gm = minIn - t(w);
      return w + "コースのSTが" + s(w) + "で、内の艇より" + (gm > 0 ? gm.toFixed(2).replace(/^0/, "") + "秒早く" : "遅れずに") + "出て、内を叩きに行く形。";
    }
    if (k === "差し") {
      if (w >= 3) {
        var in2 = Math.min.apply(null, inner.slice(0, w - 2));
        if (t(w - 1) <= in2 - 0.015) return "内の" + (w - 1) + "コース(" + s(w - 1) + ")が先に出て攻め、空いた内を差す形。";
      }
      if (w <= 5 && t(w + 1) <= Math.min(minIn, t(w)) - 0.015) return "外の" + (w + 1) + "コース(" + s(w + 1) + ")が攻めて、その内を差す形。";
      return "そろったスタート(" + w + "コース" + s(w) + ")から、内の艇のターンの内側を差す形。";
    }
    if (k === "捲り差し") {
      if (w >= 3 && t(w - 1) <= Math.min(t(w - 2), t(w)) - 0.015) return "内の" + (w - 1) + "コース(" + s(w - 1) + ")が先に出て捲りに行き、その内を突く形。";
      return w + "コース(" + s(w) + ")が内へ切り込み、内の艇の間を突く形。";
    }
    return "1マークでは決まらず、2マーク以降で逆転する形。";
  }
  // 2着・3着の艇の総評: 着順の見立ての項目ごとの点数を、分かる言葉にまとめる(大きいものから)
  function nvTags(pt) {
    if (!pt) return "";
    var g = { "スタート": (pt.st || 0) + (pt.st_mk || 0) + (pt.st_sa || 0) + (pt.st_ms || 0) + (pt.st_p1 || 0) + (pt.st_p1mk || 0),
              "力": pt.str || 0, "展示": pt.ex || 0, "モーター": pt.mot || 0, "このコースの成績": (pt.c2 || 0) + (pt.top3 || 0),
              "当地": pt.loc || 0, "前づけでダッシュ有利": pt.mz_dash || 0 };
    var xs = Object.keys(g).filter(function (n) { return Math.abs(g[n]) >= 0.08; }).sort(function (a, b) { return Math.abs(g[b]) - Math.abs(g[a]); }).slice(0, 3);
    return xs.map(function (n) { return '<span class="nvtag ' + (g[n] > 0 ? "up" : "dn") + '">' + (g[n] > 0 ? "▲" : "▼") + esc(n) + "</span>"; }).join("");
  }
  // 艇のデータ(腕・モーター・癖)
  function nvChips(R, b, role, MZ, EXR) {
    var c = b.course, cs = (b.cs || {})[String(c)] || {}, out = [], ix = D.entries.map(function (e) { return e.waku; }).indexOf(b.waku);
    if (cs.n) {
      if (role === "axis") out.push(c + "コース1着" + pct(cs.w1, cs.n) + "%(" + cs.n + "走)");
      else out.push(c + "コース2連対" + pct((cs.w1 || 0) + (cs.w2 || 0), cs.n) + "%・3連対" + pct((cs.w1 || 0) + (cs.w2 || 0) + (cs.w3 || 0), cs.n) + "%(" + cs.n + "走)");
    } else out.push(c + "コースの記録なし");
    if (role === "axis") {
      var tt = tacType(cs);
      if (c >= 2 && tt.text) out.push("勝ち方 " + tt.text + (tt.type ? "(" + tt.type + ")" : ""));
    } else if (c === 1) {
      var ls = cs.ls || {}, lt = ["差し", "捲り", "捲り差し"].filter(function (x) { return ls[x]; }).map(function (x) { return NV_LS[x] + ls[x]; }).join("・");
      if (lt) out.push("負けた時 " + lt);
    } else {
      var st2t = secondText(cs);
      if (st2t !== "—") out.push("2着の時 " + st2t);
    }
    var z = MZ[ix], gd = gradeOf(z, b.mg);
    if (z != null) out.push("モーター" + gBadge(gd) + (b.motor2 != null ? "(" + fmt(b.motor2) + "%)" : ""));
    if (EXR[b.waku]) out.push("展示" + EXR[b.waku] + "位(" + fmt(b.ex, 2) + ")");
    if (b.stf) out.push("予想ST" + st2(b.stf.mean) + (b.stf.fp > 0 ? ' <span class="fon">F' + b.stf.fp + "</span>" : ""));
    out.push(esc(b.cls || "") + " 勝率" + fmt(b.rate, 2));
    var dw = dochu(b);
    if (dw.n >= 8 && (dw.rate >= 0.58 || dw.rate <= 0.42)) out.push("競り合い" + dw.w + "勝" + (dw.n - dw.w) + "敗");
    return out.map(function (x) { return '<span class="nvd">' + x + "</span>"; }).join("");
  }
  // その決着パターンになりやすい理由(見立てのモデルの、STに関係しない点数から)
  function nvWhy(R, i, b, k) {
    var p = ((R.M.staticU || {}).parts || [])[i];
    if (!p) return [];
    var c = b.course, cs = (b.cs || {})[String(c)] || {}, b1 = R.B.filter(function (x) { return x.course === 1; })[0] || null;
    var items = [];
    function add(v, pos, neg) { if (Math.abs(v || 0) >= 0.05) items.push({ v: v, t: v > 0 ? pos : neg }); }
    add(p.rec, c + "コースで1着が多い(" + (cs.w1 || 0) + "/" + (cs.n || 0) + "走)", c + "コースでの1着が少ない(" + (cs.w1 || 0) + "/" + (cs.n || 0) + "走)");
    if (c >= 2 && k !== "抜き") {
      var tt = tacType(cs).text;
      add(p.tac, c + "コースで勝つときは" + k + "が多い" + (tt ? "(" + tt + ")" : ""), c + "コースで" + k + "で勝つことは少ない" + (tt ? "(" + tt + ")" : ""));
      var ls1 = (((b1 && b1.cs) || {})["1"] || {}).ls || {};
      if (b1 && NV_LS[k]) add(p.ls, "1コースの" + surname(b1.name) + "は" + NV_LS[k] + "やすい(1コースで負けた時 " + NV_LS[k] + (ls1[k] || 0) + ")",
                             "1コースの" + surname(b1.name) + "は" + NV_LS[k] + "にくい(1コースで負けた時 " + NV_LS[k] + (ls1[k] || 0) + ")");
      if (c >= 3) add(p.nb, "内の" + (c - 1) + "コースが捲りに行くことが多く、" + k + "の展開が生まれやすい", "内の" + (c - 1) + "コースは捲りに行くことが少なく、" + k + "の展開は生まれにくい");
    }
    add(p.mot, "モーターが上位", "モーターが下位");
    add(p.ex, "展示タイムが良い", "展示タイムが悪い");
    add(p.str, "このメンバーでは力が上位", "このメンバーでは力が下位");
    add(p.loc, "この場が得意", "この場が苦手寄り");
    items.sort(function (a, b2) { return Math.abs(b2.v) - Math.abs(a.v); });
    return items.slice(0, 5);
  }
  function nvValid(c, k) { return nvClass(c, k) != null; }
  function nvBestK(R, b) {
    var best = null;
    NV_KS.forEach(function (k) { var i = nvClass(b.course, k); if (i != null && (!best || nvP(R, i) > best.p)) best = { k: k, p: nvP(R, i) }; });
    return best ? best.k : null;
  }
  function renderNavi(R) {
    var boxB = $("#nvBoats"), boxT = $("#nvTacs"), out = $("#nvOut"), state = $("#nvState");
    if (!boxB || !out) return;
    var ab = absentWakus();
    if (ab.length) {
      boxB.innerHTML = ""; boxT.innerHTML = ""; state.textContent = "";
      out.innerHTML = '<p class="wait absent-note">' + esc(absentText(ab)) + "のため、このレースは展開ナビ(展開予想)を出せません。</p>";
      return;
    }
    if (!R || !R.M) {
      boxB.innerHTML = ""; boxT.innerHTML = "";
      out.innerHTML = '<p class="wait">' + (D.entries.length < 6 ? "6艇そろっていないレースは、展開ナビを出せません。" : "見立てのモデルを読み込めませんでした。時間をおいて開き直してください。") + "</p>";
      return;
    }
    state.textContent = ready() ? (finished() ? "結果が出たレース(展示の進入・STで計算)" : "展示の進入・STを入れて計算") : "展示の前(枠なり・ふだんのSTで計算)";
    // 選択: はじめは本線(一番起こりやすい決着)
    var axis = NV.w != null ? nvBoat(R, NV.w) : null;
    if (!axis) { var ld0 = leadScen(R); axis = ld0 ? ld0.b : R.B[0]; NV.w = axis.waku; NV.k = ld0 ? ld0.kim : null; }
    if (!NV.k || !nvValid(axis.course, NV.k)) NV.k = nvBestK(R, axis);
    var c = axis.course, k = NV.k, i = nvClass(c, k);
    boxB.innerHTML = R.B.slice().sort(function (a, b) { return a.waku - b.waku; }).map(function (b) {
      var on = b.waku === axis.waku;
      return '<button type="button" class="nvb' + (on ? " on" : "") + '" data-w="' + b.waku + '" aria-pressed="' + on + '">' + wk(b.waku) +
        '<span class="nm">' + esc(surname(b.name)) + femMark(b) + (b.course !== b.waku ? '<small>' + b.course + "コース</small>" : "") + "</span>" +
        '<span class="p">1着' + pTxt(b.share || 0) + "</span></button>";
    }).join("");
    boxT.innerHTML = NV_KS.map(function (kk) {
      var ii = nvClass(c, kk), ok = ii != null, on = kk === k;
      return '<button type="button" class="nvt' + (on ? " on" : "") + '" data-k="' + kk + '" aria-pressed="' + on + '"' + (ok ? "" : " disabled") + ">" + kk +
        '<span class="p">' + (ok ? pTxt(nvP(R, ii)) : "—") + "</span></button>";
    }).join("") + '<p class="note nvdesc">' + esc(k + ": " + NV_DESC[k]) + (c === 1 ? "。1コースは逃げと抜きだけ" : "。逃げは1コースだけ") + "</p>";
    var P = nvP(R, i), o = R.M.order(i), post = R.M.postST(i), MZ = motorZs(), EXR = {};
    var exs = R.B.filter(function (b) { return b.ex != null && b.ex > 6 && b.ex < 7.6; }).sort(function (a, b) { return a.ex - b.ex; });
    if (exs.length >= 4) exs.forEach(function (b, r) { EXR[b.waku] = 1 + exs.filter(function (x) { return x.ex < b.ex - 1e-9; }).length; });
    var byC = {};
    R.B.forEach(function (b) { byC[b.course] = b; });
    var rank = 1 + R.scen.filter(function (s) { return s.p > P + 1e-9; }).length, share = axis.share ? P / axis.share * 100 : 0;
    var pr = ((PARAMS || {}).pairs || {})[c + k] || null;
    // 1) 選んだ展開のまとめ
    var why = nvWhy(R, i, axis, k);
    var stCells = [1, 2, 3, 4, 5, 6].map(function (cc) {
      var b = byC[cc], m = b && b.stf ? b.stf.mean : null, x = post ? post[cc - 1] : null, dd = x != null && m != null ? x - m : 0;
      return '<div class="' + (cc === c ? "cur" : "") + '">' + wk(b ? b.waku : cc) + "<b>" + st2(x) + "</b>" +
        '<span class="sd' + (dd <= -0.008 ? " up" : dd >= 0.008 ? " dn" : "") + '">' + (Math.abs(dd) >= 0.008 ? (dd < 0 ? "予想より早め" : "予想より遅め") : "予想並") + "</span></div>";
    }).join("");
    var html = '<div class="nvsum"><div class="nvhead">' + wk(axis.waku) + "<b>" + esc(axis.name) + "</b>の<b>" + esc(k) + "</b>" +
      (c !== axis.waku ? '<span class="tag">' + c + "コース</span>" : "") + "</div>" +
      '<p class="nvp">このレースで起こる見込み <b>' + pTxt(P) + "</b>(決着パターンの" + rank + "番目)" +
      (axis.share >= 1 ? "。" + axis.waku + "号艇が勝つときの" + Math.round(share) + "%がこの形" : "") + "</p>" +
      (P < 3 ? '<p class="nvwarn">このレースでは起こりにくい展開です。</p>' : "") +
      '<div class="nvsub">スタートの形(この展開になるときの各コースのST)</div><p class="nvtx">' + esc(nvStartText(k, c, post)) + '</p><div class="courses nvst" aria-label="この展開になるときのST(平均)">' + stCells + "</div>" +
      (why.length ? '<div class="nvsub">この展開になりやすい点・なりにくい点</div><ul class="nvwhy">' + why.map(function (x) {
        return '<li class="' + (x.v > 0 ? "up" : "dn") + '">' + (x.v > 0 ? "▲ " : "▼ ") + esc(x.t) + "</li>"; }).join("") + "</ul>" : "") +
      '<div class="nvsub">' + axis.waku + "号艇のデータ</div><div class=\"nvds\">" + nvChips(R, axis, "axis", MZ, EXR) + "</div></div>";
    // 2) 2着の展開(と、それぞれの3着)
    if (o) {
      var lam1 = (o.lam || [1, 1])[1], cand = Object.keys(o.p2).map(Number).sort(function (a, b) { return o.p2[b] - o.p2[a]; });
      var shown = cand.filter(function (cc, j) { return j < 4 && (o.p2[cc] >= 0.03 || j < 2); }), rest = cand.filter(function (cc) { return shown.indexOf(cc) < 0; });
      var natN = pr ? pr.n : 0, nat2 = function (cc) { return pr && natN >= 30 ? Math.round(pr.s2[cc - 1] / natN * 100) : null; };
      var canPlay = ready() && k !== "抜き";
      html += '<div class="nvsec"><h3>2着の展開</h3><p class="sub">' + axis.waku + "号艇の" + esc(k) + "になったとき、2着になりそうな艇と、その動き。" +
        (natN >= 30 ? "「全国」は、過去1年の全国のレースで" + c + "コースの" + esc(k) + "だったとき(" + natN.toLocaleString() + "レース)の、そのコースの2着の割合です。" : "") + "</p>";
      html += shown.map(function (cc) {
        var b = byC[cc], q2 = o.p2[cc] * 100, n2 = nat2(cc);
        // 3着: この艇が2着だったときの、残りの艇の見立て
        var others = Object.keys(o.u).map(Number).filter(function (x) { return x !== cc; });
        var mx = Math.max.apply(null, others.map(function (x) { return lam1 * o.u[x]; })), q = {}, s = 0;
        others.forEach(function (x) { q[x] = Math.exp(lam1 * o.u[x] - mx); s += q[x]; });
        var t3 = others.sort(function (a, b2) { return q[b2] - q[a]; }).slice(0, 3);
        var s23 = pr ? pr.s23[cc - 1] : null, n23 = s23 ? s23.reduce(function (a, x) { return a + x; }, 0) : 0;
        var thirds = t3.map(function (x) {
          var bx = byC[x], nat = n23 >= 30 ? Math.round(s23[x - 1] / n23 * 100) : null;
          return '<li>' + wk(bx.waku) + '<span class="ph">' + esc(nvPhrase(k, c, x, bx, 3)) + '</span><span class="pc">' + pTxt(q[x] / s * 100) + "</span>" +
            (nat != null ? '<span class="nat">全国' + nat + "%</span>" : "") + "</li>";
        }).join("");
        return '<div class="nvc"><div class="nvch">' + wk(b.waku) + '<div class="nvcm"><div><b>' + esc(surname(b.name)) + "</b> " + esc(nvPhrase(k, c, cc, b, 2)) + "</div>" +
          '<div class="bar"><i style="width:' + Math.min(100, q2).toFixed(1) + '%"></i></div></div><span class="pct">' + pTxt(q2) + "</span>" +
          (n2 != null ? '<span class="nat">全国' + n2 + "%</span>" : "") + "</div>" +
          '<div class="nvtags">' + nvTags(o.parts && o.parts[cc]) + "</div>" +
          '<div class="nvds">' + nvChips(R, b, "cand", MZ, EXR) + "</div>" +
          '<div class="nv3"><span class="lbl">3着は</span><ul>' + thirds + "</ul></div>" +
          (canPlay ? '<button type="button" class="nvplay" data-a="' + b.waku + '" data-b="' + (byC[t3[0]] ? byC[t3[0]].waku : "") + '">この展開を1S1Mの映像で見る</button>' : "") + "</div>";
      }).join("");
      if (rest.length) html += '<p class="sub nvrest">そのほか: ' + rest.map(function (cc) { return wk(byC[cc].waku) + " " + pTxt(o.p2[cc] * 100); }).join("・") + "</p>";
      if (!canPlay) html += '<p class="note">' + (k === "抜き" ? "抜きは2マーク以降の逆転なので、1周1マークの映像はありません。" : "1周1マークの映像は、スタート展示のあとに見られます。") + "</p>";
      html += "</div>";
    }
    out.innerHTML = html;
  }
  function navi(R) {                                  // 展開ナビのタブが開いているときだけ作る(開いたときに作り直す)
    naviR = R;
    var pane = $("#pane-navi");
    if (!pane) return;
    if (pane.hidden) { naviPending = true; return; }
    naviPending = false;
    renderNavi(absentWakus().length ? null : naviR || (naviR = analyze()));
  }
  function setupNavi() {
    var boxB = $("#nvBoats"), boxT = $("#nvTacs"), out = $("#nvOut");
    if (!boxB) return;
    boxB.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-w]");
      if (!b) return;
      NV.w = +b.getAttribute("data-w"); NV.k = null;
      var R = naviR || (naviR = analyze()), axis = nvBoat(R, NV.w);
      if (axis) NV.k = nvBestK(R, axis);
      renderNavi(R);
    });
    boxT.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-k]");
      if (!b || b.disabled) return;
      NV.k = b.getAttribute("data-k");
      renderNavi(naviR || (naviR = analyze()));
    });
    out.addEventListener("click", function (e) {
      var b = e.target.closest("button.nvplay");
      if (!b || !ready()) return;
      custom = { w: NV.w, k: NV.k, a: +b.getAttribute("data-a"), b: +b.getAttribute("data-b") || null };
      showTab("t1", true);
      if (view && !pendingR && lastR) {                       // 映像を作るあいだ(選んだ並びに合わせるので少し時間がかかる)、その旨を出しておく
        view.pause();
        var cv0 = $("#t1view"), g = cv0 && cv0.getContext("2d");
        if (g) {
          g.fillStyle = "rgba(6,40,54,0.72)"; g.fillRect(0, 0, cv0.width, cv0.height);
          g.fillStyle = "rgba(255,255,255,0.9)"; g.font = Math.round(cv0.width / 26) + "px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
          g.fillText("選んだ展開の映像を作っています…", cv0.width / 2, cv0.height / 2);
        }
        setTimeout(showNow, 40);
      }
      var cv = $("#t1view");
      if (cv && cv.scrollIntoView) setTimeout(function () { cv.scrollIntoView({ behavior: "smooth", block: "center" }); }, 60);
    });
  }

  // 直前情報と結果を読み直す(Cloudflare か GitHub。締切の1時間半前から、結果が出るまで。締切から時間がたっていても、結果がまだなら読みに行く)
  var pollTimer = null;
  function poll() {
    var left = minsLeft();
    if (left > 90) return;
    getData("live", LIVE_REL).then(function (j) {
      if (!j) return;
      var nb = (j.before || {})[NO], nr = (j.result || {})[NO], no = (j.orig || {})[NO], ch = false;
      var nd = (j.dl || {})[NO];                                    // 公式の今の締切(レースが遅れると変わる)
      if (nd && nd !== D.race.deadline) {
        if (!D.race.deadline0) D.race.deadline0 = D.race.deadline;
        D.race.deadline = nd; ch = true;
        if (D.race.deadline0 === nd) delete D.race.deadline0;
        try { document.dispatchEvent(new CustomEvent("suimen:deadline", { detail: nd })); } catch (e) {}
      }
      if (URA && j.before) {                                       // 裏: 先のレースの直前情報の風・波(このレースの展示の前の目安)
        var lw = null;
        Object.keys(j.before).forEach(function (k) {
          var x = j.before[k] || {}, w = x.weather;
          if (w && w.wind != null && (!lw || String(x.fetched || "") > lw.at)) lw = { wind: w.wind, wave: w.wave, at: String(x.fetched || "") };
        });
        if (lw && JSON.stringify(lw) !== JSON.stringify(VW)) { VW = lw; if (!ready()) ch = true; }
      }
      if (no && JSON.stringify(no) !== JSON.stringify(OG)) { OG = no; ch = true; }
      if (nb && JSON.stringify(nb) !== JSON.stringify(BI)) { BI = nb; ch = true; }
      if (nr && JSON.stringify(nr) !== JSON.stringify(LR)) { LR = nr; ch = true; }
      if (ch) render();
    }).catch(function () {});
  }
  // 直前情報を待っている間(締切の25分前〜)と、結果を待っている間(締切の後)は20秒ごと、それ以外は1分ごとに読み直す
  function hot() {
    var left = minsLeft();
    return (left <= 25 && left >= -3 && !(BI && BI.ready)) || (left < -2 && left > -90 && !LR);
  }
  function schedule() {
    clearTimeout(pollTimer);
    function tick() {
      if (!document.hidden) {
        renderDeadline();
        if (!(finished() && LR)) poll();
      }
      pollTimer = setTimeout(tick, hot() ? 20000 : 60000);
    }
    pollTimer = setTimeout(tick, hot() ? 20000 : 60000);
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { renderDeadline(); if (!(finished() && LR)) poll(); } });
  function copyBtn(id, ta, m) {
    var b = $(id);
    if (b) b.addEventListener("click", function () {
      var t = $(ta), msg = $(m);
      if (!t) return;
      function sel() { t.focus(); t.select(); msg.textContent = "選択しました。長押しでコピーしてください"; }
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t.value).then(function () { msg.textContent = "コピーしました"; }, sel);
      else sel();
    });
  }
  // タブ(出走表・直前情報・1S1M展開・展開ナビ・データ)。選んだタブはアドレスの # に残し、ほかのレースへ移っても同じタブを開く
  var showTab = function () {};
  function setupTabs() {
    var tabs = $$(".tabs [data-tab]"), names = tabs.map(function (b) { return b.getAttribute("data-tab"); });
    showTab = show;
    function show(name, keep) {
      tabs.forEach(function (b) { var on = b.getAttribute("data-tab") === name; b.classList.toggle("on", on); b.setAttribute("aria-selected", on ? "true" : "false"); });
      $$(".pane").forEach(function (pn) { pn.hidden = pn.id !== "pane-" + name; });
      if (keep && history.replaceState) history.replaceState(null, "", "#" + name);
      $$(".chips a.chip").forEach(function (a) { a.href = a.getAttribute("href").split("#")[0] + "#" + name; });
      if (name === "t1") {
        if (pendingR) {                                               // 映像を作るあいだ固まって見えないよう、先にタブを出してから作る
          var R1 = pendingR;
          drawWaiting();
          setTimeout(function () { if (pendingR === R1) updateView(R1); window.dispatchEvent(new Event("resize")); }, 40);
        } else window.dispatchEvent(new Event("resize"));
      }
      if (name === "navi" && naviPending) setTimeout(function () { navi(naviR); }, 20);
    }
    tabs.forEach(function (b) { b.addEventListener("click", function () { show(b.getAttribute("data-tab"), true); }); });
    var h = (location.hash || "").slice(1);
    show(names.indexOf(h) >= 0 ? h : names[0], false);
    // 表の見出し(選手名)を、上に止まるタブのすぐ下に止める
    var bar = $(".tabs");
    function tabsH() { if (bar) document.documentElement.style.setProperty("--tabsH", bar.offsetHeight + "px"); }
    tabsH();
    window.addEventListener("resize", tabsH);
  }
  setupTabs();
  copyBtn("#btnCopy", "#post", "#copyMsg");
  copyBtn("#btnCopyR", "#review", "#copyMsgR");
  setupViewControls();
  setupNavi();
  setupTactics();
  if (URA) {                                                          // 裏: オッズ(odds.js)が来たら、人気とのずれを入れて描き直す(20秒に1回まで)
    var oddsAt = 0, oddsTimer = null;
    document.addEventListener("suimen:odds", function (ev) {
      window.SuimenOdds = ev.detail;
      clearTimeout(oddsTimer);
      var wait = Math.max(0, 20000 - (Date.now() - oddsAt));
      oddsTimer = setTimeout(function () { oddsAt = Date.now(); render(); }, wait);
    });
  }
  window.SuimenRace = { render: function () { render(); } };
  render();
  if (!(finished() && LR)) poll();
  schedule();
})();
