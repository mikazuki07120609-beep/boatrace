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
  var LIVE_URL = "https://raw.githubusercontent.com/mikazuki07120609-beep/boatrace/main/data/live/" + D.race.ymd + "/" + V.code + ".json";
  var NO = String(D.race.no);
  var BI = D.before || null, LR = D.live || null;     // 直前情報・レース直後の結果
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

  // 直前情報の表
  function renderBefore() {
    var box = $("#beforeBox"), at = $("#beforeAt");
    if (!box) return;
    var has = BI && BI.ex && Object.keys(BI.ex).some(function (k) { return BI.ex[k] != null; });
    var fromRes = !has && D.result;
    if (!has && !fromRes) {
      var left = minsLeft();
      box.innerHTML = '<p class="wait">' + (left < -5 || finished() ? "このレースの直前情報は取り込めませんでした。" : "展示航走のあと(締切の10〜15分前ごろ)に自動で入ります。") + "</p>";
      if (at) at.textContent = "";
      return;
    }
    var exs = D.entries.map(function (e) { return exOf(e.waku); }).filter(function (x) { return x != null; }).sort(function (a, b) { return a - b; });
    var rows = D.entries.map(function (e) {
      var w = String(e.waku), ex = exOf(e.waku), rk = ex == null ? null : exs.indexOf(ex) + 1, c = courseOf(e.waku);
      var est = has && BI.est ? BI.est[w] : null, parts = has ? (BI.parts && BI.parts[w] || []).slice() : [];
      if (has && BI.prop && BI.prop[w]) parts.push("プロペラ" + BI.prop[w]);
      var tilt = has && BI.tilt ? BI.tilt[w] : null, wt = has && BI.weight ? BI.weight[w] : null, adj = has && BI.adj ? BI.adj[w] : null;
      return '<tr><td class="w w' + e.waku + '">' + e.waku + '</td><td class="who"><b>' + esc(e.name) + "</b></td>" +
        '<td class="' + (rk === 1 ? "best" : "") + '"><b>' + fmt(ex, 2) + "</b>" + (rk ? '<span class="dim">' + rk + "位</span>" : "") + "</td>" +
        '<td><b>' + (c !== e.waku ? '<span class="moved">' + c + "</span>" : c) + "</b></td>" +
        '<td class="' + (est != null && est < 0 ? "fon" : "") + '">' + st2(est) + "</td>" +
        "<td>" + (tilt == null ? "—" : fmt(tilt, 1)) + "</td>" +
        '<td class="txt">' + (parts.length ? esc(parts.join("・")) : "—") + "</td>" +
        "<td>" + (wt == null ? "—" : fmt(wt, 1)) + (adj ? '<span class="dim">調整' + fmt(adj, 1) + "</span>" : "") + "</td></tr>";
    }).join("");
    var W = has ? BI.weather || {} : {};
    var wl = has ? [W.at ? W.at + "時点" : "", W.weather || "", W.temp != null ? "気温" + fmt(W.temp, 0) + "℃" : "", W.wind != null ? "風速" + fmt(W.wind, 0) + "m" : "",
                    W.wave != null ? "波高" + fmt(W.wave, 0) + "cm" : "", W.water != null ? "水温" + fmt(W.water, 0) + "℃" : ""].filter(Boolean).join("・")
                 : (D.result ? "風 " + (D.result.wind_dir || "") + (D.result.wind != null ? D.result.wind + "m" : "") + "(競走成績から)" : "");
    box.innerHTML = '<div class="scroll"><table class="rc bt"><thead><tr><th class="w">枠</th><th class="who">選手</th><th>展示<br>タイム</th><th>進入</th><th>展示<br>ST</th>' +
      "<th>チルト</th><th>部品交換</th><th>体重</th></tr></thead><tbody>" + rows + "</tbody></table></div>" +
      (wl ? '<p class="sub">' + esc(wl) + "</p>" : "");
    if (at) at.textContent = has ? (BI.fetched ? BI.fetched + " 取り込み" : "") : "";
  }

  // 出走表の「このコース」を、展示の進入に合わせて書き換える。モーター評価に、このレースの展示タイムを加える
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
  function courseCells(cs, course) {
    var a;
    if (cs && cs.n) {
      a = '<td class="c1"><b>' + pct(cs.w1, cs.n) + '%</b></td><td class="c2">' + pct(cs.w2, cs.n) + '%</td><td class="c3">' + pct(cs.w1 + cs.w2 + cs.w3, cs.n) + "%</td>" +
        '<td class="c4"><span>' + st2(cs.st) + '</span><span class="dim">' + cs.n + "走</span></td>";
    } else a = '<td class="c1">—</td><td class="c2">—</td><td class="c3">—</td><td class="c4"><span>—</span><span class="dim">0走</span></td>';
    var lab = "", val = "—";
    if (cs && cs.n && course === 1) { lab = "逃げ"; val = pct((cs.km || {})["逃げ"] || 0, cs.n) + "%"; }
    if (cs && cs.n && course === 2) { lab = "逃がし"; val = pct(cs.ng || 0, cs.n) + "%"; }
    return a + '<td class="txt c5"><span>' + esc(winText(cs, course)) + '</span><span class="dim">' + esc(secondText(cs)) + "</span></td>" +
      '<td class="c6"><span class="dim">' + (lab ? esc(lab) : "&nbsp;") + "</span><span>" + esc(val) + "</span></td>";
  }
  var cardCourseSig = "";
  function updateCard() {
    var sig = D.entries.map(function (e) { return courseOf(e.waku); }).join("");
    if (sig !== cardCourseSig) {
      cardCourseSig = sig;
      var moved = false;
      D.entries.forEach(function (e) {
        var c = courseOf(e.waku), tr = document.querySelector('#card tr[data-waku="' + e.waku + '"]');
        if (!tr) return;
        if (c !== e.waku) moved = true;
        var cells = tr.querySelectorAll(".c1,.c2,.c3,.c4,.c5,.c6");
        if (cells.length !== 6) return;
        var tmp = document.createElement("tbody");
        tmp.innerHTML = "<tr>" + courseCells((e.cs || {})[String(c)], c) + "</tr>";
        var fresh = tmp.firstChild.children;
        for (var i = cells.length - 1; i >= 0; i--) cells[i].parentNode.replaceChild(fresh[i], cells[i]);
      });
      var h = $("#cardCourse");
      if (h) h.textContent = moved ? "このコース(展示の進入)" : "このコース(枠と同じ)";
    }
    // モーター評価: 展示タイムが4艇以上そろったら、レースの平均との差を加える(重みは scripts/motor.py と同じ)
    var exs = D.entries.map(function (e) { return exOf(e.waku); }).filter(function (x) { return x != null && x > 6 && x < 7.6; });
    var mean = exs.length >= 4 ? avg(exs) : null;
    D.entries.forEach(function (e) {
      var mg = e.mg, b = document.querySelector('#card tr[data-waku="' + e.waku + '"] td.mo b');
      if (!mg || !b) return;
      var z = mg.z, ex = exOf(e.waku);
      if (mean != null && ex != null) {
        var zt = Math.max(-3, Math.min(3, (mean - ex) / 0.047));
        z = (0.55 * mg.z + 0.45 * zt) / Math.sqrt(0.55 * 0.55 + 0.45 * 0.45);
      }
      var g = z >= 1.4 ? "S" : z >= 0.65 ? "A" : z >= 0 ? "B" : z >= -0.65 ? "C" : z >= -1.4 ? "D" : "E";
      b.textContent = g; b.className = "g g" + g;
      b.title = mean != null ? "モーター評価(このレースの展示タイムを加えたもの)" : "モーター評価";
    });
  }

  // 結果(3連単の組と払戻金)
  function renderResult() {
    var bar = $("#resbar");
    if (!bar || !LR || !LR.tri) return;
    var t = LR.tri.map(function (w) { return '<span class="waku w' + w + '">' + w + "</span>"; }).join('<span class="sep">-</span>');
    bar.innerHTML = '<span class="lbl">結果</span><span class="tri">' + t + "</span>" +
      (LR.pay ? '<b class="odds">' + (LR.pay / 100).toFixed(1) + "倍</b>" + (LR.pop ? '<span class="dim">' + LR.pop + "番人気</span>" : "") : "") +
      (LR.kimarite ? '<span class="tag">' + esc(LR.kimarite) + "</span>" : "") + (LR.note ? '<span class="sub">' + esc(LR.note) + "</span>" : "");
    bar.hidden = false;
  }
  function renderDeadline() {
    var t = $("#dlTag");
    if (!t) return;
    var left = minsLeft(), s = "締切 " + D.race.deadline;
    if (finished()) s += "(終了)";
    else if (left > 0 && left < 600) s += "(あと" + Math.floor(left) + "分)";
    else if (left <= 0 && left > -600) s += "(締切済み)";
    t.textContent = s;
    t.classList.toggle("soon", !finished() && left > 0 && left <= 10);
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
    var race = { vt: D.vt, nt: D.nt, wind: W.wspd, date: D.race.date, venue: V.code,
                 boats: B.map(function (b) { return { waku: b.waku, course: b.course, pts: b.pts || [0, 0], stx: b.stx || [0, 0, 0], r8: b.r8 || [], f: b.f || [], est: estOf(b.waku),
                                                      cs: b.cs || {}, motor2: b.motor2, ex: b.ex }; }) };
    var M = MODEL.predict(race, PARAMS, { samples: 400 });
    if (!M) return null;
    var kw = windKw(W), byC = {};
    B.forEach(function (b) { byC[b.course] = b; });
    var scen = M.classes.map(function (ck, i) { return { b: byC[ck[0]], kim: ck[1], w: M.p[i] * (kw[ck[1]] || 1), i: i }; });
    var tot = scen.reduce(function (s, x) { return s + x.w; }, 0) || 1;
    scen.forEach(function (s) { s.p = s.w / tot * 100; });
    scen.sort(function (a, b) { return b.p - a.p; });
    M.st.forEach(function (s) { byC[s.course].stf = s; });
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
    if (q.wind) out.push("風速" + R.wspd + "m(" + sgn(q.wind) + "秒)");
    var est = estOf(b.waku);
    if (est != null) out.push("展示ST" + (est < 0 ? "F" + st2(-est) : st2(est)) + (Math.abs(q.est || 0) >= 0.003 ? "(" + sgn(q.est) + "秒)" : ""));
    return out;
  }
  function renderStart(R) {
    var rows = $("#stRows"), notes = $("#stNotes");
    if (!rows) return;
    if (!R.M) { rows.innerHTML = '<tr><td colspan="6" class="why">学習済みの見立てがまだありません。</td></tr>'; return; }
    var B = R.B.slice().sort(function (a, b) { return a.course - b.course; }), M = R.M;
    R.nbMean = avg(B.map(function (b) { return (b.stf.parts || {}).nb || 0; }));
    rows.innerHTML = B.map(function (b) {
      var s = b.stf, wb = M.whenBoat(b.course - 1, "out"), top = "—";
      if (wb) {
        var bi = 0;
        wb.p.forEach(function (p, i) { if (p > wb.p[bi]) bi = i; });
        top = M.classes[bi][0] + "コース" + M.classes[bi][1] + " " + Math.round(wb.p[bi] * 100) + "%";
      }
      return '<tr><td><span class="waku w' + b.waku + '">' + b.waku + "</span> " + b.course + "</td><td>" + esc(b.name) + "</td>" +
        '<td class="num">' + st2(s.mean) + '<span class="small">' + st2(s.lo) + "〜" + st2(s.hi) + "</span></td>" +
        '<td class="num">' + Math.round(s.pOut * 100) + '%<span class="meter"><i style="width:' + Math.min(100, s.pOut * 250).toFixed(0) + '%"></i></span></td>' +
        '<td class="num">' + Math.round(s.pDent * 100) + '%<span class="meter"><i style="width:' + Math.min(100, s.pDent * 250).toFixed(0) + '%"></i></span></td>' +
        "<td>" + esc(top) + "</td></tr>";
    }).join("");
    var ven = (B[0].stf.parts || {}).ven || 0;
    notes.innerHTML = B.map(function (b) { return "<li>" + b.course + "コース " + esc(b.name) + ": " + esc(stReasons(b, R).join("、")) + "</li>"; }).join("") +
      (Math.abs(R.nbMean) >= 0.004 ? "<li>" + esc("メンバー全体が" + (R.nbMean < 0 ? "スタートの早い選手ぞろいで、そろって早いスタートになりやすい" : "スタートの遅めの選手が多く、そろって遅めのスタートになりやすい") +
        "(隣の艇につられる分、平均" + sgn(R.nbMean) + "秒)。") + "</li>" : "") +
      (Math.abs(ven) >= 0.005 ? "<li>" + esc(V.name + "は、全体にSTが" + (ven < 0 ? "早く" : "遅く") + "出やすい場です(" + sgn(ven) + "秒)。") + "</li>" : "");
  }

  function render() {
    renderDeadline();
    renderResult();
    renderBefore();
    updateCard();
    var on = ready();
    setGated(on);
    if (!on) return;
    var R = analyze(), B = R.B, scen = R.scen;
    function byCourse(c) { return B.filter(function (b) { return b.course === c; })[0]; }
    var p1 = V.place[0][0], t = tier(p1);
    renderStart(R);
    // 展開
    var top = scen.slice(0, 6), max = top.length ? top[0].p : 1;
    $("#scen").innerHTML = top.map(function (s) {
      return '<div class="scen-row"><span class="waku w' + s.b.waku + '">' + s.b.waku + '</span><div><div>' + patName(s) +
        '<span class="sub"> ・' + esc(s.b.name) + '</span></div><div class="bar"><i style="width:' + (s.p / max * 100).toFixed(1) +
        '%"></i></div></div><span class="pct">' + s.p.toFixed(0) + "%</span></div>";
    }).join("");
    var lead = scen[0];
    $("#scenLead").textContent = lead ? "本線は「" + patName(lead) + "」。上位6つの決着パターンと、起こりやすさの目安です。" : "";
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
      if (outB) pts.push(outB.course + "コース" + outB.name + "はスタートで出る確率" + Math.round(outB.stf.pOut * 100) + "%。" +
        (outB.course === 2 ? "1コースより先に出ると、ジカまくりも。" : outB.course === 4 ? "カドから出れば、絞ってのカドまくり。" : "出れば内を絞って攻める。"));
    } else if (b2 && b3 && b2.stUse != null && b3.stUse != null && b2.stUse - b3.stUse >= 0.03) {
      pts.push("2コースの平均ST(" + fmt(b2.stUse, 2) + ")が3コース(" + fmt(b3.stUse, 2) + ")より遅い。2コースが凹むと、3コースのまくりが入りやすい。");
    }
    if (b2 && b1 && b2.power != null && b1.power != null && b2.power > b1.power + 0.5)
      pts.push("2コース" + b2.name + "の方が1コースより勝率が上。差しが決まる場面に注意。");
    if (!R.M && b4 && R.aSt != null && b4.stUse != null && b4.stUse <= R.aSt - 0.02)
      pts.push("4コース(カド)" + b4.name + "はスタートが速い(平均ST" + fmt(b4.stUse, 2) + ")。内が凹めばカドまくりの展開。");
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
    $("#points").innerHTML = pts.map(function (p) { return "<li>" + esc(p) + "</li>"; }).join("");
    // 各艇
    $("#boats").innerHTML = B.slice().sort(function (a, b) { return a.course - b.course; }).map(function (b) {
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
      if (b.stf) li.push("予想ST" + st2(b.stf.mean) + "。出る" + Math.round(b.stf.pOut * 100) + "%・凹む" + Math.round(b.stf.pDent * 100) + "%。");
      else if (b.stUse != null && R.aSt != null) { var ds = R.aSt - b.stUse; if (ds >= 0.02) li.push("STが速い(" + fmt(b.stUse, 2) + ")。先手を取れる。"); else if (ds <= -0.02) li.push("STが遅め(" + fmt(b.stUse, 2) + ")。スタートで後手に回りやすい。"); }
      if (b.local && b.rate) { var dl = b.local - b.rate; if (dl >= 0.4) li.push("当地勝率が全国より高い。この水面は得意。"); else if (dl <= -0.4) li.push("当地勝率が全国より低い。この水面は苦手寄り。"); }
      var dw = dochu(b);
      if (dw.text) li.push(dw.text);
      var grid = [1, 2, 3, 4, 5, 6].map(function (cn) {
        var cs = (b.cs || {})[String(cn)];
        return '<div class="' + (cn === b.course ? "cur" : "") + '">' + cn + "<b>" + (cs && cs.n ? pct(cs.w1, cs.n) + "%" : "—") + "</b>" + (cs && cs.n ? cs.n + "走" : "") + "</div>";
      }).join("");
      return '<div class="boat"><h3><span class="waku w' + b.waku + '">' + b.waku + "</span>" + esc(b.name) + '<span class="tag">' + b.course + "コース</span>" +
        '<span class="sub">勝ち筋 ' + b.share.toFixed(0) + '%</span></h3><div class="courses" aria-label="コース別1着率">' + grid + "</div><ul>" +
        li.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>";
    }).join("");
    // 解説文
    var r = D.race, lines = ["【" + V.name + r.no + "R 展開メモ】", V.name + "は1コース1着率" + fmt(p1) + "%の" + t[0] + "。"];
    if (lead) lines.push("本線は" + lead.b.course + "コース" + lead.b.name + "の「" + lead.kim + "」。");
    var second = lead ? scen.filter(function (s) { return s.b !== lead.b; })[0] : null;
    if (second) lines.push("対抗の展開は" + second.b.course + "コース" + second.b.name + "の「" + second.kim + "」。");
    pts.slice(1, 3).forEach(function (p) { lines.push(p); });
    lines.push("", "※データから見た展開の目安です。舟券の推奨ではありません。", "#ボートレース #" + V.name, location.href.split("#")[0]);
    $("#post").value = lines.join("\n");
    updateView(R);
  }

  // ---- 1周1マーク展開ビュー(turn1.js)。展開の見立てと同じ決着パターンで、そのパターンになりやすいSTの組み合わせで動かす
  var view = null, viewSig = "", patKey = "", patIdx = 0, pats = [], lastR = null, viewTimer = null, started = false, wasPlaying = false, showActual = false;
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
    return { course: s.b.course, kim: s.kim, p: s.p };
  }
  // 終わったレースの再現: 実際の進入・ST・決まり手(翌日の競走成績か、レース直後に取り込んだ結果から)
  function actualScen() {
    var res = null, byW = {};
    if (D.result) { res = D.result; res.entries.forEach(function (x) { byW[x.waku] = x; }); }
    var kim = res ? res.kimarite : LR && LR.kimarite, win = null, courseByWaku = {}, stByCourse = [null, null, null, null, null, null];
    if (res) {
      win = res.entries.filter(function (x) { return x.rank === 1; })[0];
      res.entries.forEach(function (x) { if (x.course) { courseByWaku[x.waku] = x.course; if (x.st != null && !x.flying) stByCourse[x.course - 1] = x.st; } });
      win = win ? win.course : null;
    } else if (LR && LR.course && LR.course.length === 6) {
      LR.course.forEach(function (w, i) { courseByWaku[w] = i + 1; var t = LR.st ? LR.st[String(w)] : null; if (t != null && t >= 0) stByCourse[i] = t; });
      var first = (LR.order || []).filter(function (o) { return o.rank === 1; })[0];
      win = first ? courseByWaku[first.waku] : null;
    } else return null;
    if (!win || ["逃げ", "捲り", "差し", "捲り差し"].indexOf(kim) < 0 || Object.keys(courseByWaku).length !== 6) return null;
    if (stByCourse.some(function (x) { return x == null; })) return null;
    return { course: win, kim: kim, courseByWaku: courseByWaku, st: stByCourse };
  }
  var kotaeScen = null;
  function current() {
    if (showActual && kotaeScen) return { sc: { course: kotaeScen.course, kim: kotaeScen.kim, p: null, label: "結果" },
                                          ents: entriesFor(lastR, kotaeScen.st, kotaeScen.courseByWaku), fixed: true };   // 実際のSTはそのまま使う
    var s = pats[patIdx], post = lastR.M ? lastR.M.postST(s.i) : null;
    return { sc: scenOf(patIdx), ents: entriesFor(lastR, post) };
  }
  function drawPats() {
    var box = $("#t1Pats");
    if (!box) return;
    box.innerHTML = pats.map(function (s, i) {
      var on = !showActual && i === patIdx;
      return '<button type="button" class="pat' + (on ? " on" : "") + '" data-i="' + i + '" aria-pressed="' + on + '"><span class="waku w' + s.b.waku + '">' + s.b.waku + "</span>" +
        s.b.course + "コース " + s.kim + '<span class="p">' + s.p.toFixed(0) + "%</span></button>";
    }).join("") + (kotaeScen ? '<button type="button" class="pat' + (showActual ? " on" : "") + '" data-i="actual" aria-pressed="' + showActual + '">実際のレース</button>' : "");
  }
  var actualFirst = true;
  function updateView(R) {
    lastR = R;
    var canvas = $("#t1view");
    if (!canvas || !window.Turn1) return;
    kotaeScen = actualScen();
    if (kotaeScen && actualFirst) { showActual = true; actualFirst = false; }      // 終わったレースは、まず実際のレースを再現する
    pats = R.scen.filter(function (s) { return s.kim !== "抜き" && s.kim !== "恵まれ"; }).slice(0, 4);
    if (!pats.length) return;
    var pk = pats.map(function (s) { return s.b.waku + s.kim; }).join(",");
    if (pk !== patKey) { patKey = pk; patIdx = 0; }
    drawPats();
    var cur = current(), sig = JSON.stringify([cur.sc.course, cur.sc.kim, cur.ents.map(function (e) { return [e.waku, e.course, e.st, e.ex]; })]);
    if (sig === viewSig) return;
    viewSig = sig;
    if (!view) {
      view = Turn1.mount(canvas, { entries: cur.ents, scen: cur.sc, title: viewTitle(), kimarite: V.kimarite, brand: "水面ノート", fixedST: !!cur.fixed,
                                   onEnd: function () { var b = $("#t1Pause"); if (b) b.textContent = "再生"; } });
      watch(canvas);
    } else {
      clearTimeout(viewTimer);
      viewTimer = setTimeout(function () { view.setScenario(cur.sc, cur.ents, viewTitle(), !!cur.fixed); $("#t1Pause").textContent = "一時停止"; }, 700);
    }
  }
  function showNow() {
    var cur = current();
    viewSig = JSON.stringify([cur.sc.course, cur.sc.kim, cur.ents.map(function (e) { return [e.waku, e.course, e.st, e.ex]; })]);
    drawPats();
    view.setScenario(cur.sc, cur.ents, viewTitle(), !!cur.fixed); started = true; $("#t1Pause").textContent = "一時停止";
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
      if (k === "actual") showActual = true; else { showActual = false; patIdx = +k; }
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
        out.innerHTML = (canShare ? '<button class="primary" type="button" id="t1Share">共有する(Xなど)</button>' : "") +
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

  // 直前情報と結果を読み直す(raw.githubusercontent.com。開いている間は1分ごと、締切の1時間前から結果が出るまで)
  var pollTimer = null;
  function poll() {
    var left = minsLeft();
    if (left > 90 || left < -150) return;
    fetch(LIVE_URL + "?t=" + Math.floor(Date.now() / 30000), { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (!j) return;
      var nb = (j.before || {})[NO], nr = (j.result || {})[NO], ch = false;
      if (nb && JSON.stringify(nb) !== JSON.stringify(BI)) { BI = nb; ch = true; }
      if (nr && JSON.stringify(nr) !== JSON.stringify(LR)) { LR = nr; ch = true; }
      if (ch) render();
    }).catch(function () {});
  }
  function schedule() {
    clearInterval(pollTimer);
    pollTimer = setInterval(function () {
      if (document.hidden) return;
      renderDeadline();
      if (!(finished() && LR)) poll();
    }, 60000);
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
  copyBtn("#btnCopy", "#post", "#copyMsg");
  copyBtn("#btnCopyR", "#review", "#copyMsgR");
  setupViewControls();
  render();
  if (!(finished() && LR)) poll();
  schedule();
})();
