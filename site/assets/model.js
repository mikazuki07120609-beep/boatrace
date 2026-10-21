/* 水面ノートの見立てモデル(scripts/fit.py と同じ式。どちらかを変えたら、もう一方も合わせる)。
   1) スタートの見立て: 選手ごとの予想ST(平均ST・コース・フライング持ち・風)と、過去のレースで実際に起きた
      スタートのずれ方(全員そろって遅れる日、スロー勢とダッシュ勢でずれる日、たまに大きく出遅れる艇)を当てはめた多数の組み合わせ
   2) 展開の見立て: STの組み合わせごとに、どのコースがどの決まり手で1着になりやすいか(条件付きロジット)
   本番前はSTが分からないので、1)の多数の組み合わせで2)を平均する。
   使い方: var R = SuimenModel.predict(race, params, {samples: 400});
     race = {vt, nt, wind, date, venue, boats: [{waku, course, pts, stx, r8, f, cs, motor2, motorR, lv, ex, est}]}
   ブラウザでもNode(require)でも使える。 */
(function (root) {
  "use strict";
  var KIMS = ["逃げ", "捲り", "差し", "捲り差し", "抜き"];
  var CLASSES = [[1, "逃げ"], [1, "抜き"]];
  for (var c0 = 2; c0 <= 6; c0++) ["捲り", "差し", "捲り差し", "抜き"].forEach(function (k) { CLASSES.push([c0, k]); });
  var CI = {};
  CLASSES.forEach(function (ck, i) { CI[ck[0] + ck[1]] = i; });
  var NC = CLASSES.length;
  var NAT_FALLBACK = [0.55, 0.14, 0.13, 0.1, 0.06, 0.02];

  function group(c) { return c === 2 ? 0 : c === 3 ? 1 : c === 4 ? 2 : 3; }
  function rng(seed) {                       // 同じページでは同じ結果になるよう、種を固定した乱数
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function periodStart(iso) {               // フライングの回数を数える期の始まり(5月1日・11月1日)
    var y = +iso.slice(0, 4), m = +iso.slice(5, 7);
    if (m >= 11) return y + "-11-01";
    if (m >= 5) return y + "-05-01";
    return (y - 1) + "-11-01";
  }
  function cnt(tbl, c, k) {
    var km = (tbl[c] || {}).km || {};
    return (km[k] || 0) + (k === "抜き" ? (km["恵まれ"] || 0) : 0);
  }

  // 場の傾向(全国の傾向で補ったもの)から、コース×決まり手の起こりやすさ
  function prior(vt, nt, K) {
    var pc = [], c, s = 0;
    for (c = 1; c <= 6; c++) {
      var n = nt[c] || { n: 0, w1: 0 }, v = vt[c] || { n: 0, w1: 0 };
      var natRate = n.n ? n.w1 / n.n : NAT_FALLBACK[c - 1];
      pc.push((v.w1 + K.VEN_M * natRate) / (v.n + K.VEN_M));
      s += pc[c - 1];
    }
    pc = pc.map(function (x) { return x / (s || 1); });
    var q = {};
    for (c = 1; c <= 6; c++) {
      var ks = c === 1 ? ["逃げ", "抜き"] : ["捲り", "差し", "捲り差し", "抜き"];
      var ntot = 0, vtot = 0;
      ks.forEach(function (k) { ntot += cnt(nt, c, k); vtot += cnt(vt, c, k); });
      var qs = 0;
      ks.forEach(function (k) {
        var nq = (cnt(nt, c, k) + 0.5) / (ntot + 0.5 * ks.length);
        q[c + k] = (cnt(vt, c, k) + K.VEN_KM * nq) / (vtot + K.VEN_KM);
        qs += q[c + k];
      });
      ks.forEach(function (k) { q[c + k] /= qs || 1; });
    }
    return { pc: pc, q: q };
  }
  function lossShare(nt) {
    var tot = { "捲り": 0, "差し": 0, "捲り差し": 0 }, s = 0;
    for (var c = 2; c <= 6; c++) Object.keys(tot).forEach(function (k) { tot[k] += ((nt[c] || {}).km || {})[k] || 0; });
    Object.keys(tot).forEach(function (k) { s += tot[k]; });
    var out = {};
    Object.keys(tot).forEach(function (k) { out[k] = s ? tot[k] / s : 1 / 3; });
    return out;
  }

  // ---- スタートの見立て
  function racerScale(sm, stx) {
    var n = stx[0], s1 = stx[1], s2 = stx[2], sp2 = sm.sd_pop * sm.sd_pop;
    var v = n >= 2 ? (s2 - s1 * s1 / n) / n : sp2;
    v = (n * Math.max(v, 0) + 10 * sp2) / (n + 10);
    return Math.sqrt(v / sp2);
  }
  // 6艇の予想ST(fit.py の start_means と同じ式): 選手の平均ST(走数で全体の平均に寄せる)・コース・フライング持ち(F1/F2)・風・
  // 直近8走の調子・隣の艇のスタートの傾向・場の補正
  function startParts(sm, byC, wind, venue) {
    var co = sm.coef, K = sm.K, RK = sm.REC_K || 4;
    function mrOf(stx) { return (stx[1] + K * sm.m_pop) / (stx[0] + K); }
    var parts = byC.map(function (b, i) {
      var stx = b.stx || [0, 0, 0], mr = mrOf(stx), r8 = b.r8 || [], rec = 0, nb = 0, nn = 0, r8m = null;
      if (r8.length) { r8m = r8.reduce(function (a, x) { return a + x; }, 0) / r8.length; rec = (r8m * r8.length + RK * mr) / (r8.length + RK) - mr; }
      [i - 1, i + 1].forEach(function (j) { if (j >= 0 && j < 6) { nb += mrOf(byC[j].stx || [0, 0, 0]); nn++; } });
      nb = nn ? nb / nn - sm.m_pop : 0;
      var c = b.course, p = { mr: mr, r8m: r8m, n8: r8.length, base: co.a + co.b * mr, course: c >= 2 ? (co["c" + c] || 0) : 0,
                              f: b.fp > 0 ? co.f : 0, f2: b.fp >= 2 ? (co.f2 || 0) : 0, wind: co.wind * Math.max(0, (wind || 0) - 3),
                              rec: (co.rec || 0) * rec, nb: (co.nb || 0) * nb, ven: (sm.ven || {})[venue] || 0 };
      p.mu = p.base + p.course + p.f + p.f2 + p.wind + p.rec + p.nb + p.ven;
      p.est = 0;
      return p;
    });
    // 展示ST: 展示は本番より全体に早く出る(フライングしても罰がないため)ので、6艇の中で早いか遅いか(差)だけを使う。
    // 展示で他の艇より早かった艇ほど、本番も他の艇より早く出やすい(効き方は学習した値。まだ学習できていないうちは0.35)
    var ok = byC.map(function (b) { return b.est != null && isFinite(b.est); }), n = ok.filter(Boolean).length;
    if (n >= 4) {
      var es = byC.map(function (b) { return Math.max(-0.02, Math.min(0.35, b.est)); }), mE = 0, mM = 0;
      parts.forEach(function (p, i) { if (ok[i]) { mE += es[i] / n; mM += p.mu / n; } });
      var k = co.est != null ? co.est : 0.35;
      parts.forEach(function (p, i) { if (ok[i]) { p.est = k * ((es[i] - mE) - (p.mu - mM)); p.mu += p.est; } });
    }
    return parts;
  }
  function startMeans(sm, byC, wind, venue) { return startParts(sm, byC, wind, venue).map(function (p) { return p.mu; }); }

  // ---- 展開の見立て: STに関係しない点数(クラスごと)
  function staticU(race, P) {
    var K = P.const, th = P.dev, B = race.byC, pr = prior(race.vt, race.nt, K), u = new Array(NC);
    var pts = B.map(function (b) { return (b.pts[0] + K.PTS_K * K.PTS_MEAN) / (b.pts[1] + K.PTS_K); });
    var mp = pts.reduce(function (s, x) { return s + x; }, 0) / 6;
    var mots = B.map(function (b) { return b.motorR != null ? b.motorR : null; }), mm = mots.filter(function (x) { return x != null; });   // 成績の2連率(学習と同じ)
    var mmean = mm.length ? mm.reduce(function (s, x) { return s + x; }, 0) / mm.length : null;
    var LK = K.LOC_K || 8, locd = B.map(function (b, i) { var lv = b.lv || [0, 0]; return (lv[0] + LK * pts[i]) / (lv[1] + LK) - pts[i]; });
    var mloc = locd.reduce(function (s, x) { return s + x; }, 0) / 6;
    var ls1 = ((B[0].cs || {})["1"] || {}).ls || {}, lsh = lossShare(race.nt), lsw = 0;
    Object.keys(lsh).forEach(function (k) { lsw += ls1[k] || 0; });
    var exs = B.map(function (b) { return b.ex; }), exOk = exs.every(function (x) { return x != null && isFinite(x) && x >= 6.0 && x <= 7.6; });
    var exMean = exOk ? exs.reduce(function (s, x) { return s + x; }, 0) / 6 : null;
    var parts = [];                        // 理由の説明に使う、項ごとの点数
    CLASSES.forEach(function (ck, i) {
      var c = ck[0], k = ck[1], b = B[c - 1], cs = (b.cs || {})[String(c)] || { n: 0, w1: 0, km: {} };
      var v = Math.log(Math.max(1e-6, pr.pc[c - 1] * pr.q[c + k])), base = pr.pc[c - 1];
      var p = { prior: v };
      p.d = th["d_" + c + k] || 0;
      p.str = (th["str_" + k] || 0) * (pts[c - 1] - mp);
      p.loc = (th.loc || 0) * (locd[c - 1] - mloc);                   // 当地の相性
      p.rec = th.rec * Math.log(((cs.w1 + K.REC_K * base) / (cs.n + K.REC_K)) / base);
      p.mot = mmean != null && mots[c - 1] != null ? th.mot * (mots[c - 1] - mmean) / 10 : 0;
      p.ex = exOk ? ((th.ex || 0) + (k === "捲り" || k === "捲り差し" ? (th.ex_mk || 0) : 0)) * (exMean - exs[c - 1]) / 0.05 : 0;
      p.tac = 0; p.ls = 0;
      if (c >= 2 && (k === "捲り" || k === "差し" || k === "捲り差し")) {
        var km = cs.km || {}, W = (km["捲り"] || 0) + (km["差し"] || 0) + (km["捲り差し"] || 0);
        var q3 = pr.q[c + "捲り"] + pr.q[c + "差し"] + pr.q[c + "捲り差し"], qk = pr.q[c + k] / q3;
        p.tac = th.tac * Math.log((((km[k] || 0) + K.TAC_K * qk) / (W + K.TAC_K)) / qk);
        p.ls = th.ls * Math.log((((ls1[k] || 0) + K.LS_K * lsh[k]) / (lsw + K.LS_K)) / lsh[k]);
      }
      u[i] = v + p.d + p.str + p.loc + p.rec + p.mot + p.ex + p.tac + p.ls;
      parts.push(p);
    });
    return { u: u, parts: parts, prior: pr };
  }

  // STの組み合わせ t[0..5](1〜6コース)で変わる点数を u に足す
  function addST(u, t, wind, P) {
    var th = P.dev, Uu = P.const.U, c;
    var lag = (t[0] - Math.min(t[1], t[2])) / Uu;
    var mn = Math.min(t[1], t[2], t[3], t[4], t[5]);
    u[CI["1逃げ"]] += th.n1_lag * lag + th.n1_big * Math.max(0, t[0] - mn - 0.04) / Uu;
    var inner = t[0];
    for (c = 2; c <= 6; c++) {
      var g = group(c);
      var L = (inner - t[c - 1]) / Uu, N = (t[c - 2] - t[c - 1]) / Uu, A = 0, O = 0, H = 0;
      if (c >= 3) {
        var in2 = t[0];
        for (var j = 1; j < c - 2; j++) in2 = Math.min(in2, t[j]);
        A = (in2 - t[c - 2]) / Uu;
        H = (t[c - 2] - Math.min(t[c - 3], t[c - 1])) / Uu;
      }
      if (c <= 5) O = (Math.min(inner, t[c - 1]) - t[c]) / Uu;
      u[CI[c + "捲り"]] += th["mk1_" + g] * L + th["mk2_" + g] * Math.max(0, L - 0.8);
      u[CI[c + "差し"]] += th["sa1_" + g] * N + th["sa2_" + g] * Math.max(0, A) + th["sa3_" + g] * Math.max(0, O);
      u[CI[c + "捲り差し"]] += th["ms1_" + g] * N + th["ms2_" + g] * Math.max(0, H) + th["ms3_" + g] * Math.max(0, A);
      inner = Math.min(inner, t[c - 1]);
    }
    var w = Math.max(0, (wind || 0) - 3);
    if (w) {
      u[CI["1逃げ"]] += th.w_nige * w;
      for (c = 2; c <= 6; c++) { u[CI[c + "捲り"]] += th.w_mk * w; u[CI[c + "差し"]] += th.w_sa * w; u[CI[c + "捲り差し"]] += th.w_ms * w; }
    }
    return u;
  }
  function softmax(u) {
    var m = -Infinity, i, s = 0, p = new Array(u.length);
    for (i = 0; i < u.length; i++) if (u[i] > m) m = u[i];
    for (i = 0; i < u.length; i++) { p[i] = Math.exp(u[i] - m); s += p[i]; }
    for (i = 0; i < u.length; i++) p[i] /= s;
    return p;
  }

  // ---- まとめて見立てを作る
  function predict(race, P, opt) {
    opt = opt || {};
    var S = opt.samples || 400, sm = P.start, R = rng(opt.seed || 20261021);
    var byC = [];
    race.boats.forEach(function (b) { byC[b.course - 1] = b; });
    for (var c = 0; c < 6; c++) if (!byC[c]) return null;           // 6艇そろっていないレースは見立てない
    var ps = periodStart(race.date || "2026-10-01");
    byC.forEach(function (b) {
      b.fp = (b.f || []).filter(function (x) { return x >= ps && x < (race.date || "9999"); }).length;
      b.scale = racerScale(sm, b.stx || [0, 0, 0]) * (b.est != null && isFinite(b.est) ? (sm.est_scale || 0.9) : 1);   // 展示STが分かれば、ばらつきは小さくなる
    });
    var parts = startParts(sm, byC, race.wind, race.venue);
    byC.forEach(function (b, i) { b.mu = parts[i].mu; });
    race.byC = byC;
    var st0 = staticU(race, P), pool = sm.pool, acc = new Array(NC).fill(0);
    var samples = [], probs = [];
    for (var s = 0; s < S; s++) {
      var z = pool[Math.floor(R() * pool.length)], t = new Array(6);
      for (c = 0; c < 6; c++) t[c] = Math.min(0.45, Math.max(0, byC[c].mu + byC[c].scale * z[c]));
      var p = softmax(addST(st0.u.slice(), t, race.wind, P));
      for (var i = 0; i < NC; i++) acc[i] += p[i];
      samples.push(t); probs.push(p);
    }
    var pm = acc.map(function (x) { return x / S; });
    // 艇ごとのスタートの見立て: 予想ST・隣より0.05秒以上早い(出る)・遅い(凹む)確率
    var st = byC.map(function (b, ci) {
      var nb = [ci - 1, ci + 1].filter(function (j) { return j >= 0 && j < 6; }), out = 0, dent = 0, sum = 0, xs = [];
      samples.forEach(function (t) {
        var lo = Math.min.apply(null, nb.map(function (j) { return t[j]; })), hi = Math.max.apply(null, nb.map(function (j) { return t[j]; }));
        if (t[ci] <= lo - 0.05) out++;
        if (t[ci] >= hi + 0.05) dent++;
        sum += t[ci]; xs.push(t[ci]);
      });
      xs.sort(function (a, b) { return a - b; });
      return { course: ci + 1, waku: b.waku, mu: b.mu, mean: sum / S, lo: xs[Math.floor(S * 0.3)], hi: xs[Math.floor(S * 0.7)],   // 10回に4回はこの幅
               pOut: out / S, pDent: dent / S, scale: b.scale, fp: b.fp, parts: parts[ci] };
    });
    // 決着パターンごとの「よくあるSTの組み合わせ」(そのパターンが起きやすいSTの組み合わせほど重く数えた平均)
    function postST(i) {
      var w = 0, m = [0, 0, 0, 0, 0, 0];
      samples.forEach(function (t, s) { var x = probs[s][i]; w += x; for (var c = 0; c < 6; c++) m[c] += x * t[c]; });
      return m.map(function (x) { return w ? x / w : null; });
    }
    // ある艇が「出た」とき・「凹んだ」ときの見立て(その場合に一番起こりやすい決着)
    function whenBoat(ci, kind) {
      var a = new Array(NC).fill(0), n = 0;
      samples.forEach(function (t, s) {
        var nb = [ci - 1, ci + 1].filter(function (j) { return j >= 0 && j < 6; });
        var lo = Math.min.apply(null, nb.map(function (j) { return t[j]; })), hi = Math.max.apply(null, nb.map(function (j) { return t[j]; }));
        var hit = kind === "out" ? t[ci] <= lo - 0.05 : t[ci] >= hi + 0.05;
        if (!hit) return;
        n++;
        for (var i = 0; i < NC; i++) a[i] += probs[s][i];
      });
      return n >= 8 ? { n: n, p: a.map(function (x) { return x / n; }) } : null;
    }
    return { classes: CLASSES, p: pm, st: st, staticU: st0, postST: postST, whenBoat: whenBoat, samples: samples, probs: probs,
             order: function (i) { return orderFor(race, P, i, postST(i)); },
             withST: function (t) { return softmax(addST(st0.u.slice(), t, race.wind, P)); } };
  }

  // ---- 2着〜6着の並び(fit.py の order_feats・order_model と同じ式)。ci: 決着パターン、t: そのパターンでのST(1〜6コース)
  //      戻り値: { order: [1着のコース, 2着, …6着], p2: {コース: 2着になる確率}, p3: {コース: 3着になる確率} }
  var KG = { "逃げ": 0, "捲り": 1, "差し": 2, "捲り差し": 3, "抜き": 4 };
  function orderFor(race, P, ci, t) {
    var O = P && P.order, B = race.byC;
    if (!O || !B || B.length !== 6) return null;
    var cw = CLASSES[ci][0], k = CLASSES[ci][1], alpha = O.alpha[k], beta = O.beta, K = P.const;
    var pts = B.map(function (b) { return ((b.pts || [0, 0])[0] + K.PTS_K * K.PTS_MEAN) / ((b.pts || [0, 0])[1] + K.PTS_K); });
    var mp = pts.reduce(function (s, x) { return s + x; }, 0) / 6;
    var sts = t && t.length === 6 ? t : B.map(function (b) { return b.mu; }), sm = sts.reduce(function (s, x) { return s + x; }, 0) / 6;
    var exs = B.map(function (b) { return b.ex; }), exOk = exs.every(function (x) { return x != null && isFinite(x) && x >= 6.0 && x <= 7.6; });
    var exm = exOk ? exs.reduce(function (s, x) { return s + x; }, 0) / 6 : null;
    var mots = B.map(function (b) { return b.motorR != null ? b.motorR : null; }), mm = mots.filter(function (x) { return x != null; });
    var mmean = mm.length ? mm.reduce(function (s, x) { return s + x; }, 0) / mm.length : null;
    var LK = K.LOC_K || 8, locd = B.map(function (b, i) { var lv = b.lv || [0, 0]; return (lv[0] + LK * pts[i]) / (lv[1] + LK) - pts[i]; });
    var mloc = locd.reduce(function (s, x) { return s + x; }, 0) / 6;
    var u = {};
    B.forEach(function (b, i) {
      var c = i + 1;
      if (c === cw) return;
      var cs = (b.cs || {})[String(c)] || {}, bc = O.base2[i], cb = b.cb || [0, 0];
      var x = { str: pts[i] - mp, st: (sm - sts[i]) / K.U, ex: exOk ? (exm - exs[i]) / 0.05 : 0,
                mot: mmean != null && mots[i] != null ? (mots[i] - mmean) / 10 : 0,
                c2: Math.log((((cs.w2 || 0) + O.K2 * bc) / ((cs.n || 0) + O.K2)) / bc), cb: ((cb[0] + 2.5) / (cb[1] + 5) - 0.5) * 4 };
      if (O.base3) {                                      // このコースの3連対率と、当地の相性(fit.py の order_feats と同じ式)
        var b3 = O.base2[i] + O.base3[i] + 0.1;
        x.top3 = Math.log((((cs.w1 || 0) + (cs.w2 || 0) + (cs.w3 || 0) + O.K2 * b3) / ((cs.n || 0) + O.K2)) / b3);
        x.loc = locd[i] - mloc;
      }
      var d = c - cw, v = alpha[d < 0 ? d + 5 : d + 4];
      Object.keys(beta).forEach(function (n) { v += beta[n] * (x[n] || 0); });
      u[c] = v;
    });
    var rest = Object.keys(u).map(Number), order = rest.slice().sort(function (a, b) { return u[b] - u[a]; });
    function soft(set, lam) { var m = -1e9, s = 0, o = {}; set.forEach(function (c) { m = Math.max(m, lam * u[c]); }); set.forEach(function (c) { o[c] = Math.exp(lam * u[c] - m); s += o[c]; }); set.forEach(function (c) { o[c] /= s; }); return o; }
    var p2 = soft(rest, O.lam[0]), p3 = {};
    rest.forEach(function (c) { p3[c] = 0; });
    rest.forEach(function (a) {                       // 3着の確率: 2着がそれぞれの艇だったときの和
      var q = soft(rest.filter(function (c) { return c !== a; }), O.lam[1]);
      Object.keys(q).forEach(function (c) { p3[c] += p2[a] * q[c]; });
    });
    return { order: [cw].concat(order), p2: p2, p3: p3, u: u };
  }

  var api = { predict: predict, orderFor: orderFor, CLASSES: CLASSES, CI: CI, prior: prior, startMeans: startMeans, startParts: startParts, racerScale: racerScale,
              staticU: staticU, addST: addST, softmax: softmax, periodStart: periodStart };
  root.SuimenModel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
