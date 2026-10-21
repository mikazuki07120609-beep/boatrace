/* 1周1マーク シミュレーション
   出走表のデータ(平均ST・モーター・展示タイム・級別・進入コース)と、展開の見立て(決着パターン)から、
   スタートから全艇が1周1マークを回り切るまでを、上空から見た映像として描く。
   各艇は、スタート後の位置関係から自分の行き方(逃げ・差し・捲り・捲り差し・外を回す)を選び、
   スタートが良ければ内に絞り、前の艇との間合い(速度)と横の艇との間隔を自分で取りながら走る。
   単位はメートルと秒。ホームストレッチを左から右へ走り、右の1マークを左回りに回る。
   使い方: var v = Turn1.mount(canvas, {entries:[{waku,course,name,st,motor2,ex,cls}], scen:{course,kim,p}, kimarite, title});
           v.play(); v.replay(); v.setScenario(scen); v.record() -> Promise<Blob>(対応ブラウザのみ) */
(function (root) {
  "use strict";
  var D = 140;                                   // スタートラインから1マークまでの距離
  var BUOY = { x: D, y: 0 }, BUOY2 = { x: D - 300, y: 0 }, BUOY_R = 1.25;
  var CLEAR = 3.4;                               // ブイの中心から艇の中心まで、必ず空ける距離
  var LANE0 = 7, LANE_W = 6;                     // スタート時の横位置(1コースが一番内側)
  var HULL_L = 4.4, HULL_W = 1.8;
  var T0 = -2.6, DT = 1 / 60, T_MAX = 22;        // スタートの2.6秒前から描く
  var COLORS = { 1: ["#f4f6f8", "#14212b"], 2: ["#1b1b1b", "#ffffff"], 3: ["#d7282f", "#ffffff"],
                 4: ["#1d5fbf", "#ffffff"], 5: ["#f2cf1d", "#14212b"], 6: ["#1f9a4b", "#ffffff"] };
  var FONT = '"Zen Kaku Gothic New","Hiragino Sans","Noto Sans JP",sans-serif';
  var MONO = '"IBM Plex Mono",ui-monospace,monospace';

  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function sstep(a, b, x) { var t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }
  function avg(a) { var v = a.filter(function (x) { return x != null && !isNaN(x); }); return v.length ? v.reduce(function (s, x) { return s + x; }, 0) / v.length : null; }

  // ---- 選手ごとの性能
  function prepare(entries) {
    var boats = entries.map(function (e) {
      return { waku: e.waku, course: e.course || e.waku, name: e.name || (e.waku + "号艇"),
               st: e.st == null ? 0.16 : clamp(e.st, 0.05, 0.3), motor2: e.motor2, ex: e.ex, cls: e.cls,
               km: e.km || {}, ls: e.ls || {}, n: e.n || 0, w1: e.w1 || 0 };   // このコースでの勝ち方・負け方・走数・1着数
    }).sort(function (a, b) { return a.course - b.course; });
    var am = avg(boats.map(function (b) { return b.motor2; })), ae = avg(boats.map(function (b) { return b.ex; }));
    boats.forEach(function (b) {
      var dash = b.course >= 4;                  // 4〜6コースはダッシュ、1〜3コースはスロー
      b.vline = dash ? 21.6 : 18.0;              // スタートラインを越えるときの速さ(m/秒)
      b.apre = dash ? 1.3 : 2.6;                 // スタート前の加速
      var vm = 22.0;                             // 直線の最高速(モーターと展示タイムで上下)
      if (b.motor2 != null && am != null) vm += 0.045 * (b.motor2 - am);
      if (b.ex != null && ae != null) vm += 0.35 * (ae - b.ex) / 0.05;
      b.vmax0 = clamp(vm, 20.8, 23.4);
      b.alat0 = 17 * ({ A1: 1.06, A2: 1.03, B1: 1.0, B2: 0.96 }[b.cls] || 1);     // 旋回の上手さ(横向きの加速度)
      b.lane = LANE0 + LANE_W * (b.course - 1);
    });
    return boats;
  }

  // ---- スタート後の直線を、よけ合いなしで走らせたときの位置と速さ(行き方を決めるのに使う)
  function straightRun(b, t) {
    if (t < b.st) { var r = b.st - t; return { x: -(b.vline * r - b.apre * r * r / 2), v: b.vline - b.apre * r }; }
    var x = 0, v = b.vline, vmax = b.vmax0 + b.bias.vmax;
    for (var s = b.st; s < t; s += DT) { v = Math.min(vmax, v + (0.95 * (vmax - v) + 0.6) * DT); x += v * DT; }
    return { x: x, v: v };
  }

  // ---- 行き方を決める。勝つ艇は決着パターンどおり。ほかの艇は、スタートして少し走った時点で
  //      内の艇より前に出ているか(平均STとモーターの伸びの結果)を見て、絞る・捲る・捲り差し・差しを選ぶ
  function assignRoles(boats, sc, vkim) {
    var cw = sc.course, k = sc.kim, byC = {};
    boats.forEach(function (b) {
      byC[b.course] = b;
      b.bias = { vmax: 0, alat: 1 };
      b.flow = 0;                                // 1マークで外に流れる量
      b.squeeze = 0;                             // 直線で内に絞る量
      b.hari = 0;                                // 1コースが外へ張る量
      b.delExtra = 0;
      b.slow = [];                               // 他艇とぶつからないよう、手前から速度を抑える区間
      b.win = b.course === cw;
      b.role = null; b.note = null;
    });
    var w = byC[cw], b1 = byC[1];
    if (w) {
      w.role = cw === 1 ? "nige" : ({ "差し": "sashi", "捲り": "makuri", "捲り差し": "makurizashi" }[k] || "sashi");
      if (w.role === "nige") { w.bias.alat = 1.04; w.bias.vmax = 0.15; }
      if (w.role === "sashi") w.bias.alat = 1.08;
      if (w.role === "makuri") w.bias.vmax = 0.6;
      if (w.role === "makurizashi") w.bias.alat = 1.06;
    }
    // 先頭が45m進んだ時点の並び(平均STとモーターの伸びの結果)
    var tDec = 0;
    while (tDec < 6 && !boats.some(function (b) { return straightRun(b, tDec).x >= 45; })) tDec += 0.05;
    boats.forEach(function (b) { var r = straightRun(b, tDec); b.xDec = r.x; b.vDec = r.v; });
    function lead(b) { var i = byC[b.course - 1]; return i ? b.xDec - i.xDec : 0; }
    function tend(c) { return vkim && vkim[c - 1] ? vkim[c - 1] : [0, 1, 1, 1, 0, 0]; }
    // 選手の戦法の傾向: このコースで勝ったときの決まり手(捲り・捲り差し・差し)を、場の傾向で補って割合にする
    boats.forEach(function (b) {
      var t = tend(b.course), prior = { "捲り": t[1], "捲り差し": t[3], "差し": t[2] }, ps = (t[1] + t[2] + t[3]) || 1, tot = 0, W0 = 3;
      ["捲り", "捲り差し", "差し"].forEach(function (k) { tot += b.km[k] || 0; });
      b.tac = { n: tot };
      ["捲り", "捲り差し", "差し"].forEach(function (k) { b.tac[k] = ((b.km[k] || 0) + W0 * prior[k] / ps) / (tot + W0); });
    });
    // 捲り型の選手ほど、少し前に出ただけでも仕掛ける(カドはダッシュの分、前に出やすい)
    function thrOf(b) { return (b.course === 4 ? 4.2 : 1.8) - 2.0 * (b.tac["捲り"] - 0.3); }
    // 仕掛けやすさ: 内の艇より前に出ている分と、まだ伸びている分(カドはダッシュで速い分を差し引く)
    function score(b) { var i = byC[b.course - 1]; return lead(b) - thrOf(b) + (i ? (b.vDec - i.vDec - (b.course === 4 ? 0.6 : 0)) * 1.2 : 0); }
    // 捲れないときの狙い方: 選手の傾向で、捲り差しか差しか(5・6コースは外を回すことも)
    function fallback(b) {
      var c = b.course, tc = b.tac;
      if (c >= 5 && tc["差し"] < 0.45 && tc["捲り差し"] < 0.45) return "soto";
      if (c === 6 && tc["差し"] < 0.5) return "soto";
      return tc["差し"] > tc["捲り差し"] ? "sashi" : "makurizashi";
    }

    // 1) 捲りに行く艇(展開を作る艇)
    var attacker = null;
    if (w && w.role === "makuri") attacker = w;
    else {
      var cands = boats.filter(function (b) { return !b.win && b.course >= 2 && b.course <= 5; });
      if (k === "差し" || k === "捲り差し") {
        // 差し・捲り差しが決まるのは、内か外で誰かが仕掛けて1コースが外へ持っていかれたとき
        cands = cands.filter(function (b) { return cw === 2 ? (b.course === 3 || b.course === 4) : b.course < cw; });
        cands.sort(function (a, b) { return score(b) - score(a); });
        if (cands[0] && score(cands[0]) > -1.5) attacker = cands[0];
      } else {
        cands.sort(function (a, b) { return score(b) - score(a); });
        if (cands[0] && score(cands[0]) >= 0) attacker = cands[0];   // 本当に前に出ている艇だけが捲りに行く
      }
      if (attacker) attacker.role = "makuri";
    }
    var A = attacker ? attacker.course : 99;

    // 2) 1コースの判断: 捲りに来た艇に張って対抗するか、小回りで着を残しに行くか
    var avgV = avg(boats.map(function (b) { return b.vmax0; }));
    if (b1 && !b1.win) {
      if (attacker) {
        var strong = ({ A1: 1, A2: 0.6, B1: 0.3, B2: 0 }[b1.cls] || 0.3) + (b1.vmax0 - avgV) * 0.6;
        if (b1.n >= 5) strong += (b1.w1 / b1.n - 0.55) * 2;               // 1コースでよく逃げている選手は対抗する
        var resist = k === "差し" || k === "捲り差し" || (strong >= 0.6 && attacker.xDec - b1.xDec < 3.5);
        if (resist) { b1.role = "nige"; b1.hari = 3.5; b1.flow = 9; b1.bias.alat = 0.92; b1.note = "張る"; }
        else { b1.role = "nokoshi"; b1.bias.alat = 0.97; b1.note = "残す"; }
      } else {
        b1.role = "nige";
        if (k === "差し") { b1.flow = 10; b1.bias.alat = 0.9; b1.note = "流れる"; }
        else if (k === "捲り差し") { b1.flow = 6; b1.bias.alat = 0.95; b1.note = "流れる"; }
      }
    } else if (b1 && b1.win && attacker && attacker.xDec - b1.xDec > -3) {
      b1.hari = 2.0; b1.note = "張る";                                  // 張って先に回る
    }

    // 3) ほかの艇は、仕掛けた艇との位置関係で動く
    boats.forEach(function (b) {
      if (b.role) return;
      var c = b.course, inner = byC[c - 1];
      if (c < A) { b.role = "sashi"; b.flow = 4; b.bias.alat = 0.96; return; }        // 捲られる側(引き波で沈むかは走らせて決まる)
      if (c === A + 1) {
        // 捲った艇のすぐ外: 並んでいて捲り型なら捲りについて行く、そうでなければ空いた内を差し型は差し、ほかは捲り差しで狙う
        if (b.xDec - attacker.xDec >= -2.5 && b.vDec >= attacker.vDec - 0.3 && b.tac["差し"] < 0.5) { b.role = "mark"; return; }
        b.role = b.tac["差し"] > b.tac["捲り差し"] ? "sashi" : "makurizashi";
        return;
      }
      if (c > A + 1) { b.role = fallback(b); return; }
      if (c === 2) { b.role = "sashi"; return; }                                         // 仕掛けがなければ2コースは差し構え
      if (c <= 5 && lead(inner) <= -1.2 && b.tac["差し"] < 0.6) { b.role = "makurizashi"; return; }   // 内の艇が凹んでいる
      b.role = fallback(b);
    });

    // 4) スタートが良い艇は内に絞る(捲りに行く艇は大きく)
    boats.forEach(function (b) {
      var c = b.course;
      if (c === 1) return;
      if (b.role === "makuri") b.squeeze = 3.3;
      else if (b.role === "mark") b.squeeze = 1.5;
      else if (lead(b) >= thrOf(b) * 0.6 && c > A) b.squeeze = 2.0;
    });
  }

  // ---- 走るライン。1マークに入る横位置(ye)は内外の順番を崩さず、出る横位置(yx)は回り方で決める
  //      (差しは内、捲り差しはその外、逃げは小回り、捲りと外を回す艇は外)
  function computeLines(boats) {
    var prev = null;
    boats.slice().sort(function (a, b) { return a.course - b.course; }).forEach(function (b) {
      var L = b.lane;
      b.ysq = L - b.squeeze;
      var pref = { nige: Math.min(L, 6.5) + b.hari, nokoshi: Math.min(L, 6.5), sashi: L - 4, makurizashi: L - 2,
                   makuri: L - 3.3, mark: L - 2.5, soto: L - 3 }[b.role];
      b.ye = prev == null ? pref : Math.max(prev + 4.0, pref);
      prev = b.ye;
      b.pref = { nige: 0, nokoshi: 0.2, sashi: 0.5, makurizashi: 1.5, makuri: 3, mark: 3.4, soto: 4 }[b.role] + 0.1 * b.course + b.flow / 3 + b.hari / 3;
    });
    // 1マークを回る順(内から): 出口の横位置と、ブイの外へ振る量を、内から一定の間隔で割り振る(同心円の重なりを作らない)
    boats.slice().sort(function (a, b) { return a.pref - b.pref; }).forEach(function (b, r) { b.yx = -12 - 4.0 * r; b.rank = r; });
    boats.forEach(function (b) {
      var c = b.course;
      var base = { nige: 3.5 + b.hari * 0.5, nokoshi: 3.0, sashi: 2 + 0.5 * (c - 2), makurizashi: 6 + (c - 3), makuri: 6 + 1.5 * (c - 2),
                   mark: 8 + 1.5 * (c - 2), soto: 12 + 2 * Math.max(0, c - 6) }[b.role] + b.flow * 0.4;
      b.del = Math.max(base, 3.5 + 3.0 * b.rank) + b.delExtra;
      b.asym = (b.role === "makurizashi" ? 2 : b.role === "sashi" ? 0.5 : 0) - b.flow / 4;   // 大きく入って小さく出る(切り込む)/流れる
      var xw = { nige: b.hari ? [72, 118] : [60, 115], nokoshi: [60, 115], sashi: [70, 120], makurizashi: [60, 115], makuri: [70, 112],
                 mark: [65, 112], soto: [70, 120] }[b.role];
      b.xa = xw[0]; b.xb = xw[1];
    });
  }

  function makePath(b, del) {
    var pts = [], half = (b.ye - b.yx) / 2, r1 = half + b.asym, cyc = b.ye - r1, r2 = cyc - b.yx;
    var cx = D + del - (r1 + r2) / 2, i, q, phi, r;
    var xb = Math.min(b.xb, cx - 4), xa = Math.min(b.xa, xb - 10);
    for (var x = 0; x < cx; x += 0.5) {
      pts.push([x, b.lane + (b.ysq - b.lane) * sstep(12, 55, x) + (b.ye - b.ysq) * sstep(xa, xb, x)]);
    }
    var iStart = pts.length;
    for (i = 0; i <= 160; i++) {
      q = i / 160; phi = Math.PI / 2 - Math.PI * q; r = r1 + (r2 - r1) * sstep(0, 1, q);
      pts.push([cx + r * Math.cos(phi), cyc + r * Math.sin(phi)]);
    }
    var iEnd = pts.length - 1, ex = pts[iEnd];
    for (var d = 0.5; d <= 220; d += 0.5) pts.push([ex[0] - d, ex[1] + 3 * sstep(0, 45, d)]);
    // つなぎ目の折れをなくす(前後の点でならす)
    var n = pts.length, sm = new Array(n);
    for (i = 0; i < n; i++) {
      if (i < 8) { sm[i] = pts[i]; continue; }
      var sx = 0, sy = 0, m = 0;
      for (var u = i - 7; u <= i + 7; u++) { if (u < 0 || u >= n) continue; sx += pts[u][0]; sy += pts[u][1]; m++; }
      sm[i] = [sx / m, sy / m];
    }
    var s = [0], k = [0], minB = 1e9;
    for (i = 1; i < n; i++) s.push(s[i - 1] + Math.hypot(sm[i][0] - sm[i - 1][0], sm[i][1] - sm[i - 1][1]));
    for (i = 1; i < n - 1; i++) {
      var a1 = Math.atan2(sm[i][1] - sm[i - 1][1], sm[i][0] - sm[i - 1][0]);
      var a2 = Math.atan2(sm[i + 1][1] - sm[i][1], sm[i + 1][0] - sm[i][0]);
      var da = Math.abs(Math.atan2(Math.sin(a2 - a1), Math.cos(a2 - a1)));
      k.push(da / ((s[i + 1] - s[i - 1]) / 2 || 1));
    }
    k.push(0);
    for (i = 0; i < n; i++) minB = Math.min(minB, Math.hypot(sm[i][0] - BUOY.x, sm[i][1] - BUOY.y));
    var ks = k.map(function (_, j) { var sum = 0, c = 0; for (var u = Math.max(0, j - 6); u <= Math.min(n - 1, j + 6); u++) { sum += k[u]; c++; } return sum / c; });
    return { pts: sm, s: s, k: ks, sStart: s[iStart], sEnd: s[iEnd], minB: minB };
  }

  // ブイから必ず CLEAR + 余裕 を空けるまで、外への振り出しを広げる
  function buildPath(b) {
    var del = b.del, P = null;
    for (var tries = 0; tries < 40; tries++) {
      P = makePath(b, del);
      if (P.minB >= CLEAR + 0.5) break;
      del += 0.4;
    }
    return P;
  }

  // 道のり s の地点の位置と向き
  function pathAt(P, sv) {
    var s = P.s, lo = 0, hi = s.length - 1;
    if (sv <= 0) return { x: P.pts[0][0], y: P.pts[0][1], h: 0 };
    if (sv >= s[hi]) { var a = P.pts[hi - 1], z = P.pts[hi]; return { x: z[0], y: z[1], h: Math.atan2(z[1] - a[1], z[0] - a[0]) }; }
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (s[mid] <= sv) lo = mid; else hi = mid; }
    var f = (sv - s[lo]) / (s[hi] - s[lo] || 1), p = P.pts[lo], n = P.pts[hi];
    return { x: p[0] + (n[0] - p[0]) * f, y: p[1] + (n[1] - p[1]) * f, h: Math.atan2(n[1] - p[1], n[0] - p[0]) };
  }

  // ---- 時間を進めて全艇を走らせる
  function simulate(boats) {
    var N = Math.round((T_MAX - T0) / DT) + 1;
    computeLines(boats);
    boats.forEach(function (b) {
      b.vmax = b.vmax0 + b.bias.vmax;
      b.alat = b.alat0 * b.bias.alat;
      b.P = buildPath(b);
      var P = b.P, n = P.s.length, vl = new Array(n);
      for (var i = 0; i < n; i++) vl[i] = Math.min(b.vmax, Math.sqrt(b.alat / Math.max(P.k[i], 1e-4)));
      for (i = n - 2; i >= 0; i--) vl[i] = Math.min(vl[i], Math.sqrt(vl[i + 1] * vl[i + 1] + 2 * 6.5 * (P.s[i + 1] - P.s[i])));
      b.vl = vl;
      b.X = new Float32Array(N); b.Y = new Float32Array(N); b.H = new Float32Array(N); b.V = new Float32Array(N); b.S = new Float32Array(N);
      b.sv = 0; b.v = b.vline; b.off = 0; b.offV = 0; b.done = null; b.acc = null; b.wakeLoss = 0; b.sinkI = null;
    });
    function vlimAt(b, sv) {
      var s = b.P.s, lo = 0, hi = s.length - 1, f = 1;
      b.slow.forEach(function (z) { var w = sstep(z.s0 - 12, z.s0, sv) * (1 - sstep(z.s1, z.s1 + 12, sv)); f *= 1 - (1 - z.f) * w; });
      if (sv >= s[hi]) return b.vl[hi] * f;
      while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (s[mid] <= sv) lo = mid; else hi = mid; }
      return b.vl[lo] * f;
    }
    for (var i = 0; i < N; i++) {
      var t = T0 + i * DT;
      // 1) 前のコマの位置関係から、加速と横の動きを決める
      boats.forEach(function (b) {
        if (t < b.st || i === 0) return;
        var hb = b.H[i - 1], cs = Math.cos(hb), sn = Math.sin(hb), lead = null, gap = 1e9, latF = 0;
        boats.forEach(function (a) {
          if (a === b) return;
          var dx = a.X[i - 1] - b.X[i - 1], dy = a.Y[i - 1] - b.Y[i - 1];
          var fwd = dx * cs + dy * sn, lat = -dx * sn + dy * cs;     // lat>0: 相手が右(外)側
          if (fwd > 0 && fwd < 30 && Math.abs(lat) < HULL_W + 1.4) {
            var g = fwd - HULL_L - 0.3;
            if (g < gap) { gap = g; lead = a; }
          }
          if (Math.abs(fwd) < HULL_L + 1.5 && Math.abs(lat) < 3.6) {
            var m = 3.6 - Math.abs(lat);
            latF += -(lat >= 0 ? 1 : -1) * (m * m * 3.2 + (Math.abs(lat) < 2.3 ? (2.3 - Math.abs(lat)) * 30 : 0));
          }
        });
        var bx = b.X[i - 1] - BUOY.x, by = b.Y[i - 1] - BUOY.y, bd = Math.hypot(bx, by);
        if (bd < CLEAR + 1.0) latF += ((bx * -sn + by * cs) >= 0 ? 1 : -1) * (CLEAR + 1.0 - bd) * 24;   // ブイからは離れる
        // 引き波: 少し前に他艇が通った跡を横切ると失速する(真後ろを追うときは少しだけ)
        var wake = 0;
        boats.forEach(function (a) {
          if (a === b) return;
          for (var lag = 15; lag <= 90; lag += 15) {
            var j = i - 1 - lag;
            if (j < 0 || T0 + j * DT < a.st) break;
            var wx = b.X[i - 1] - a.X[j], wy = b.Y[i - 1] - a.Y[j];
            if (wx * wx + wy * wy < 6.8) {
              var ang = Math.abs(Math.atan2(Math.sin(hb - a.H[j]), Math.cos(hb - a.H[j])));
              wake += (ang > 0.35 ? 1 : 0.25) * (1 - lag / 110);
            }
          }
        });
        var aWake = wake > 0 ? -Math.min(6, 3.5 * wake) : 0;
        if (wake > 0) latF += Math.sin(t * 23 + b.course * 1.7) * 1.6 * Math.min(1, wake);   // 波で少し揺れる
        // 前に艇がいれば間合いを取る(車間をとる考え方: 近く・速く迫るほど強く減速)
        var v0 = vlimAt(b, b.sv + b.v * 0.3);
        var aFree = b.v < v0 ? Math.min(0.95 * (b.vmax - b.v) + 0.6, (v0 - b.v) * 2.5) : -Math.min(8, (b.v - v0) * 3);
        var aInt = 0;
        if (lead) {
          var dv = b.v - lead.V[i - 1], sStar = 1.2 + b.v * 0.22 + b.v * dv / (2 * Math.sqrt(18));
          aInt = -3 * Math.pow(Math.max(0, sStar) / Math.max(0.2, gap), 2);
        }
        b.acc = clamp(aFree + aInt + aWake, -12, 4.5);
        b.latF = latF;
        if (aWake < 0 && b.v > 6) {
          b.wakeLoss += -aWake * DT;
          if (b.sinkI == null && b.wakeLoss >= 1.6) b.sinkI = i;
        }
      });
      // 2) 動かす
      boats.forEach(function (b) {
        var x, y, h, v;
        if (t < b.st) {                                          // スタート前: 平均STでラインを越えるように助走
          var r = b.st - t;
          x = -(b.vline * r - b.apre * r * r / 2); y = b.lane; h = 0; v = b.vline - b.apre * r;
        } else {
          if (b.acc != null) {
            b.v = Math.max(5, b.v + b.acc * DT);
            var lim = Math.min(3, 0.16 * b.v);                  // 横の動きは前に進む速さの一部まで(低速でくるくる回らない)
            b.offV = clamp(b.offV + (b.latF - b.off * 2.0 - b.offV * 3.0) * DT, -lim, lim);
            b.off = clamp(b.off + b.offV * DT, -6, 6);
          }
          b.sv += b.v * DT;
          var p = pathAt(b.P, b.sv);
          x = p.x - Math.sin(p.h) * b.off; y = p.y + Math.cos(p.h) * b.off; h = p.h; v = b.v;
          if (b.done == null && b.sv >= b.P.sEnd) b.done = t;
        }
        b.X[i] = x; b.Y[i] = y; b.H[i] = h; b.V[i] = v; b.S[i] = b.sv;
      });
    }
    boats.forEach(function (b) { if (b.done == null) b.done = T_MAX; smoothTrack(b, N); });
    var tEnd = Math.min(T_MAX - 0.1, Math.max.apply(null, boats.map(function (b) { return b.done; })) + 2.0);
    return { N: N, tEnd: tEnd };
  }

  // 軌跡をならして(約0.1秒の幅)、向きは実際の進み方から出す
  function smoothTrack(b, N) {
    var X = b.X, Y = b.Y, sx = new Float32Array(N), sy = new Float32Array(N), K = [], R = 9, sig = 4, i, j, w, sum;
    for (j = -R; j <= R; j++) K.push(Math.exp(-j * j / (2 * sig * sig)));
    for (i = 0; i < N; i++) {
      var ax = 0, ay = 0; sum = 0;
      for (j = -R; j <= R; j++) { var u = clamp(i + j, 0, N - 1); w = K[j + R]; ax += X[u] * w; ay += Y[u] * w; sum += w; }
      sx[i] = ax / sum; sy[i] = ay / sum;
    }
    var H = new Float32Array(N), prev = 0;
    for (i = 0; i < N; i++) {
      var a = Math.max(0, i - 2), c = Math.min(N - 1, i + 2), dx = sx[c] - sx[a], dy = sy[c] - sy[a];
      var hh = dx * dx + dy * dy > 1e-6 ? Math.atan2(dy, dx) : prev;
      hh = prev + Math.atan2(Math.sin(hh - prev), Math.cos(hh - prev));   // 角度の折り返しをなくす
      H[i] = hh; prev = hh;
    }
    b.X = sx; b.Y = sy; b.H = H;
  }

  function leaderAt(boats, i) {
    var best = null;
    boats.forEach(function (b) { if (b.done <= T0 + i * DT && (!best || b.X[i] < best.X[i])) best = b; });
    return best;
  }

  function idxAtS(b, sv) { for (var i = 0; i < b.S.length; i++) if (T0 + i * DT >= b.st && b.S[i] >= sv) return i; return null; }

  // ---- 展開の重要ポイント(吹き出し)。多くても3つ、時間が重ならないように選ぶ
  function events(boats) {
    var ev = [];
    function add(b, i, text, pr) { if (i != null) ev.push({ i: i, b: b, text: text, pr: pr }); }
    boats.forEach(function (b) {
      var c = b.course, turn = b.P.sEnd - b.P.sStart;
      if (b.squeeze >= 2) add(b, idxAtS(b, 30), c + "コース 絞る", b.win || b.role === "makuri" ? 2 : 3.5);
      if (b.role === "makuri" && !b.win) add(b, idxAtS(b, b.P.sStart - 34), c + "コース 捲りに行く", 2.2);
      if (b.win) {
        var txt = { nige: "逃げる", sashi: "差す", makuri: "捲る", makurizashi: "まくり差し" }[b.role];
        add(b, idxAtS(b, b.P.sStart + turn * (b.role === "makuri" ? 0.25 : 0.55)), c + "コース " + txt, 1);
      }
      if (c === 1 && b.note === "張る") add(b, idxAtS(b, b.P.sStart - 10), "1コース 張る", b.win ? 3.2 : 2.4);
      if (c === 1 && b.note === "残す") add(b, idxAtS(b, b.P.sStart + turn * 0.35), "1コース 残しに行く", 2.4);
      if (c === 1 && b.note === "流れる") add(b, idxAtS(b, b.P.sStart + turn * 0.8), "1コース 流れる", 3.4);
      if (!b.win && b.sinkI != null) add(b, b.sinkI, c + "コース 沈む", c === 1 ? 2.8 : 3.6);
      if (b.role === "mark") add(b, idxAtS(b, b.P.sStart + turn * 0.3), c + "コース 捲りについて行く", 3.0);
      var inA = boats.filter(function (o) { return o.course === c - 1 && o.role === "makuri"; })[0];
      if (inA && !b.win && b.role === "makurizashi") add(b, idxAtS(b, b.P.sStart + turn * 0.5), c + "コース まくり差し", 2.6);   // 捲った艇の隙を狙う
      if (inA && !b.win && b.role === "sashi") add(b, idxAtS(b, b.P.sStart + turn * 0.5), c + "コース 差し", 2.8);
    });
    ev.sort(function (a, b) { return a.pr - b.pr; });
    var out = [];
    ev.forEach(function (e) {
      if (out.length >= 4) return;
      if (out.every(function (o) { return Math.abs(o.i - e.i) * DT > 0.55 && o.b !== e.b || Math.abs(o.i - e.i) * DT > 1.8; })) out.push(e);
    });
    out.forEach(function (e) { e.t = T0 + e.i * DT; });
    out.sort(function (a, b) { return a.t - b.t; });
    out.forEach(function (e, k) { e.below = k % 2 === 1; });    // 続けて出る吹き出しは上下に分けて重ならないようにする
    return out;
  }

  // 艇どうしが重なる最初の場面を、組ごとに探す
  function conflicts(boats, iEnd) {
    var out = [];
    for (var a = 0; a < boats.length; a++) for (var c = a + 1; c < boats.length; c++) {
      var A = boats[a], B = boats[c], i0 = Math.round((Math.max(A.st, B.st) - T0) / DT);
      for (var i = i0; i <= iEnd; i++) {
        var dx = A.X[i] - B.X[i], dy = A.Y[i] - B.Y[i];
        if (dx * dx + dy * dy > 36) continue;
        var hb = B.H[i], fwd = dx * Math.cos(hb) + dy * Math.sin(hb), lat = -dx * Math.sin(hb) + dy * Math.cos(hb);
        if (Math.abs(fwd) < HULL_L + 0.5 && Math.abs(lat) < HULL_W + 0.5) { out.push({ A: A, B: B, i: i, fwd: fwd, lat: lat }); break; }
      }
    }
    return out;
  }

  // ---- 決着パターンどおりの先頭になり、どの艇もブイに近づかず、艇どうしも重ならないよう、調整しながら走らせ直す
  function plan(entries, sc, vkim) {
    var boats = prepare(entries);
    assignRoles(boats, sc, vkim);
    var winner = boats.filter(function (b) { return b.win; })[0] || boats[0], R;
    for (var it = 0; it < 26; it++) {
      R = simulate(boats);
      var iEnd = Math.round((R.tEnd - T0) / DT), lead = leaderAt(boats, iEnd), again = false;
      boats.forEach(function (b) {
        var md = 1e9;
        for (var i = 0; i <= iEnd; i += 2) md = Math.min(md, Math.hypot(b.X[i] - BUOY.x, b.Y[i] - BUOY.y));
        if (md < CLEAR - 0.1) { b.delExtra += CLEAR - md + 0.4; again = true; }
      });
      if (lead && lead !== winner) { winner.bias.alat *= 1.05; winner.bias.vmax += 0.25; lead.bias.alat *= 0.97; again = true; }
      if (!again && it < 25) {
        conflicts(boats, iEnd).forEach(function (cf) {
          var A = cf.A, B = cf.B, hd = Math.abs(Math.atan2(Math.sin(A.H[cf.i] - B.H[cf.i]), Math.cos(A.H[cf.i] - B.H[cf.i])));
          if (hd < 0.35 && Math.abs(cf.fwd) < 2.6) {              // 並走: 外の艇が、直線なら絞りを弱め、旋回ならもう少し外を回る
            var outer = cf.lat > 0 ? A : B, inner = outer === A ? B : A;
            if (!outer.win) {
              if (outer.X[cf.i] < D - 30 && outer.squeeze > 0) outer.squeeze = Math.max(0, outer.squeeze - 1);
              else outer.delExtra += 1.2;
            } else inner.slow.push({ s0: inner.S[cf.i] - 45, s1: inner.S[cf.i] + 4, f: 0.88 });   // 外の勝つ艇を先に行かせる
          } else {                                                // 追いつく・交差する: 後ろの艇が手前から速度を抑える
            var behind = cf.fwd > 0 ? B : A, ahead = behind === A ? B : A;
            if (!behind.win) behind.slow.push({ s0: behind.S[cf.i] - 45, s1: behind.S[cf.i] + 4, f: 0.9 });
            else { ahead.delExtra += 1.0; ahead.slow.push({ s0: ahead.S[cf.i] - 30, s1: ahead.S[cf.i] + 4, f: 0.95 }); }   // 前の艇が外へよけて勝つ艇を通す
          }
          again = true;
        });
      }
      if (!again) break;
    }
    return { boats: boats, winner: winner, sc: sc, tEnd: R.tEnd, total: R.tEnd - T0, cam: camera(boats, R), N: R.N, events: events(boats) };
  }

  // ---- カメラ: ドローンが全艇を追うように、位置と画角をなめらかに変える
  function camera(boats, R) {
    var n = Math.round((R.tEnd + 1.6 - T0) / DT), CX = [], CY = [], CW = [];
    for (var i = 0; i < n; i++) {
      var t = T0 + i * DT, j = Math.min(i, R.N - 1);
      var xs = boats.map(function (b) { return b.X[j]; }), ys = boats.map(function (b) { return b.Y[j]; });
      if (t < 1.0) { xs.push(4); ys.push(4, 40); xs.push(4); }
      if (Math.max.apply(null, xs) > D - 45) { xs.push(D + 6); ys.push(0); }
      var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
      CX.push((x0 + x1) / 2 + 3); CY.push((y0 + y1) / 2);
      CW.push(clamp(Math.max(x1 - x0 + 28, (y1 - y0 + 18) * 1.6), 62, 150));
    }
    function sm(a, tau) {                                         // 前後からならして、揺れを抑える
      var k = DT / tau, o = a.slice(), i;
      for (i = 1; i < o.length; i++) o[i] = o[i - 1] + (o[i] - o[i - 1]) * k;
      for (i = o.length - 2; i >= 0; i--) o[i] = o[i + 1] + (o[i] - o[i + 1]) * k;
      return o;
    }
    return { x: sm(CX, 0.5), y: sm(CY, 0.5), w: sm(CW, 0.7), n: n };
  }

  // さざ波(固定の乱数で毎回同じ模様)
  var WAVES = (function () {
    var s = 11, out = [];
    function rnd() { s = (s * 16807) % 2147483647; return s / 2147483647; }
    for (var i = 0; i < 560; i++) out.push([rnd() * 520 - 140, rnd() * 160 - 80, 1.2 + rnd() * 3, rnd() * 6.28]);
    return out;
  })();

  function hull(ctx) {
    var l = HULL_L, w = HULL_W;
    ctx.beginPath();
    ctx.moveTo(l * 0.5, 0);
    ctx.quadraticCurveTo(l * 0.3, -w * 0.5, l * 0.02, -w * 0.5);
    ctx.lineTo(-l * 0.5, -w * 0.42);
    ctx.lineTo(-l * 0.5, w * 0.42);
    ctx.lineTo(l * 0.02, w * 0.5);
    ctx.quadraticCurveTo(l * 0.3, w * 0.5, l * 0.5, 0);
    ctx.closePath();
  }

  function sample(b, t) {
    var f = (t - T0) / DT, i = Math.floor(f), u = f - i, n = b.X.length;
    if (i < 0) { i = 0; u = 0; }
    if (i >= n - 1) { i = n - 2; u = 1; }
    var h = b.H[i] + (b.H[i + 1] - b.H[i]) * u;
    return { x: b.X[i] + (b.X[i + 1] - b.X[i]) * u, y: b.Y[i] + (b.Y[i + 1] - b.Y[i]) * u, h: h, w: (b.H[i + 1] - b.H[i]) / DT, v: b.V[i] };
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h - r); ctx.arcTo(x + w, y + h, x + w - r, y + h, r); ctx.lineTo(x + r, y + h);
    ctx.arcTo(x, y + h, x, y + h - r, r); ctx.lineTo(x, y + r); ctx.arcTo(x, y, x + r, y, r); ctx.closePath();
  }

  // 吹き出し(艇の上に出して、艇についていく)
  function bubble(ctx, text, b, sx, sy, cw, ch, u, alpha, wantBelow, others, rBoat, memo) {
    var fs = Math.max(11, u * 2.4), col = COLORS[b.waku] || COLORS[1];
    ctx.font = "700 " + fs + "px " + FONT;
    var tw = ctx.measureText(text).width, chip = fs * 1.3, pad = fs * 0.45;
    var w = pad + chip + fs * 0.45 + tw + fs * 0.7, h = fs * 2.0, gap = fs * 1.4;
    // 置き場所の候補(上・下、それぞれ中央・右寄り・左寄り)から、ほかの艇にかぶらず画面に収まる所を選ぶ
    var cands = [], order = wantBelow ? [true, false] : [false, true];
    [0, 0.42, -0.42].forEach(function (sh) { order.forEach(function (bl) { cands.push([bl, sh]); }); });
    var pick = null;
    function at(k) { var bl = cands[k][0]; return [bl, clamp(sx - w / 2 + cands[k][1] * w, u, cw - w - u), bl ? sy + gap : sy - h - gap]; }
    function fits(p) { return p[2] >= u * 11 && p[2] + h <= ch - u * 7; }
    if (memo.k != null && fits(at(memo.k))) pick = at(memo.k);      // 一度決めた置き場所は、出ている間は変えない(ちらつかない)
    for (var k = 0; k < cands.length && !pick; k++) {
      var p = at(k);
      if (!fits(p)) continue;
      var hit = others.some(function (o) { return o[0] + rBoat > p[1] && o[0] - rBoat < p[1] + w && o[1] + rBoat > p[2] && o[1] - rBoat < p[2] + h; });
      if (!hit) { pick = p; memo.k = k; }
    }
    if (!pick) { var bl0 = !(sy - h - gap >= u * 11); pick = [bl0, clamp(sx - w / 2, u, cw - w - u), bl0 ? sy + gap : sy - h - gap]; }
    var below = pick[0], bx = pick[1], by = pick[2];
    var tx = clamp(sx, bx + h * 0.6, bx + w - h * 0.6);
    ctx.globalAlpha = alpha;
    ctx.fillStyle = "rgba(255,255,255,0.96)";
    ctx.beginPath();
    if (below) { ctx.moveTo(tx - fs * 0.45, by + 1); ctx.lineTo(sx, sy + fs * 0.7); ctx.lineTo(tx + fs * 0.45, by + 1); }
    else { ctx.moveTo(tx - fs * 0.45, by + h - 1); ctx.lineTo(sx, sy - fs * 0.7); ctx.lineTo(tx + fs * 0.45, by + h - 1); }
    ctx.closePath(); ctx.fill();
    roundRect(ctx, bx, by, w, h, h / 2); ctx.fill();
    var ccx = bx + pad + chip / 2, ccy = by + h / 2;
    ctx.beginPath(); ctx.arc(ccx, ccy, chip / 2, 0, Math.PI * 2); ctx.fillStyle = col[0]; ctx.fill();
    if (b.waku === 1) { ctx.lineWidth = 1; ctx.strokeStyle = "#8a99a3"; ctx.stroke(); }
    ctx.fillStyle = col[1]; ctx.font = "700 " + (fs * 0.85) + "px " + MONO; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(String(b.waku), ccx, ccy + 0.5);
    ctx.fillStyle = "#14212b"; ctx.font = "700 " + fs + "px " + FONT; ctx.textAlign = "left";
    ctx.fillText(text, bx + pad + chip + fs * 0.45, ccy + 0.5);
    ctx.globalAlpha = 1;
  }

  function draw(ctx, cw, ch, P, t, opt) {
    var ci = clamp(Math.round((t - T0) / DT), 0, P.cam.n - 1);
    var camX = P.cam.x[ci], camY = P.cam.y[ci], vw = P.cam.w[ci], sc = cw / vw;
    var tt = Math.min(t, P.tEnd + 1.2);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    var g = ctx.createLinearGradient(0, 0, 0, ch);
    g.addColorStop(0, "#0d566f"); g.addColorStop(1, "#0a465c");
    ctx.fillStyle = g; ctx.fillRect(0, 0, cw, ch);
    ctx.setTransform(sc, 0, 0, sc, cw / 2 - camX * sc, ch / 2 - camY * sc);
    // さざ波
    ctx.lineCap = "round"; ctx.strokeStyle = "rgba(255,255,255,0.09)"; ctx.lineWidth = 0.18;
    var vx0 = camX - vw / 2 - 5, vx1 = camX + vw / 2 + 5, vy0 = camY - vw * 0.35, vy1 = camY + vw * 0.35;
    WAVES.forEach(function (w) {
      if (w[0] < vx0 || w[0] > vx1 || w[1] < vy0 || w[1] > vy1) return;
      var dx = Math.sin(t * 0.7 + w[3]) * 0.6;
      ctx.beginPath(); ctx.moveTo(w[0] + dx, w[1]); ctx.quadraticCurveTo(w[0] + dx + w[2] / 2, w[1] - 0.4, w[0] + dx + w[2], w[1]); ctx.stroke();
    });
    // スタンド側の岸
    ctx.fillStyle = "#8fa2aa"; ctx.fillRect(-300, 52, 800, 60);
    ctx.fillStyle = "#73878f"; ctx.fillRect(-300, 52, 800, 1.2);
    // スタートライン(スタート直後に消す)
    var la = 1 - sstep(1.2, 2.4, t);
    if (la > 0) {
      ctx.globalAlpha = la; ctx.setLineDash([2.2, 1.8]); ctx.lineWidth = 0.35; ctx.strokeStyle = "#ffffff";
      ctx.beginPath(); ctx.moveTo(0, 2); ctx.lineTo(0, 46); ctx.stroke(); ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }
    // ターンマーク
    [BUOY, BUOY2].forEach(function (m) {
      ctx.beginPath(); ctx.arc(m.x, m.y, BUOY_R, 0, Math.PI * 2); ctx.fillStyle = "#ff6a1a"; ctx.fill();
      ctx.lineWidth = 0.35; ctx.strokeStyle = "#ffffff"; ctx.stroke();
      ctx.beginPath(); ctx.arc(m.x, m.y, 0.55, 0, Math.PI * 2); ctx.fillStyle = "#ffffff"; ctx.fill();
    });
    // 引き波(水面に残る)
    ctx.lineCap = "butt";
    P.boats.forEach(function (b) {
      var pts = [];
      for (var j = 0; j <= 32; j++) {
        var tj = tt - j * 0.075;
        if (tj < T0) break;
        pts.push(sample(b, tj));
      }
      for (var i = 1; i < pts.length; i++) {
        var a = pts[i - 1], c = pts[i], f = Math.pow(1 - i / 32, 1.6), d0 = 0.6 + (i - 1) * 0.13, d1 = 0.6 + i * 0.13;
        var ax = -Math.sin(a.h), ay = Math.cos(a.h), cxn = -Math.sin(c.h), cyn = Math.cos(c.h);
        ctx.strokeStyle = "rgba(255,255,255," + (0.26 * f).toFixed(3) + ")";
        ctx.lineWidth = 0.9 + i * 0.045;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(c.x, c.y); ctx.stroke();
        ctx.strokeStyle = "rgba(255,255,255," + (0.45 * f).toFixed(3) + ")";
        ctx.lineWidth = 0.28;
        ctx.beginPath(); ctx.moveTo(a.x + ax * d0, a.y + ay * d0); ctx.lineTo(c.x + cxn * d1, c.y + cyn * d1); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(a.x - ax * d0, a.y - ay * d0); ctx.lineTo(c.x - cxn * d1, c.y - cyn * d1); ctx.stroke();
      }
    });
    // ボートと、旋回中の水しぶき
    var now = P.boats.map(function (b) { return sample(b, tt); });
    P.boats.forEach(function (b, k) {
      var p = now[k], col = COLORS[b.waku] || COLORS[1];
      if (Math.abs(p.w) > 0.3 && t < P.tEnd + 1) {
        var ox = -Math.sin(p.h), oy = Math.cos(p.h), bx = p.x - Math.cos(p.h) * HULL_L * 0.45, by = p.y - Math.sin(p.h) * HULL_L * 0.45;
        var amt = clamp((Math.abs(p.w) - 0.3) * 1.2, 0, 1);
        for (var j = 0; j < 4; j++) {
          ctx.beginPath(); ctx.arc(bx + ox * (0.9 + j * 0.55), by + oy * (0.9 + j * 0.55), 0.55 + j * 0.35, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(255,255,255," + (0.36 * amt * (1 - j / 4)).toFixed(3) + ")"; ctx.fill();
        }
      }
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.h);
      hull(ctx); ctx.fillStyle = col[0]; ctx.fill();
      ctx.lineWidth = 0.18; ctx.strokeStyle = b.waku === 1 ? "#33474f" : "rgba(255,255,255,0.7)"; ctx.stroke();
      ctx.beginPath(); ctx.ellipse(-HULL_L * 0.12, 0, 0.55, 0.42, 0, 0, Math.PI * 2); ctx.fillStyle = "rgba(0,0,0,0.35)"; ctx.fill();  // 選手
      ctx.restore();
    });
    // 艇番・ST・吹き出し(画面の大きさで描く)
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    var u = cw / 100, fsN = Math.max(9, Math.min(u * 2.3, HULL_L * 0.55 * sc));
    function scr(p) { return [(p.x - camX) * sc + cw / 2, (p.y - camY) * sc + ch / 2]; }
    P.boats.forEach(function (b, k) {
      var s2 = scr(now[k]), col = COLORS[b.waku] || COLORS[1];
      ctx.font = "700 " + fsN + "px " + MONO; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.lineWidth = Math.max(2, fsN * 0.22); ctx.strokeStyle = col[0]; ctx.strokeText(String(b.waku), s2[0], s2[1]);
      ctx.fillStyle = col[1]; ctx.fillText(String(b.waku), s2[0], s2[1]);
      if (t >= b.st - 0.05 && t <= b.st + 1.2) {                 // スタートの瞬間にSTを出す
        ctx.globalAlpha = 1 - sstep(b.st + 0.8, b.st + 1.2, t);
        ctx.font = "600 " + Math.max(9, u * 1.9) + "px " + MONO; ctx.textAlign = "left";
        ctx.fillStyle = "#ffffff"; ctx.fillText("ST" + b.st.toFixed(2).replace(/^0/, ""), s2[0] + HULL_L * 0.62 * sc + 3, s2[1]);
        ctx.globalAlpha = 1;
      }
    });
    var spots = now.map(scr), rBoat = HULL_L * 0.55 * sc + 6;
    P.events.forEach(function (e) {
      if (t < e.t - 0.15 || t > e.t + 2.0) { e.k = null; return; }   // 出ていないときは置き場所を忘れる(次に出るとき選び直す)
      var k = P.boats.indexOf(e.b), s2 = spots[k];
      var a = Math.min(sstep(e.t - 0.15, e.t + 0.1, t), 1 - sstep(e.t + 1.7, e.t + 2.0, t));
      bubble(ctx, e.text, e.b, s2[0], s2[1], cw, ch, u, a, e.below, spots.filter(function (_, j) { return j !== k; }), rBoat, e);
    });
    function pill(text, x, y, align, bg, fg, size) {
      ctx.font = "700 " + size + "px " + FONT; ctx.textBaseline = "middle";
      var w = ctx.measureText(text).width + size * 1.1, h = size * 1.7, left = align === "right" ? x - w : x;
      ctx.fillStyle = bg; roundRect(ctx, left, y, w, h, h / 2); ctx.fill();
      ctx.fillStyle = fg; ctx.textAlign = "left"; ctx.fillText(text, left + size * 0.55, y + h / 2 + 1);
    }
    var fs = Math.max(11, u * 2.5);
    pill(opt.title || "1周1マーク", u * 2, u * 2, "left", "rgba(8,26,34,0.72)", "#ffffff", fs);
    pill(P.sc.course + "コース " + P.sc.kim + (P.sc.p != null ? " " + Math.round(P.sc.p) + "%" : ""), cw - u * 2, u * 2, "right", "#f2cf1d", "#14212b", fs);
    if (t < 0) pill("スタートまで " + (-t).toFixed(1), u * 2, u * 3.2 + fs * 1.7, "left", "rgba(8,26,34,0.72)", "#ffffff", fs * 0.9);
    ctx.font = Math.max(9, u * 1.6) + "px " + FONT; ctx.fillStyle = "rgba(255,255,255,0.8)"; ctx.textAlign = "right"; ctx.textBaseline = "bottom";
    ctx.fillText((opt.brand ? opt.brand + " ・ " : "") + "データに基づくシミュレーション", cw - u * 2, ch - u * 1.5);
    if (t > P.tEnd - 0.6) {                                       // 最後に先頭を出す
      ctx.globalAlpha = sstep(P.tEnd - 0.6, P.tEnd, t);
      var w = P.winner;
      pill("1周1マーク 先頭 " + w.waku + "号艇 " + w.name, u * 2, ch - u * 2 - fs * 1.9, "left", "rgba(8,26,34,0.8)", "#ffffff", fs * 1.05);
      ctx.globalAlpha = 1;
    }
  }

  function mount(canvas, opt) {
    var ctx = canvas.getContext("2d");
    var P = plan(opt.entries, opt.scen, opt.kimarite);
    var t = T0, playing = false, last = null, speed = 1, raf = null, fixed = null;
    function end() { return P.tEnd + 1.6; }
    function size() {
      if (fixed) return;
      var dpr = Math.min(2, window.devicePixelRatio || 1), w = canvas.clientWidth || 640;
      var W = Math.round(w * dpr), H = Math.round(W * 10 / 16);
      if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
    }
    function render() { size(); draw(ctx, canvas.width, canvas.height, P, t, opt); }
    function frame(now) {
      if (!playing) return;
      if (last != null) t += Math.min(0.05, (now - last) / 1000) * speed;
      last = now;
      if (t >= end()) { t = end(); playing = false; if (opt.onEnd) opt.onEnd(); }
      render();
      if (playing) raf = requestAnimationFrame(frame);
    }
    var api = {
      duration: function () { return end() - T0; },
      play: function () { if (playing) return; if (t >= end()) t = T0; playing = true; last = null; raf = requestAnimationFrame(frame); },
      pause: function () { playing = false; if (raf) cancelAnimationFrame(raf); },
      replay: function () { api.pause(); t = T0; api.play(); },
      isPlaying: function () { return playing; },
      seek: function (s) { t = clamp(T0 + s, T0, end()); render(); },
      setSpeed: function (s) { speed = s; },
      setScenario: function (sc, entries, title) {
        if (entries) opt.entries = entries;
        if (title) opt.title = title;
        opt.scen = sc; P = plan(opt.entries, sc, opt.kimarite); api.replay();
      },
      render: render,
      // 動画として書き出す(MediaRecorder対応ブラウザのみ)。1280x800で描き直して録画する
      record: function () {
        if (!canvas.captureStream || typeof MediaRecorder === "undefined") return Promise.reject(new Error("unsupported"));
        var types = ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm"];
        var type = types.filter(function (x) { return MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(x); })[0];
        if (!type) return Promise.reject(new Error("unsupported"));
        api.pause();
        fixed = true; canvas.width = 1280; canvas.height = 800;
        var stream = canvas.captureStream(30), rec = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 6000000 }), chunks = [];
        rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
        return new Promise(function (resolve) {
          rec.onstop = function () { fixed = null; render(); resolve(new Blob(chunks, { type: type.split(";")[0] })); };
          t = T0; render(); rec.start();
          var t0 = null;
          function step(now) {
            if (t0 == null) t0 = now;
            t = T0 + (now - t0) / 1000;
            if (t >= end()) { t = end(); render(); setTimeout(function () { rec.stop(); }, 200); return; }
            render(); requestAnimationFrame(step);
          }
          requestAnimationFrame(step);
        });
      }
    };
    window.addEventListener("resize", function () { if (!playing) render(); });
    render();
    return api;
  }

  root.Turn1 = { mount: mount, plan: plan };
})(typeof window !== "undefined" ? window : globalThis);
