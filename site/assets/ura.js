/* 裏水面ノート(レースのページ): 万舟の見込み・裏本線・荒れる理由・人気と見立てのずれ。
   式は scripts/ura_fit.py・scripts/ura.py と同じ(どちらかを変えたら、もう一方も合わせる)。
   - 3連単120通りの起こりやすさ: 見立て(model.js)の22通りの決着と、決着ごとの2着・3着(orderFor の点数と λ)から
   - 組み合わせごとの「万舟(100倍以上)になる見込み」: オッズがあればオッズから。なければ学習した市場の目安(log 倍 = a + b·log q)から
   - 万舟の見込み: 上の2つを掛けて足したものを、風・波・場・レースの種類・前づけで補正(学習したロジスティック回帰)
   - 裏本線: 表の本線の艇以外で、「その決着になって、しかも万舟になる」見込みが一番高い決着
   ブラウザでもNode(require)でも使える。買い目は出さない。 */
(function (root) {
  "use strict";
  var MODEL = root.SuimenModel || (typeof require === "function" ? require("./model.js") : null);
  var CL = MODEL ? MODEL.CLASSES : [];
  var LN100 = Math.log(100), ODDS_S = 0.12;     // オッズがあるとき: 締切までに少し動くので、100倍の前後は少しなだらかに

  function erf(x) {                              // Abramowitz-Stegun 7.1.26(誤差 1.5e-7)
    var s = x < 0 ? -1 : 1; x = Math.abs(x);
    var t = 1 / (1 + 0.3275911 * x);
    var y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
  }
  function Phi(z) { return 0.5 * (1 + erf(z / Math.SQRT2)); }
  function sig(z) { return 1 / (1 + Math.exp(-z)); }
  function logit(p) { p = Math.min(Math.max(p, 1e-4), 1 - 1e-4); return Math.log(p / (1 - p)); }
  function soft(u, lam) {
    var m = -1e9, s = 0, o = u.map(function (x) { m = Math.max(m, lam * x); return x; });
    o = u.map(function (x) { var e = Math.exp(lam * x - m); s += e; return e; });
    return o.map(function (x) { return x / s; });
  }
  var WIND_B = [[0, 2, "0-2"], [3, 4, "3-4"], [5, 6, "5-6"], [7, 99, "7+"]];
  var WAVE_B = [[0, 2, "0-2"], [3, 5, "3-5"], [6, 9, "6-9"], [10, 999, "10+"]];
  var TIME_B = [[1, 4, "1-4"], [5, 8, "5-8"], [9, 12, "9-12"]];
  function bucket(x, bs) {
    if (x == null || !isFinite(x)) return null;
    for (var i = 0; i < bs.length; i++) if (bs[i][0] <= x && x <= bs[i][1]) return bs[i][2];
    return null;
  }
  function idx(a, b, c) { return (a - 1) * 36 + (b - 1) * 6 + (c - 1); }

  // ---- 3連単(コースの並び)の起こりやすさと、決着ごとの2着・3着(合計1)
  function triOf(Mo) {
    var T = new Float64Array(216), cond = [];
    for (var i = 0; i < CL.length; i++) {
      var o = Mo.order(i), cw = CL[i][0], c = new Float64Array(36);
      if (o && o.u) {
        var rest = [1, 2, 3, 4, 5, 6].filter(function (x) { return x !== cw; });
        var p2 = soft(rest.map(function (x) { return o.u[x]; }), o.lam[0]);
        rest.forEach(function (a, ai) {
          var oth = rest.filter(function (x, j) { return j !== ai; });
          var q = soft(oth.map(function (x) { return o.u[x]; }), o.lam[1]);
          oth.forEach(function (b, bi) { c[(a - 1) * 6 + (b - 1)] += p2[ai] * q[bi]; });
        });
      }
      cond.push(c);
      for (var j = 0; j < 36; j++) T[(cw - 1) * 36 + j] += Mo.p[i] * c[j];
    }
    return { T: T, cond: cond };
  }
  // ---- 組み合わせごとの、万舟になる見込み
  function manG(T, px, odds3t, c2w) {
    var G = new Float64Array(216), nOdds = 0;
    for (var a = 1; a <= 6; a++) for (var b = 1; b <= 6; b++) for (var c = 1; c <= 6; c++) {
      if (a === b || b === c || a === c) continue;
      var k = idx(a, b, c), od = odds3t && c2w ? odds3t[c2w[a] + "-" + c2w[b] + "-" + c2w[c]] : null;
      if (od && od > 0) { G[k] = Phi((Math.log(od) - LN100) / ODDS_S); nOdds++; }
      else G[k] = Phi((px.a + px.b * Math.log(Math.max(T[k], 1e-7)) - LN100) / px.s);
    }
    return { G: G, odds: nOdds >= 60 };
  }
  function maeduke(B) { return B.some(function (b) { return b.waku != null && b.waku > b.course && b.waku >= 3; }); }
  // 補正の特徴(scripts/ura_fit.py の feat と同じ並び)
  function feats(m, x, cal) {
    var f = [1, logit(m)], wb = bucket(x.wind, WIND_B), vb = bucket(x.wave, WAVE_B);
    cal.wind.slice(1).forEach(function (n) { f.push(wb === n ? 1 : 0); });
    cal.wave.slice(1).forEach(function (n) { f.push(vb === n ? 1 : 0); });
    cal.kinds.forEach(function (k) { f.push(x.kind === k ? 1 : 0); });
    f.push(x.mz ? 1 : 0);
    cal.vens.forEach(function (v) { f.push(x.v === v ? 1 : 0); });
    return f;
  }
  function calib(m, x, cal) { var f = feats(m, x, cal), z = 0; for (var i = 0; i < f.length; i++) z += f[i] * (cal.w[i] || 0); return sig(z); }

  // ---- まとめて計算する
  //   Mo: model.js の predict の戻り値、B: 6艇 [{waku, course, …}]、ctx: {venue, name, wind, wave, odds(odds.js が読んだもの)}
  function compute(Mo, B, ctx, UP) {
    if (!Mo || !UP || !UP.proxy || !UP.cal) return null;
    var c2w = {}, byC = {};
    B.forEach(function (b) { c2w[b.course] = b.waku; byC[b.course] = b; });
    var tc = triOf(Mo), T = tc.T, O = ctx.odds || null;
    var mg = manG(T, UP.proxy, O && O["3t"], c2w), G = mg.G;
    var x = { wind: ctx.wind, wave: ctx.wave, kind: MODEL.raceKind(ctx.name), mz: maeduke(B), v: ctx.venue };
    var m = 0;
    for (var k = 0; k < 216; k++) m += T[k] * G[k];
    var pMan = calib(m, x, UP.cal);
    // 1着の見込み(艇ごと)と、表の本線の艇
    var pc = [0, 0, 0, 0, 0, 0];
    Mo.p.forEach(function (p, i) { pc[CL[i][0] - 1] += p; });
    var oc = pc.indexOf(Math.max.apply(null, pc)) + 1;
    // 決着ごと: その決着になって万舟になる見込み
    var scen = CL.map(function (ck, i) {
      var cw = ck[0], mk = 0, c = tc.cond[i];
      for (var j = 0; j < 36; j++) mk += c[j] * G[(cw - 1) * 36 + j];
      var pk = calib(mk, x, UP.cal);
      return { i: i, c: cw, k: ck[1], b: byC[cw], p: Mo.p[i], pk: pk, s: Mo.p[i] * pk };
    });
    var cands = scen.filter(function (s) { return s.c !== oc && s.k !== "抜き"; }).sort(function (a, b) { return b.s - a.s; });
    var lead = cands[0] || null;
    // 人気(単勝オッズ)と見立てのずれ
    var pop = null;
    if (O && O.tan) {
      var inv = B.map(function (b) { var t = O.tan[String(b.waku)]; return t && t > 0 ? 1 / t : 0; }), s = inv.reduce(function (a, v) { return a + v; }, 0);
      if (s > 0 && inv.filter(function (v) { return v > 0; }).length >= 5) {
        var rows = B.map(function (b, j) {
          var pm = inv[j] / s, pw = pc[b.course - 1];
          var f0 = O.first && O.first.tan ? O.first.tan[String(b.waku)] : null, od = O.tan[String(b.waku)];
          return { b: b, odds: od, pm: pm, pw: pw, ratio: pm > 0 ? pw / pm : null, f0: f0 > 0 ? f0 : null, mv: f0 > 0 && od > 0 ? od / f0 : null };
        });
        var order = rows.slice().sort(function (a, b) { return b.pm - a.pm; });
        order.forEach(function (r, j) { r.rank = j + 1; });
        var mOrder = rows.slice().sort(function (a, b) { return b.pw - a.pw; });
        mOrder.forEach(function (r, j) { r.mrank = j + 1; });
        var value = rows.filter(function (r) { return r.b.course !== oc && r.pw >= 0.05 && r.ratio >= 1.3; }).sort(function (a, b) { return b.ratio - a.ratio; });
        pop = { rows: rows, value: value, over: rows.filter(function (r) { return r.pm - r.pw >= 0.08; }).sort(function (a, b) { return (b.pm - b.pw) - (a.pm - a.pw); }) };
      }
    }
    return { T: T, G: G, m: m, pMan: pMan, x: x, pc: pc, oc: oc, scen: scen, cands: cands, lead: lead, pop: pop, odds: mg.odds, c2w: c2w, byC: byC };
  }

  // ---- 荒れの目安の言葉
  function venueBase(UP, v) { var s = ((UP.stats || {}).ven || {})[v]; return s ? s[0] / 100 : ((UP.stats || {}).nat || 16) / 100; }
  function level(p, base) {
    var r = p / Math.max(base, 0.01);
    return r >= 1.5 ? ["大荒れ注意", "L3"] : r >= 1.15 ? ["荒れ気味", "L2"] : r >= 0.85 ? ["ふつう", "L1"] : ["平穏", "L0"];
  }

  // ---- 荒れる理由(根拠の数字と一緒に)。w は並べる順(大きいほど上)
  function reasons(U, ctx, UP) {
    var out = [], st = UP.stats || {}, v = ctx.venue, base = venueBase(UP, v), nat = (st.nat || 16) / 100;
    var B = ctx.B, byC = U.byC, b1 = byC[1];
    function pc(x) { return Math.round(x * 100) + "%"; }
    // 場
    if (base >= nat * 1.12) out.push({ w: 2, t: ctx.vname + "はもともと荒れやすい場です(万舟率 " + pc(base) + "、全国 " + pc(nat) + ")。" });
    else if (base <= nat * 0.88) out.push({ w: 1, t: ctx.vname + "は荒れにくい場です(万舟率 " + pc(base) + "、全国 " + pc(nat) + ")。荒れるときは展開の崩れが必要です。" });
    // 風・波
    var wb = bucket(ctx.wind, WIND_B), wv = (((st.wind || {})[v] || {})[wb] || null);
    if (wb && wb !== "0-2" && wv && wv[1] >= 30) {
      var d = wv[0] / 100 - base;
      out.push({ w: 3 + d * 20, t: "風速" + ctx.wind + "m" + (ctx.weatherPre ? "(先のレースの直前情報から)" : "") + "。この場で風速" + wb.replace("7+", "7m以上").replace(/^(\d)-(\d)$/, "$1〜$2m") +
        "のときの万舟率は " + pc(wv[0] / 100) + "(ふだん " + pc(base) + ")。" + (ctx.wind >= 5 ? "スタートが全体に遅れ、ばらつきも大きくなります。" : "") });
    }
    var vb = bucket(ctx.wave, WAVE_B), vv = (((st.wave || {})[v] || {})[vb] || null);
    if (vb && vb !== "0-2" && vv && vv[1] >= 30) {
      out.push({ w: 3 + (vv[0] / 100 - base) * 20, t: "波" + ctx.wave + "cm。この場で波が" + vb.replace("10+", "10cm以上").replace(/^(\d+)-(\d+)$/, "$1〜$2cm") +
        "のときの万舟率は " + pc(vv[0] / 100) + "(ふだん " + pc(base) + ")。旋回で流れやすく、1マークがもつれやすい水面です。" });
    }
    // 1号艇(1コース)の不安
    var p1 = U.pc[0], pl = ctx.place1 != null ? ctx.place1 / 100 : null;
    if (b1) {
      var bad = [];
      var cs1 = (b1.cs || {})["1"] || null;
      if (cs1 && cs1.n >= 5 && cs1.w1 / cs1.n < 0.4) bad.push("1コースの1着率 " + Math.round(cs1.w1 / cs1.n * 100) + "%(" + cs1.n + "走)");
      if ((b1.fp || 0) > 0) bad.push("今期F" + b1.fp + "でスタートを控えやすい");
      if (b1.stf && b1.stf.pDent >= 0.15) bad.push("スタートで凹む見込み " + Math.round(b1.stf.pDent * 100) + "%");
      if (ctx.exRank && ctx.exRank[b1.waku] >= 5) bad.push("展示タイムは" + ctx.exRank[b1.waku] + "番目");
      if (b1.mgGrade && /^[DE]$/.test(b1.mgGrade)) bad.push("モーター評価 " + b1.mgGrade);
      if (/^B/.test(b1.cls || "")) bad.push(b1.cls + "級");
      var p1row = (st.p1 || []).filter(function (r) { return p1 * 100 >= r[0] && p1 * 100 < r[1]; })[0];
      if (pl != null && p1 < pl - 0.06) {
        out.push({ w: 4 + (pl - p1) * 20, t: "1コースの" + (b1.name || "") + "(" + b1.waku + "号艇)は1着の見込みが " + pc(p1) + "で、この場の1コースの1着率(" + pc(pl) + ")より低めです。" +
          (bad.length ? "(" + bad.join("・") + ")" : "") + (p1row ? "全国で1コースの見込みがこのくらいのレースの万舟率は " + p1row[2] + "%。" : "") });
      } else if (bad.length >= 2) {
        out.push({ w: 2.5, t: "1コースの" + (b1.name || "") + "(" + b1.waku + "号艇)に不安材料があります(" + bad.join("・") + ")。" });
      }
    }
    // 外の攻め手(3〜6コース)
    B.filter(function (b) { return b.course >= 3; }).forEach(function (b) {
      var why = [], cs = (b.cs || {})[String(b.course)] || {}, km = cs.km || {};
      var mk = (km["捲り"] || 0) + (km["捲り差し"] || 0);
      if (cs.n >= 10 && mk / cs.n >= 0.08) why.push(b.course + "コースで捲り・捲り差しの1着が " + mk + "回(" + cs.n + "走)");
      if (b.stf && b.stf.pOut >= 0.18) why.push("一撃スタートの見込み " + Math.round(b.stf.pOut * 100) + "%");
      if (ctx.exRank && ctx.exRank[b.waku] === 1) why.push("展示タイム1位");
      if (b.mgGrade && /^(S\+|S|A)$/.test(b.mgGrade)) why.push("モーター評価 " + b.mgGrade);
      if (why.length >= 2) out.push({ w: 2 + why.length * 0.6 + (U.pc[b.course - 1] || 0) * 4, t: b.course + "コースの" + (b.name || "") + "(" + b.waku + "号艇)に攻めの材料がそろっています(" + why.join("・") + ")。" });
    });
    // 進入
    if (U.x.mz && st.mz && st.mz[0]) out.push({ w: 3, t: "前づけで進入が乱れています。全国で前づけがあったレースの万舟率は " + st.mz[0][0] + "%(ないとき " + (st.mz[1] ? st.mz[1][0] : "—") + "%)。" });
    // 裏目: 表の本線が崩れたときの形
    var oc = U.oc, rest = U.scen.filter(function (s) { return s.c !== oc; }), tot = rest.reduce(function (a, s) { return a + s.p; }, 0);
    var top = rest.slice().sort(function (a, b) { return b.p - a.p; })[0];
    if (top && tot > 0) {
      var kk = ((st.kim || {})[top.c + top.k] || null);
      out.push({ w: 2.2, t: "表の本線(" + oc + "コース)が崩れたときに一番多いのは「" + top.c + "コース" + top.k + "」(崩れたときの " + pc(top.p / tot) + ")。" +
        (kk ? "全国でこの決着になったときの万舟率は " + kk[0] + "%。" : "") });
    }
    // 人気とのずれ(オッズが出たあと)
    if (U.pop) {
      U.pop.over.slice(0, 1).forEach(function (r) {
        out.push({ w: 4.5, t: r.b.waku + "号艇は単勝" + r.odds.toFixed(1) + "倍(人気からの見込み " + pc(r.pm) + ")で、見立て(" + pc(r.pw) + ")より売れています。崩れたときの配当がふくらみます。" });
      });
      // 締切前に単勝が大きく下がった(売れた)艇(表の本線の艇を除く)
      U.pop.rows.filter(function (r) { return r.mv != null && r.mv <= 0.7 && r.f0 >= 3 && r.b.course !== U.oc; }).sort(function (a, b) { return a.mv - b.mv; }).slice(0, 1).forEach(function (r) {
        out.push({ w: 4.2, t: r.b.waku + "号艇は締切前に単勝が大きく売れています(約15分前 " + r.f0.toFixed(1) + "倍→" + r.odds.toFixed(1) + "倍)。" });
      });
      U.pop.value.slice(0, 2).forEach(function (r) {
        out.push({ w: 4.4, t: r.b.waku + "号艇は" + r.rank + "番人気(単勝" + r.odds.toFixed(1) + "倍・人気からの見込み " + pc(r.pm) + ")ですが、見立てでは1着 " + pc(r.pw) + "。人気より見立てが上です。" });
      });
    }
    out.sort(function (a, b) { return b.w - a.w; });
    return out;
  }

  var api = { compute: compute, reasons: reasons, level: level, venueBase: venueBase, triOf: triOf, manG: manG, feats: feats, calib: calib, bucket: bucket,
              WIND_B: WIND_B, WAVE_B: WAVE_B, TIME_B: TIME_B, Phi: Phi };
  root.SuimenUra = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
