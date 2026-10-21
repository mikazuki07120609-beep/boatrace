/* レースページの見立て。出走表と選手の成績(ページに埋め込んだJSON)から、
   スタートの見立て(model.js)→ 展開の見立て → 1周1マークの映像(turn1.js)を作る。
   直前情報(展示タイム・進入・風)を入れると計算し直す。結果が出たレースは、見立てと結果を比べる(答え合わせ)。買い目は出さない。 */
(function () {
  "use strict";
  var el = document.getElementById("race-data");
  if (!el) return;
  var D = JSON.parse(el.textContent);
  var V = D.venue;
  var PARAMS = window.SUIMEN_PARAMS || null, MODEL = window.SuimenModel || null;
  var KIM = ["逃げ", "捲り", "差し", "捲り差し", "抜き", "恵まれ"];
  var SHRINK = 10; // 走数が少ない選手の成績を、場の平均に寄せる強さ(学習済みの重みがないときの簡易モデル用)
  function $(s) { return document.querySelector(s); }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function fmt(n, d) { return n == null || isNaN(n) ? "—" : Number(n).toFixed(d == null ? 1 : d); }
  function st2(x) { return x == null || isNaN(x) ? "—" : (x < 0 ? "-" : "") + Math.abs(x).toFixed(2).replace(/^0/, ""); }
  function avg(a) { var v = a.filter(function (x) { return x != null && !isNaN(x); }); return v.length ? v.reduce(function (s, x) { return s + x; }, 0) / v.length : null; }
  function pct(a, b) { return b ? Math.round(a / b * 100) : null; }

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

  // 直前情報(自動で取り込んだもの)
  var BI = D.before || null;
  function estOf(waku) { var v = BI && BI.est ? BI.est[String(waku)] : null; return v == null ? null : v; }
  function applyBefore() {
    if (!BI) return;
    D.entries.forEach(function (e) {
      var w = String(e.waku), ex = BI.ex && BI.ex[w], el = document.getElementById("ex" + e.waku);
      if (el && ex != null && !el.value) el.value = ex.toFixed(2);
      var ci = (BI.course || []).indexOf(e.waku), cEl = document.getElementById("c" + e.waku);
      if (cEl && ci >= 0 && (BI.course || []).length === D.entries.length) cEl.value = String(ci + 1);
    });
    var ws = BI.weather && BI.weather.wind, wEl = document.getElementById("windspd");
    if (wEl && ws != null) wEl.value = String(Math.round(ws));
  }

  function readState() {
    return D.entries.map(function (e) {
      var exEl = document.getElementById("ex" + e.waku), cEl = document.getElementById("c" + e.waku);
      var ex = exEl && exEl.value.trim() ? parseFloat(exEl.value) : null;
      var course = cEl ? parseInt(cEl.value, 10) : e.waku;
      var b = Object.assign({}, e);
      b.ex = isFinite(ex) ? ex : null;
      b.course = course || e.waku;
      return b;
    });
  }
  function windState() {
    var wind = $("#wind") ? $("#wind").value : "none";
    var wspd = parseFloat($("#windspd") ? $("#windspd").value : "0") || 0;
    return { wind: wind, wspd: wspd, strong: wspd >= 4 };
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
    renderKotae(R);
    updateView(R);
  }

  // ---- 答え合わせ(結果が出たレース): 締切前の見立てと実際の結果を比べ、何が違ったかを数字で出す。
  //      締切前の見立て(記録)→ 実際の進入・展示タイム・風を入れた見立て → 実際のSTも入れた見立て、の順に計算し直して、
  //      どこで見立てとずれたか(進入・展示か、スタートか、ターンや道中か)を分ける
  var kotaeScen = null;
  function validSt(x) { return x && x.st != null && !x.flying && !String(x.status || "").match(/^[LK]/) ? x.st : null; }
  function renderKotae(R) {
    var box = $("#kotae");
    if (!box || !D.result) return;
    if (!R.M) { $("#kotaeLead").textContent = "学習済みの見立てがないため、答え合わせはできません。"; return; }
    var res = D.result, byW = {}, M = R.M;
    res.entries.forEach(function (x) { byW[x.waku] = x; });
    var win = res.entries.filter(function (x) { return x.rank === 1; })[0];
    var kim = res.kimarite === "恵まれ" ? "抜き" : res.kimarite;
    var idx = win && win.course ? MODEL.CI[win.course + kim] : null;
    var logged = !!(D.pred && D.pred.p), pre = logged ? D.pred.p : M.p;
    function preST(waku) {
      if (logged) { var a = D.pred.st[waku - 1]; return a ? { mean: a[0], pOut: a[1], pDent: a[2] } : null; }
      var b = R.B.filter(function (x) { return x.waku === waku; })[0];
      return b && b.stf ? b.stf : null;
    }
    // 実際の進入・展示タイム・風速で見立て直す
    var ok6 = res.entries.length === 6 && res.entries.every(function (x) { return x.course >= 1 && x.course <= 6; });
    var M2 = null, tA = null, allSt = false;
    if (ok6) {
      var raceA = { vt: D.vt, nt: D.nt, wind: res.wind != null ? res.wind : 2, date: D.race.date, venue: V.code,
                    boats: D.entries.map(function (e) {
                      var x = byW[e.waku] || {};
                      return { waku: e.waku, course: x.course, pts: e.pts || [0, 0], stx: e.stx || [0, 0, 0], r8: e.r8 || [], f: e.f || [],
                               cs: e.cs || {}, motor2: e.motor2, ex: x.ex != null ? x.ex : null };
                    }) };
      M2 = MODEL.predict(raceA, PARAMS, { samples: 300 });
      var byC = {};
      res.entries.forEach(function (x) { byC[x.course] = x; });
      tA = [1, 2, 3, 4, 5, 6].map(function (c) { return validSt(byC[c]); });
      allSt = tA.every(function (x) { return x != null; });
    }
    // STのずれ(実際の進入の順に並べる)
    var order = res.entries.filter(function (x) { return x.course; }).sort(function (a, b) { return a.course - b.course; });
    var devs = [];
    $("#kotaeRows").innerHTML = order.map(function (x, ci) {
      var e = D.entries.filter(function (y) { return y.waku === x.waku; })[0] || {}, s = preST(x.waku), a = validSt(x);
      var d = a != null && s ? a - s.mean : null, tag = "";
      if (d != null) devs.push([d, x, e, s, a]);
      if (allSt && s) {
        var nb = [ci - 1, ci + 1].filter(function (j) { return j >= 0 && j < 6; });
        var lo = Math.min.apply(null, nb.map(function (j) { return tA[j]; })), hi = Math.max.apply(null, nb.map(function (j) { return tA[j]; }));
        if (a <= lo - 0.05) tag = '<span class="up">出た</span>(見立て' + Math.round(s.pOut * 100) + "%)";
        else if (a >= hi + 0.05) tag = '<span class="down">凹んだ</span>(見立て' + Math.round(s.pDent * 100) + "%)";
        else tag = "並び";
      }
      if (x.flying) tag = '<span class="down">フライング</span>';
      else if (String(x.status || "").match(/^L/)) tag = '<span class="down">出遅れ</span>';
      return '<tr><td><span class="waku w' + x.waku + '">' + x.waku + "</span> " + x.course + "</td><td>" + esc(e.name || "") + "</td>" +
        '<td class="num">' + (s ? st2(s.mean) : "—") + '</td><td class="num">' + (x.flying ? "F" : "") + st2(x.st) + "</td>" +
        '<td class="num ' + (d == null ? "" : d <= -0.03 ? "up" : d >= 0.03 ? "down" : "") + '">' + (d == null ? "—" : (d >= 0 ? "+" : "") + d.toFixed(2)) + "</td><td>" + tag + "</td></tr>";
    }).join("");
    var notes = [], lead = "";
    var moved = res.entries.filter(function (x) { return x.course && x.course !== x.waku; }).sort(function (a, b) { return a.course - b.course; });
    if (moved.length) notes.push("進入は枠なりではありませんでした(" + moved.map(function (x) { return x.waku + "号艇が" + x.course + "コース"; }).join("、") +
      ")。締切前の見立ては枠なりの進入で作っています。");
    if (idx == null) {
      lead = "決まり手「" + (res.kimarite || "—") + "」は、見立ての対象外の決着でした。";
    } else {
      var rk = pre.map(function (p, i) { return [p, i]; }).sort(function (a, b) { return b[0] - a[0]; });
      var rank = rk.findIndex(function (x) { return x[1] === idx; }) + 1, p1 = pre[idx] * 100;
      lead = "結果は「" + win.course + "コース" + res.kimarite + "」。" + (logged ? "締切前の見立て" : "見立て(今の式で計算し直したもの)") + "では " +
        p1.toFixed(1) + "%(" + rank + "番目)でした。";
      if (M2) {
        var p2 = M2.p[idx] * 100;
        notes.push("実際の進入・展示タイム・風速" + (res.wind != null ? "(" + res.wind + "m)" : "") + "を入れて見立て直すと " + p2.toFixed(1) + "%。" +
          (Math.abs(p2 - p1) >= 3 ? (p2 > p1 ? "直前の情報で、この展開の可能性は上がっていました。" : "直前の情報では、この展開の可能性はむしろ下がっていました。") : ""));
        if (allSt) {
          var p3 = M2.withST(tA)[idx] * 100;
          notes.push("さらに実際のSTを入れると " + p3.toFixed(1) + "%。" +
            (p3 >= Math.max(p2 * 1.8, p2 + 5) ? "スタートの差がこの展開を作ったレースです。" :
             p3 <= p2 * 0.7 ? "スタートからは起きにくい展開で、1マークのターンや道中で決まったレースです。" :
             "スタートは見立てに近く、決め手はターンの出来でした。"));
        } else notes.push("フライング・出遅れなどがあったため、実際のSTでの計算はしていません。");
      }
      devs.filter(function (x) { return Math.abs(x[0]) >= 0.05; }).sort(function (a, b) { return Math.abs(b[0]) - Math.abs(a[0]); }).slice(0, 2).forEach(function (x) {
        notes.push(x[1].course + "コース" + (x[2].name || "") + "のSTは予想より" + Math.abs(x[0]).toFixed(2) + "秒" + (x[0] < 0 ? "早かった" : "遅かった") +
          "(予想" + st2(x[3].mean) + " → 実際" + st2(x[4]) + ")。");
      });
      if (devs.length) notes.push("STのずれは平均" + avg(devs.map(function (x) { return Math.abs(x[0]); })).toFixed(3) + "秒(" + devs.length + "艇)。この差は毎晩の学習に入り、次の見立てに使われます。");
      if (rk[0][1] !== idx) notes.push("見立ての本線は「" + MODEL.CLASSES[rk[0][1]][0] + "コース" + MODEL.CLASSES[rk[0][1]][1] + "」(" + (rk[0][0] * 100).toFixed(0) + "%)でした。");
      if (["逃げ", "捲り", "差し", "捲り差し"].indexOf(kim) >= 0 && ok6) {
        var cw = {};
        res.entries.forEach(function (x) { cw[x.waku] = x.course; });
        kotaeScen = { course: win.course, kim: kim, courseByWaku: cw,
                      st: tA.map(function (x, ci) { if (x != null) return x; var w = order[ci], s = w ? preST(w.waku) : null; return s ? s.mean : null; }) };
      }
    }
    $("#kotaeLead").textContent = lead;
    $("#kotaeNotes").innerHTML = notes.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("");
    var btn = $("#kotaeView");
    if (btn) btn.hidden = !kotaeScen;
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
    }).join("") + (kotaeScen ? '<button type="button" class="pat' + (showActual ? " on" : "") + '" data-i="actual" aria-pressed="' + showActual + '">結果(実際のST)</button>' : "");
  }
  function updateView(R) {
    lastR = R;
    var canvas = $("#t1view");
    if (!canvas || !window.Turn1) return;
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
    var kb = $("#kotaeView");
    if (kb) kb.addEventListener("click", function () {
      if (!view || !kotaeScen) return;
      showActual = true; showNow();
      var t = $("#t1view"); if (t && t.scrollIntoView) t.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
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

  document.addEventListener("input", render);
  document.addEventListener("change", render);
  var btn = $("#btnCopy");
  if (btn) btn.addEventListener("click", function () {
    var t = $("#post"), msg = $("#copyMsg");
    function sel() { t.focus(); t.select(); msg.textContent = "選択しました。長押しでコピーしてください"; }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t.value).then(function () { msg.textContent = "コピーしました"; }, sel);
    else sel();
  });
  var btnR = $("#btnCopyR");
  if (btnR) btnR.addEventListener("click", function () {
    var t = $("#review"), msg = $("#copyMsgR");
    function sel() { t.focus(); t.select(); msg.textContent = "選択しました。長押しでコピーしてください"; }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t.value).then(function () { msg.textContent = "コピーしました"; }, sel);
    else sel();
  });
  setupViewControls();
  applyBefore();
  render();
})();
