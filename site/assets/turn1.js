/* 1周1マーク シミュレーション
   出走表のデータ(ST・モーター・展示タイム・級別・進入コース)と、展開の見立て(決着パターン)から、
   スタートから全艇が1周1マークを回り切るまでを、上空から見た映像として描く。

   戦法の動き(公式の用語の定義と、過去の成績で実際に起きていることに合わせる):
     逃げ        1コースが最初に回る(先マイ)。2コースが差し巧者なら小回り、外が全速型なら大きめに回る
     差し        左の艇(内の艇)を先に回らせ、その内側(ブイ際)を小回りで抜く。先に回る艇が膨らむほど、内に入る余地ができる。
                 余地がなければ、その艇の真後ろに続く(差し届かず)
     捲り        左の艇の外を、減速せずに全速で回る。スタートで前に出て、内の艇の前へ絞ってから回る。
                 捲られた艇は引き波を受けて沈みやすい(そのぶん、外の艇の差し・まくり差しが届きやすくなる)
     まくり差し  左の艇の前を横切って(捲って)、さらに左の艇の内側を差す(3〜6コースだけ)
     二段まくり  先に捲りに行った艇の、さらに外から捲る
     マーク      捲った艇の外について回る
     絞る        前に出た艇が、内の艇の前へ寄せていく。1艇身以上前に出るまでは内の艇の外にとどまり、寄せた位置は1マークまで保つ
     張る        捲りに来た艇を、1コースが外へ膨らんで止めに行く(2艇とも流れて、内が空く)
     残す        捲りに来た艇を先に行かせ、1コースが小回りで内に残る
   動かし方: 戦法から各艇のライン(走る道筋)を決め、優先する艇(前を横切る艇・先に回る艇)から順に時間を決める。
   後から決める艇は、先に決めた艇とぶつからないよう、手前から速度を落として譲る(差しは後ろから内へ、捲られる艇は捲る艇を先に行かせる)。
   引き波は、先に通った艇の跡(旋回の外側に強く、真後ろは泡)を横切ると速度が落ちる。
   吹き出しは、走らせた結果の位置関係(どちら側を通って前に出たか・前を横切ったか)から決める。
   単位はメートルと秒。ホームストレッチを左から右へ走り、右の1マークを左回りに回る。
   使い方: var v = Turn1.mount(canvas, {entries:[{waku,course,name,st,motor2,ex,cls,km,ls,n,w1}], scen:{course,kim,p}, kimarite, title, fixedST});
           v.play(); v.replay(); v.setScenario(scen, entries, title, fixedST); v.record() -> Promise<Blob>(対応ブラウザのみ) */
(function (root) {
  "use strict";
  var D = 140;                                   // スタートラインから1マークまでの距離
  var BUOY = { x: D, y: 0 }, BUOY2 = { x: D - 300, y: 0 }, BUOY_R = 1.25;
  var CLEAR = 3.4;                               // ブイの中心から艇の中心まで、必ず空ける距離
  var LANE0 = 7, LANE_W = 6;                     // スタート時の横位置(1コースが一番内側)
  var HULL_L = 4.4, HULL_W = 1.8;
  var T0 = -2.6, DT = 1 / 60, T_MAX = 22;        // スタートの2.6秒前から描く
  var NF = Math.round((T_MAX - T0) / DT) + 1;
  var R0 = 8;                                    // 位置関係を比べるときの、旋回部分の目盛り(半周 = R0*π m)
  var KM3 = ["捲り", "捲り差し", "差し"];
  // 全国のコース別の1着の決まり手の割合(捲り・捲り差し・差し)。場のデータがないときに使う
  var PRIOR = { 2: [0.28, 0.0, 0.64], 3: [0.42, 0.37, 0.12], 4: [0.49, 0.25, 0.17], 5: [0.16, 0.65, 0.07], 6: [0.27, 0.45, 0.12] };
  var COLORS = { 1: ["#f4f6f8", "#14212b"], 2: ["#1b1b1b", "#ffffff"], 3: ["#d7282f", "#ffffff"],
                 4: ["#1d5fbf", "#ffffff"], 5: ["#f2cf1d", "#14212b"], 6: ["#1f9a4b", "#ffffff"] };
  var FONT = '"Zen Kaku Gothic New","Hiragino Sans","Noto Sans JP",sans-serif';
  var MONO = '"IBM Plex Mono",ui-monospace,monospace';

  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function sstep(a, b, x) { var t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }
  function avg(a) { var v = a.filter(function (x) { return x != null && !isNaN(x); }); return v.length ? v.reduce(function (s, x) { return s + x; }, 0) / v.length : null; }
  var TAU = 2 * Math.PI;
  function angd(a, b) { var d = a - b; if (d > Math.PI || d < -Math.PI) d -= TAU * Math.round(d / TAU); return d; }   // 角度の差(-π〜π)

  // ---- 選手ごとの性能
  function prepare(entries) {
    var boats = entries.map(function (e) {
      return { waku: e.waku, course: e.course || e.waku, name: e.name || (e.waku + "号艇"),
               st: e.st == null ? 0.16 : clamp(e.st, 0.01, 0.35), st0: e.st == null ? 0.16 : clamp(e.st, 0.01, 0.35),
               motor2: e.motor2, ex: e.ex, cls: e.cls, km: e.km || {}, ls: e.ls || {}, n: e.n || 0, w1: e.w1 || 0 };
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
      b.X = new Float32Array(NF); b.Y = new Float32Array(NF); b.H = new Float32Array(NF);
      b.V = new Float32Array(NF); b.S = new Float32Array(NF); b.WK = new Float32Array(NF);
      b.adj = { dz: 0, yo: 0 }; b.extra = [];
    });
    return boats;
  }

  // 選手の戦法の傾向: このコースで勝ったときの決まり手(捲り・捲り差し・差し)を、場の傾向で補って割合にする
  function tacShares(b, vkim) {
    var c = b.course, t = vkim && vkim[c - 1], pr, s;
    if (t && (t[1] + t[2] + t[3]) > 0) { s = t[1] + t[2] + t[3]; pr = { "捲り": t[1] / s, "差し": t[2] / s, "捲り差し": t[3] / s }; }
    else { var p = PRIOR[c] || [0.34, 0.33, 0.33]; s = p[0] + p[1] + p[2]; pr = { "捲り": p[0] / s, "捲り差し": p[1] / s, "差し": p[2] / s }; }
    var tot = 0, W0 = 3, out = { prior: pr };
    KM3.forEach(function (k) { tot += b.km[k] || 0; });
    KM3.forEach(function (k) { out[k] = ((b.km[k] || 0) + W0 * pr[k]) / (tot + W0); });
    out.n = tot;
    return out;
  }

  // ---- スタート後の直線を、よけ合いなしで走らせたときの位置と速さ(eq: 全艇ST.15・同じモーターとしたとき)
  function straightRun(b, t, eq) {
    var st = eq ? 0.15 : b.st, vmax = eq ? 22 : b.vmax0 + (b.bias ? b.bias.vmax : 0);
    if (t < st) { var r = st - t; return { x: -(b.vline * r - b.apre * r * r / 2), v: b.vline - b.apre * r }; }
    var x = 0, v = b.vline;
    for (var s = st; s < t; s += DT) { v = Math.min(vmax, v + (0.95 * (vmax - v) + 0.6) * DT); x += v * DT; }
    return { x: x, v: v };
  }
  // 先頭が xLead まで来たときの、各艇の位置
  function project(boats, xLead, eq) {
    var t = 0, out = {};
    while (t < 9 && !boats.some(function (b) { return straightRun(b, t, eq).x >= xLead; })) t += 0.04;
    boats.forEach(function (b) { out[b.course] = straightRun(b, t, eq); });
    return out;
  }
  // 直線の見込みの表(0.02秒ごとの位置)。絞る艇が内の艇の前に出たかを見るのに使う
  function runTable(b) {
    var n = 601, out = new Float32Array(n), vmax = b.vmax0 + b.bias.vmax, x = 0, v = b.vline, tp = b.st;
    for (var k = 0; k < n; k++) {
      var tk = k * 0.02;
      if (tk < b.st) { var r = b.st - tk; out[k] = -(b.vline * r - b.apre * r * r / 2); continue; }
      while (tp < tk - 1e-9) { var h = Math.min(0.01, tk - tp); v = Math.min(vmax, v + (0.95 * (vmax - v) + 0.6) * h); x += v * h; tp += h; }
      out[k] = x;
    }
    b.run = out;
  }
  function runX(b, t) { var f = t / 0.02, k = Math.floor(f); if (k < 0) return b.run[0]; if (k >= 600) return b.run[600]; return b.run[k] + (b.run[k + 1] - b.run[k]) * (f - k); }
  function runT(b, x) {
    var R = b.run, lo = 0, hi = 600;
    if (x <= R[0]) return 0;
    if (x >= R[600]) return 12;
    while (hi - lo > 1) { var m = (lo + hi) >> 1; if (R[m] < x) lo = m; else hi = m; }
    return (lo + (x - R[lo]) / ((R[hi] - R[lo]) || 1)) * 0.02;
  }
  function decide(boats, sc, vkim, opt) {
    var byC = {}, cw = sc.course, k = sc.kim || "逃げ";
    if (cw === 1) k = "逃げ";
    if (k === "抜き" || k === "恵まれ") k = "差し";
    if (cw === 2 && k === "捲り差し") k = "差し";              // まくり差しは3〜6コースだけ
    boats.forEach(function (b) {
      byC[b.course] = b;
      b.bias = { vmax: 0, alat: 1 }; b.slow = []; b.role = null; b.ref = null; b.over = []; b.under = null;
      b.win = b.course === cw; b.adj = { dz: 0, yo: 0 }; b.wait = 0; b.stAdj = 0; b.fail = false; b.squeezed = false; b.byOrder = false; b.goWide = false;
      b.tac = tacShares(b, vkim);
    });
    var b1 = byC[1], W = byC[cw] || boats[0], A = null;
    var avgV = avg(boats.map(function (b) { return b.vmax0; }));
    var Q = project(boats, 95, true), P = null;
    function reproject() { P = project(boats, 95, false); }
    reproject();
    // a が b より何秒ぶん前にいるか(ダッシュの助走の差は除く。ST差0.05秒 ≒ 1m)
    function lead(a, b) { return a && b ? ((P[a.course].x - P[b.course].x) - (Q[a.course].x - Q[b.course].x)) / 19 : 0; }
    function inner(a) { return boats.filter(function (o) { return o.course < a.course; }); }
    function leadIn(a) { var m = Infinity; inner(a).forEach(function (o) { m = Math.min(m, lead(a, o)); }); return m === Infinity ? 0 : m; }
    // 捲りに行くのに必要な、内の艇より前に出ている量(秒)。捲り型の選手ほど小さい
    function thr(b) {
      var base = { 2: 0.065, 3: 0.05, 4: 0.04, 5: 0.05, 6: 0.07 }[b.course] || 0.06;
      return clamp(base - 0.06 * (b.tac["捲り"] - b.tac.prior["捲り"]), 0.025, 0.09);
    }
    function margin(b) { return leadIn(b) - thr(b); }
    // 決着パターンに必要なだけ前に出す(足りない分はSTで。実際のSTを使うときはモーターの伸びで)
    function force(x, set, m) {
      if (!x) return;
      var need = 0;
      set.forEach(function (o) { need = Math.max(need, m - lead(x, o)); });
      if (need <= 0.001) return;
      if (opt.fixedST) { x.bias.vmax += Math.min(1.4, need * 19 / 2.2); reproject(); return; }
      // 足りない分は、まず仕掛ける艇のST(早めるのは合計0.04秒まで)、残りは相手のSTを遅らせる(合計0.05秒まで)
      var dx = Math.max(0, Math.min(need, 0.04 + x.stAdj));
      x.st = Math.max(0.01, x.st - dx); x.stAdj -= dx;
      if (need - dx > 0.001) set.forEach(function (o) { var d = Math.max(0, Math.min(need - dx, 0.05 - o.stAdj)); o.st = Math.min(0.35, o.st + d); o.stAdj += d; });
      reproject();
    }
    function strong1() {
      var s = { A1: 0.9, A2: 0.6, B1: 0.3, B2: 0.1 }[b1.cls] || 0.3;
      if (b1.n >= 6) s += (b1.w1 / b1.n - 0.55) * 1.5;
      return s + (b1.vmax0 - avgV) * 0.4;
    }
    function natural() {
      var best = null, bm = 0;
      boats.forEach(function (b) {
        if (b.course < 2) return;
        var m = margin(b);
        if (m >= 0 && (!best || m > bm)) { best = b; bm = m; }
      });
      return best;
    }
    function set(b, role, ref, over, under) { if (!b) return; b.role = role; b.ref = ref || null; b.over = over || []; b.under = under || null; }
    function midBoats(lo, hi) { return boats.filter(function (o) { return o.course > lo && o.course < hi; }); }

    // 着順の並び(予想、または実際のレースの着順)が分かっていれば、それに合わない仕掛けはさせない
    var tgt = opt.order || sc.order || null;
    function tpos(c) { return tgt ? tgt.indexOf(c) : -1; }
    if (k === "逃げ") {
      A = natural();
      if (A && A.course === 2 && margin(A) < 0.03) A = null;                // 2コースは少し出ても差しに回ることが多い
      if (A && tgt && tpos(A.course) <= 1) A = null;                        // 2着に残る艇は、捲りに行って止められた形ではない(差し・ついて回る)
      if (A) { set(A, "makuri", b1); A.fail = true; set(b1, strong1() >= 0.45 ? "nigeHari" : "nige"); }  // 張り気味に先に回って止める
      else set(b1, byC[2] && byC[2].tac["差し"] >= 0.72 ? "kotsu" : "nige");
    } else if (k === "捲り") {
      A = W;
      force(W, inner(W), Math.max(0.035, thr(W) * 0.7));
      set(W, "makuri", b1);
      set(b1, strong1() >= 0.8 && lead(W, b1) < 0.05 ? "hari" : "nokoshi");
    } else if (k === "差し") {
      if (cw === 2) {
        // 2コースの差しが決まるのは、1コースが全速で流れるか、外の捲りに張って2艇とも流れたとき
        var cand = [byC[3], byC[4]].filter(Boolean).sort(function (a, b) { return margin(b) - margin(a); })[0];
        if (cand && margin(cand) >= -0.03) { A = cand; force(A, inner(A), 0.025); set(A, "makuri", b1); set(b1, "hari"); A.flowOut = true; }
        else set(b1, "zensoku");
        set(W, "sashi", b1);
      } else {
        // 内の艇が捲り、1コースが張って2艇とも流れる → 空いた内を差す
        A = byC[cw - 1];
        if (cw >= 5 && byC[cw - 2] && margin(byC[cw - 2]) > margin(A)) A = byC[cw - 2];
        force(A, inner(A), 0.03);
        set(A, "makuri", b1); set(b1, "hari"); set(W, "sashi", A); A.flowOut = true;      // 張られて2艇とも流れる
        force(A, [W], 0.045);                                                           // 捲る艇が前、差す艇はその後ろ(並んでいると内へ入れない)
        midBoats(1, A.course).forEach(function (o) { o.wait = 1; });
        midBoats(A.course, cw).forEach(function (o) { o.wait = 1; });
      }
    } else if (k === "捲り差し") {
      var nb = byC[cw - 1];
      if (cw === 3) {
        // 2コースが差し構えで待つところを、3コースが2コースの舳先の前を横切り、1コースの内へ
        force(W, [nb], 0.0);
        set(b1, "zensoku"); set(nb, "sashi", b1); nb.wait = 1;
        set(W, "makurizashi", null, [nb], b1);
      } else {
        // 4〜6コースのまくり差し: 隣の艇(と、その内の艇)の前を横切って、先に回った艇の内へ。
        // 隣より内の艇が捲って1コースを流していれば、その捲った艇の内へ(例: 2コースのジカまくり → 5コースのまくり差し)
        var cands = midBoats(1, cw - 1).filter(function (o) { return o.course >= 2; }).sort(function (a, b) { return margin(b) - margin(a); });
        var att = cands[0] && margin(cands[0]) >= -0.03 ? cands[0] : null;
        if (att) {
          A = att; force(A, inner(A), 0.03);
          set(A, "makuri", b1); set(b1, "hari"); A.flowOut = true;
          var ov2 = midBoats(A.course, cw);
          force(A, [W], 0.02); force(W, ov2, 0.012); force(W, [A], -0.03);
          set(W, "makurizashi", null, ov2, A);
          ov2.forEach(function (o) { set(o, "sashi", A); o.wait = 1; });
          midBoats(1, A.course).forEach(function (o) { o.wait = 1; });
        } else {
          var ov = midBoats(1, cw);
          force(W, ov, 0.012);
          set(b1, "zensoku");
          set(W, "makurizashi", null, ov, b1);
          ov.forEach(function (o) { set(o, "sashi", b1); o.wait = 1; });   // 前を横切られる艇は、差し構えで待つ
        }
      }
    }
    // 着順の並び(見立て)が分かっていれば、仕掛けに関わらない艇の回り方を、その並びになる形にする:
    //   自分より内で、自分より後ろの着になる艇は、その前を横切って内へ切り込む(まくり差し)。
    //   そうでなければ、前の着の内の艇について外を回るか(マーク)、内の艇の後ろを差す(2コース)。下の着の外の艇は外を回す
    if (tgt) {
      // 決着パターンに関わる艇(仕掛けた艇に捲られる内の艇、横切られる艇・待つ艇)は、そのままにする
      boats.forEach(function (o) { o.crit = !!o.role || o.wait > 0 || !!(A && !A.fail && o.course > 1 && o.course < A.course); });
      for (var p0 = 1; p0 < 6; p0++) {
        var X = byC[tgt[p0]];
        if (!X || X.crit || X.role || X.course === 1) continue;
        X.byOrder = true;
        // 前の着の艇のうち、自分より内で一番外の艇(その後ろを回る)。勝つ艇の内へは切り込まない(逃げの1コースの後ろは別)
        var ahead = boats.filter(function (o) { return tpos(o.course) < p0 && (o !== W || k === "逃げ"); });
        // 見立ての着順で自分のすぐ前にいる内の艇(その後ろを回る)
        var U = ahead.filter(function (o) { return o.course < X.course; }).sort(function (a, b) { return tpos(b.course) - tpos(a.course); })[0] || null;
        var S = boats.filter(function (o) { return o.course < X.course && tpos(o.course) > p0; });
        var over = U ? S.filter(function (o) { return o.course > U.course; }) : [];
        // 前の艇が外へ膨らんで回るなら、その内へ切り込むと抜いてしまうので、外について回る(内の艇は待たせる)
        var wideU = U && (["zensoku", "hari", "makuri", "nidan", "zen", "mark", "soto"].indexOf(U.role) >= 0 || U.fail || U.flowOut);
        if (over.length && wideU) {
          set(X, "mark", U);
          over.forEach(function (o) { o.wait = Math.max(o.wait, 0.8); });
        } else if (over.length) {
          // 内の艇の前を横切って、前の着の艇の後ろへ切り込む(足りなければスタートで合わせる。横切られる艇は差し構えで待つ)
          force(X, over, 0.012);
          set(X, "makurizashi", null, over, U);
          over.forEach(function (o) { o.wait = Math.max(o.wait, 0.6); });
        } else if (U) {
          if (X.course === 2) set(X, "sashi", U);
          else if (p0 >= 4 && X.course >= 4 && !S.length) set(X, "soto");
          else set(X, "mark", U);
        } else if (W.course < X.course) {
          set(X, "mark", W);                                                 // 勝つ艇(捲り・まくり差し)の外について回る
        } else {
          set(X, "sashi", byC[tgt[p0 - 1]] || W); X.wait = Math.max(X.wait, 0.5);
        }
      }
    }
    // ほかの艇: 仕掛けた艇との位置関係で動く
    boats.forEach(function (b) {
      if (b.role) return;
      var c = b.course;
      if (c === 1) { set(b, A && !A.fail ? (strong1() >= 0.8 && lead(A, b) < 0.04 ? "hari" : "nokoshi") : "nige"); return; }
      if (A && c < A.course) { set(b, "sashi", b1); b.squeezed = true; return; }          // 捲られる側: 内で小回り(遅れる)
      if (A && c === A.course + 1) {
        var lc = lead(b, A);
        if (lc >= 0.03 && b.tac["捲り"] >= 0.4 && !A.win) { set(b, "nidan", A); return; }         // さらに外から捲る
        if (lc >= -0.02 && b.tac["捲り"] >= 0.33 && b.tac["差し"] < 0.45) { set(b, "mark", A); return; }   // 捲りについて行く
        if (b.tac["捲り差し"] >= b.tac["差し"]) set(b, "makurizashi", null, midBoats(1, A.course), A);
        else set(b, "sashi", A);
        return;
      }
      if (A && c > A.course + 1) {
        var inb = byC[c - 1];
        if (c <= 5 && inb && inb.role === "mark" && b.tac["差し"] >= 0.3) set(b, "sashi", inb);      // 捲りについて行った艇の内を差す
        else set(b, "soto");
        return;
      }
      // 仕掛けがないとき(または仕掛けた艇より内)
      if (c === 2) { set(b, "sashi", b1); return; }                                        // 2コースは差し構え
      if (c === 3) {
        if (lead(b, byC[2]) >= 0.015 && b.tac["捲り差し"] >= 0.3 && !byC[2].win && !b1.win) set(b, "makurizashi", null, [byC[2]], b1);
        else set(b, "zen");                                                                // 1・2コースの外を全速で
        return;
      }
      var left = byC[c - 1];
      if (c === 4) { set(b, b.tac["差し"] >= 0.3 || !left ? "sashi" : "mark", left || b1); return; }   // 3コースの後を追う(または内を差す)
      // 5・6コース: 内の艇が遅れていれば、その前を横切ってさらに内の艇の内へ(まくり差し)。そうでなければ差すか外を回す
      if (left && lead(b, left) >= 0.02 && b.tac["捲り差し"] >= 0.4 && byC[c - 2] && byC[c - 2].role !== "sashi" && !left.win && !byC[c - 2].win) {
        set(b, "makurizashi", null, [left], byC[c - 2]); left.wait = Math.max(left.wait, 0.5); return;
      }
      if (left && b.tac["差し"] >= 0.25 && c === 5) { set(b, "sashi", left); return; }
      set(b, "soto");
    });
    boats.forEach(function (b) {
      if (b.role === "makurizashi" && !b.under) b.under = b1;
      // 勝つ艇の前を横切ったり、勝つ艇の内を差したりする動きは、決着パターンと食い違うのでさせない(後ろから差すか、ついて行く)
      if (!b.win && b.role === "makurizashi" && (b.over.indexOf(W) >= 0 || b.under === W) && !(b.byOrder && k === "逃げ" && b.under === W)) {
        if (A && A !== b && !A.win) set(b, b.tac["差し"] >= 0.3 ? "sashi" : "mark", A); else set(b, "sashi", W);
        b.over = [];
      }
      if ((b.role === "sashi" || b.role === "mark" || b.role === "nidan" || b.role === "makuri") && !b.ref) b.ref = b1;
    });
    return { attacker: A, kim: k };
  }

  // ======================================================================
  // ライン(走る道筋): 1マークに入る横位置(yi)、ブイに一番近づく距離(dz)、出口の横位置(yo)、旋回の膨らみ方(rho = 出口の半径/入口の半径)
  // ======================================================================
  function natY(c) { return 5.8 + 4.2 * (c - 1); }          // 仕掛けがないときに、1マークの手前で寄っている位置
  var ORDER = { nige: 0, nigeHari: 0, kotsu: 0, zensoku: 0, hari: 0, nokoshi: 0, makuri: 1, nidan: 2, mark: 2, zen: 3, sashi: 4, makurizashi: 4, soto: 5 };

  // 1マークの手前に着く順番の目安(直線の見込みと、戦法ごとの待ち)。差しの「内の壁」(先に回る艇)を決めるのに使う
  function arrivals(boats) {
    boats.forEach(function (b) {
      var w = 0;
      if (b.role === "sashi") w += b.squeezed ? 0.16 : 0.1;
      if (b.wait) w += 0.12 * b.wait;
      if (b.role === "nokoshi") w += 0.06;
      if (b.role === "mark") w += 0.12;
      if (b.role === "soto") w += 0.08;
      b.tArr = runT(b, 118) + w;
    });
  }

  // X が Y の内を差すときのライン: Y と、X より先に回る内側の艇(内の壁)の間。内の壁がなければブイ際。入る余地がなければ null
  function gapLine(X, Y, boats) {
    var wall = null;
    boats.forEach(function (o) {
      // 先に回る艇と、ブイ際を小回りする1コース(ほぼ同時に回るなら、その内は通れない)
      if (o === X || o === Y || !o.sp) return;
      if (!(o.course === 1 && o.sp.dz <= 4.4) && o.tArr > X.tArr - 0.04) return;
      if (o.sp.dz < Y.sp.dz - 0.5 && (!wall || o.sp.dz > wall.sp.dz)) wall = o;
    });
    var wdz = wall ? wall.sp.dz : CLEAR, gap = Y.sp.dz - wdz;
    if (gap < 2.4) return null;
    // 内の壁のすぐ外(艇1つ分あけて)を小さく回る。間が広くても真ん中ではなく、内寄りを突く
    if (wall) return { dz: Math.min(wdz + 2.6, Y.sp.dz - 2.0), yo: clamp(wall.sp.yo - 3.2, Y.sp.yo + 2.6, -7.2), wall: wall };
    return { dz: CLEAR + 0.45 + Math.max(0, (gap - 3.5) * 0.08), yo: clamp(Y.sp.yo + 2.6, -9.8, -7.2), wall: null };   // ブイ際を小さく回る
  }

  function specOf(b, byC, boats) {
    var c = b.course, L = b.lane, sp, b1 = byC[1];
    var s1 = b1 && b1.sp ? b1.sp : { yi: 6, dz: 4.2, yo: -11, rho: 1.3 };
    var ref = b.ref && b.ref.sp ? b.ref : null, rs = ref ? ref.sp : s1;
    switch (b.role) {
      case "nige": sp = { yi: 6.0, dz: 4.2, yo: -11.0, rho: 1.3 }; break;
      case "nigeHari": sp = { yi: 7.6, dz: 4.9, yo: -12.2, rho: 1.25, late: true }; break;          // 張り気味に先に回る
      case "kotsu": sp = { yi: 5.6, dz: 3.8, yo: -9.6, rho: 1.25 }; break;                          // 小回り(差しの余地をなくす)
      case "zensoku": sp = { yi: 6.4, dz: 6.2, yo: -15.5, rho: 1.35 }; break;                       // 全速で回って膨らむ
      case "hari": sp = { yi: L + 3.2, dz: 7.6, yo: -18.0, rho: 1.3, late: true }; break;           // 外へ張って止めに行く
      case "nokoshi": sp = { yi: 5.6, dz: 3.7, yo: -9.0, rho: 1.3 }; break;                         // 小回りで残す
      case "makuri": sp = { yi: rs.yi + 3.4, dz: rs.dz + 3.4, yo: Math.min(-12.5, rs.yo - 2.4), rho: 1.08, sq: true }; break;
      case "nidan": sp = { yi: rs.yi + 3.3, dz: rs.dz + 3.2, yo: rs.yo - 2.6, rho: 1.06, sq: true }; break;
      case "mark": sp = { yi: rs.yi + 3.0, dz: rs.dz + 2.2, yo: rs.yo - 2.0, rho: rs.rho || 1.1, follow: true }; break;
      case "zen": sp = { yi: Math.max(natY(c), s1.yi + 7.0), dz: s1.dz + 4.2, yo: s1.yo - 3.8, rho: 1.15 }; break;
      case "sashi": {
        // 絞って捲りに行った艇の内を差すときは、その艇の後ろについて内へ寄っていく
        var Y = ref || b1, g = gapLine(b, Y, boats), tr = Y.sp.sq && Y.course < c ? Y : null;
        var yiS = tr ? Y.sp.yi + 2.8 : Math.max(Y.sp.yi + 2.8, natY(c) - 0.8);
        if (g) sp = { yi: yiS, dz: g.dz, yo: g.yo, rho: 1.65, trail: tr };
        else sp = { yi: yiS, dz: Y.sp.dz + 0.25, yo: Y.sp.yo + 0.6, rho: (Y.sp.rho || 1.3) + 0.15, queue: true, trail: tr };
        break;
      }
      case "makurizashi": {
        // 差す相手が絞って捲った艇なら、その後ろについて内へ寄り、1マークでその内へ。そうでなければ1マークの手前で内の艇の前を横切る
        var U = b.under && b.under.sp ? b.under : b1, gu = gapLine(b, U, boats), tu = U.sp.sq ? U : null;
        var base = { yi: U.sp.yi + (tu ? 2.8 : 3.0), cross: !tu, trail: tu };
        if (gu) { base.dz = gu.dz; base.yo = gu.yo; base.rho = 1.55; }
        else { base.dz = U.sp.dz + 0.3; base.yo = U.sp.yo + 0.6; base.rho = (U.sp.rho || 1.3) + 0.15; base.queue = true; }
        sp = base;
        break;
      }
      default: {                                                               // 外マイ: 内の艇の全部の外を回る
        var inn = boats.filter(function (o) { return o.sp && o !== b && o.course < c && !o.sp.queue; });
        var dmax = inn.length ? Math.max.apply(null, inn.map(function (o) { return o.sp.dz; })) : 4;
        var ymin = inn.length ? Math.min.apply(null, inn.map(function (o) { return o.sp.yo; })) : -11;
        sp = { yi: natY(c) - (c >= 5 ? 1.0 : 0), dz: dmax + 3.0, yo: ymin - 2.6, rho: 1.1 };
      }
    }
    if (b.fail) { sp.dz += 2.4; sp.yo -= 3.0; }                                // 張られて流れる
    else if (b.flowOut) { sp.dz += 1.2; sp.yo -= 2.0; }                        // 全速で回って膨らむ(内を差される)
    sp.dz += b.adj.dz; sp.yo += b.adj.yo;
    return finishSpec(sp);
  }
  function finishSpec(sp) {
    sp.dz = clamp(sp.dz, CLEAR + 0.35, 15);
    var R1 = (sp.yi - sp.yo) / (1 + sp.rho);
    if (R1 < 5.0) { R1 = 5.0; sp.yo = sp.yi - R1 * (1 + sp.rho); }
    sp.R1 = R1; sp.R2 = R1 * sp.rho;
    sp.dz = Math.min(sp.dz, Math.min(sp.yi, -sp.yo) - 0.3);
    sp.xin = solveXin(sp);
    return sp;
  }

  // 旋回の入口の位置 xin を、ブイに一番近づく距離が dz になるように決める
  function turnMinDist(xin, yi, R1, R2) {
    var x = xin, y = yi, th = 0, n = 72, dth = Math.PI / n, md = 1e9, cross = null;
    for (var i = 0; i <= n; i++) {
      var d = Math.hypot(x - BUOY.x, y - BUOY.y);
      if (d < md) md = d;
      if (cross == null && y <= BUOY.y) cross = x;
      var R = R1 + (R2 - R1) * (i / n);
      x += R * Math.cos(th) * dth; y -= R * Math.sin(th) * dth; th += dth;
    }
    if (cross == null || cross < BUOY.x + 0.5) return -1;                     // ブイを回り込んでいない
    if (xin > BUOY.x) md = Math.min(md, Math.abs(yi));
    return md;
  }
  function solveXin(sp) {
    var lo = 95, hi = 175;
    for (var it = 0; it < 34; it++) {
      var m = (lo + hi) / 2;
      if (turnMinDist(m, sp.yi, sp.R1, sp.R2) < sp.dz) lo = m; else hi = m;
    }
    return hi;
  }

  // ラインを決める順: 相手(捲る相手・差す相手・ついて行く相手)と、先に回る内の艇のラインを先に決める
  function deps(b, byC, boats) {
    var d = [];
    if (b.ref) d.push(b.ref);
    if (b.under) d.push(b.under);
    if ((b.role === "zen" || b.role === "makurizashi" || b.role === "sashi") && byC[1]) d.push(byC[1]);
    if (b.role === "sashi" || b.role === "makurizashi")
      boats.forEach(function (o) { if (o.course < b.course && o.tArr < b.tArr - 0.04 && o.role !== "soto") d.push(o); });
    if (b.role === "soto") boats.forEach(function (o) { if (o.course < b.course && o.role !== "soto") d.push(o); });
    return d.filter(function (o) { return o && o !== b; });
  }
  function specs(boats, byC) {
    boats.forEach(function (b) { b.sp = null; });
    var left = boats.slice().sort(function (a, b) { return (ORDER[a.role] * 10 + a.course) - (ORDER[b.role] * 10 + b.course); });
    while (left.length) {
      var k = 0;
      for (var i = 0; i < left.length; i++) if (deps(left[i], byC, boats).every(function (o) { return o.sp; })) { k = i; break; }
      var b = left.splice(k, 1)[0];
      b.sp = specOf(b, byC, boats);
    }
    boats.forEach(function (x) {
      if (x.role !== "makurizashi") return;
      x.over.forEach(function (o) { if (o.sp && !o.win && o.sp.yi < x.sp.yi + 1.6) { o.sp.yi = x.sp.yi + 1.6; finishSpec(o.sp); } });
    });
  }

  // 1マークまでの横の動き(1mごと)。絞る・前を横切る艇は、内の艇より1艇身以上前に出るまで、その艇の外にとどまる
  function smooth1(a, r) {
    var n = a.length, out = new Float32Array(n);
    for (var i = 0; i < n; i++) { var s = 0, m = 0; for (var j = Math.max(0, i - r); j <= Math.min(n - 1, i + r); j++) { s += a[j]; m++; } out[i] = s / m; }
    for (i = 0; i < n; i++) a[i] = out[i];
  }
  function slopeLimit(a, g) {
    for (var i = 1; i < a.length; i++) a[i] = clamp(a[i], a[i - 1] - g, a[i - 1] + g);
    for (i = a.length - 2; i >= 0; i--) a[i] = clamp(a[i], a[i + 1] - g, a[i + 1] + g);
  }
  function approachOf(b, sorted) {
    var sp = b.sp, L = b.lane, xe = Math.max(30, sp.xin - 12), n = Math.ceil(sp.xin) + 2, ys = new Float32Array(n), k;
    var w0 = sp.sq ? 14 : sp.cross ? sp.xin - 56 : sp.late ? sp.xin - 58 : sp.follow ? 40 : 22, w1 = sp.sq ? Math.min(95, xe) : sp.cross ? sp.xin - 5 : xe;
    var tr = sp.trail && sp.trail.ay ? sp.trail.ay : null;
    for (k = 0; k < n; k++) {
      if (tr) {                                                               // 前の艇の外(2.8m)について寄っていく
        var base = tr[Math.min(k, tr.length - 1)] + 2.8;
        ys[k] = L + (base - L) * sstep(10, 75, k);
        ys[k] += (sp.yi - ys[k]) * sstep(xe - 10, xe, k);
      } else ys[k] = L + (sp.yi - L) * sstep(w0, w1, k);
    }
    var floors = [];
    if (!sp.cross && !tr) {
      sorted.forEach(function (o) {
        if (o.course >= b.course || !o.ay) return;
        var fl = new Float32Array(n).fill(-99);
        for (var k2 = 0; k2 < n; k2++) {
          var xo = runX(o, runT(b, k2));
          if (sp.sq && k2 - xo >= 1.2) break;                                   // 絞る艇は、舳先が内の艇の舳先より前に出たら寄せ始める(内の艇は引いて入れる)
          fl[k2] = o.ay[clamp(Math.round(xo), 0, o.ay.length - 1)] + 2.7;      // ほかの艇は内の艇の外にとどまる
        }
        floors.push(fl);
      });
    }
    function applyFloors() { floors.forEach(function (fl) { for (var k3 = 0; k3 < n; k3++) if (ys[k3] < fl[k3]) ys[k3] = fl[k3]; }); }
    // 横の動きの速さの上限(前に進む量に対する割合)。横切る艇は1マークの手前で舳先を内に向けて切り込む
    applyFloors(); smooth1(ys, 5); applyFloors(); slopeLimit(ys, sp.cross ? 0.42 : sp.sq ? 0.2 : 0.16); applyFloors(); smooth1(ys, 2);
    return ys;
  }
  function approach(boats) {
    var sorted = boats.slice().sort(function (a, b) { return a.course - b.course; });
    sorted.forEach(function (b) { b.ay = null; });
    sorted.forEach(function (b) {
      var ys = approachOf(b, sorted), sp = b.sp, yEnd = ys[ys.length - 1];
      if (yEnd > sp.yi + 0.6) {                                               // 寄せきれなかった(内の艇が壁になった) → その位置から回る
        var d = yEnd - sp.yi;
        sp.yi = yEnd; sp.dz += d * 0.8; sp.yo -= d * 0.8; sp.blocked = d;
        finishSpec(sp);
        ys = approachOf(b, sorted);
      }
      b.ay = ys;
    });
  }

  function makePath(b) {
    var sp = b.sp, pts = [], i, ay = b.ay;
    for (var x = 0; x < sp.xin; x += 0.5) {
      var k = Math.min(ay.length - 2, Math.floor(x)), f = x - k;
      pts.push([x, ay[k] + (ay[k + 1] - ay[k]) * f]);
    }
    var iStart = pts.length, n = 200, dth = Math.PI / n, px = sp.xin, py = sp.yi, th = 0;
    for (i = 0; i <= n; i++) {
      pts.push([px, py]);
      var R = sp.R1 + (sp.R2 - sp.R1) * (i / n);
      px += R * Math.cos(th) * dth; py -= R * Math.sin(th) * dth; th += dth;
    }
    var iEnd = pts.length - 1, ex = pts[iEnd];
    for (var d = 0.5; d <= 240; d += 0.5) pts.push([ex[0] - d, ex[1] + 2.2 * sstep(12, 80, d)]);   // 2マークへ向けて少しずつ内へ
    // つなぎ目の折れをなくす(前後の点でならす)
    var N = pts.length, sm = new Array(N);
    for (i = 0; i < N; i++) {
      if (i < 8) { sm[i] = pts[i]; continue; }
      var sx = 0, sy = 0, m = 0;
      for (var u = i - 7; u <= i + 7; u++) { if (u < 0 || u >= N) continue; sx += pts[u][0]; sy += pts[u][1]; m++; }
      sm[i] = [sx / m, sy / m];
    }
    var s = new Float32Array(N), kk = new Float32Array(N), minB = 1e9;
    for (i = 1; i < N; i++) s[i] = s[i - 1] + Math.hypot(sm[i][0] - sm[i - 1][0], sm[i][1] - sm[i - 1][1]);
    for (i = 1; i < N - 1; i++) {
      var a1 = Math.atan2(sm[i][1] - sm[i - 1][1], sm[i][0] - sm[i - 1][0]);
      var a2 = Math.atan2(sm[i + 1][1] - sm[i][1], sm[i + 1][0] - sm[i][0]);
      kk[i] = Math.abs(angd(a2, a1)) / ((s[i + 1] - s[i - 1]) / 2 || 1);
    }
    for (i = 0; i < N; i++) minB = Math.min(minB, Math.hypot(sm[i][0] - BUOY.x, sm[i][1] - BUOY.y));
    var ks = new Float32Array(N);
    for (i = 0; i < N; i++) { var sum = 0, c = 0; for (u = Math.max(0, i - 6); u <= Math.min(N - 1, i + 6); u++) { sum += kk[u]; c++; } ks[i] = sum / c; }
    var px2 = new Float32Array(N), py2 = new Float32Array(N), ph = new Float32Array(N);
    for (i = 0; i < N; i++) { px2[i] = sm[i][0]; py2[i] = sm[i][1]; }
    for (i = 0; i < N; i++) { var a = Math.max(0, i - 1), z = Math.min(N - 1, i + 1); ph[i] = Math.atan2(py2[z] - py2[a], px2[z] - px2[a]); }
    return { x: px2, y: py2, h: ph, s: s, k: ks, sStart: s[iStart], sEnd: s[iEnd], minB: minB };
  }

  // 道のり s の地点の位置と向き
  function pathAt(P, sv) {
    var s = P.s, lo = 0, hi = s.length - 1;
    if (sv <= 0) return { x: P.x[0], y: P.y[0], h: P.h[0] };
    if (sv >= s[hi]) return { x: P.x[hi], y: P.y[hi], h: P.h[hi] };
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (s[mid] <= sv) lo = mid; else hi = mid; }
    var f = (sv - s[lo]) / (s[hi] - s[lo] || 1);
    return { x: P.x[lo] + (P.x[hi] - P.x[lo]) * f, y: P.y[lo] + (P.y[hi] - P.y[lo]) * f, h: P.h[lo] + angd(P.h[hi], P.h[lo]) * f };
  }

  // 位置関係を比べるための座標: s = コースに沿って進んだ量(旋回部分はブイのまわりの角度)、l = 内からの距離(直線はブイの線から、旋回はブイから)
  function cframe(x, y) {
    if (x <= BUOY.x) return y >= BUOY.y ? [x, y - BUOY.y] : [BUOY.x + R0 * Math.PI + (BUOY.x - x), BUOY.y - y];
    var phi = Math.atan2(y - BUOY.y, x - BUOY.x);
    return [BUOY.x + R0 * (Math.PI / 2 - phi), Math.hypot(x - BUOY.x, y - BUOY.y)];
  }

  function geometry(boats, byC) {
    specs(boats, byC);
    approach(boats);
    boats.forEach(function (b) {
      for (var tries = 0; tries < 5; tries++) {
        b.P = makePath(b);
        if (b.P.minB >= CLEAR + 0.15) break;
        b.sp.dz += CLEAR + 0.3 - b.P.minB; finishSpec(b.sp);
      }
      speedProfile(b);
    });
  }

  // ======================================================================
  // 速さと時間
  // ======================================================================
  // 走れる速さ: 曲がり具合(横向きの加速度の上限)・直線の最高速・旋回中の上限(大回りでも全速のままでは回れない。捲りは握って回るぶん速い)
  function speedProfile(b) {
    var P = b.P, n = P.s.length, vl = new Float32Array(n);
    var full = (b.role === "makuri" || b.role === "nidan" || b.role === "zen") && !b.fail;
    var vt0 = full ? 11.4 : 10.4;
    for (var i = 0; i < n; i++) { var kk = Math.max(P.k[i], 1e-4); vl[i] = Math.min(b.vmax, Math.sqrt(b.alat / kk), vt0 + 0.25 / kk); }
    for (i = n - 2; i >= 0; i--) vl[i] = Math.min(vl[i], Math.sqrt(vl[i + 1] * vl[i + 1] + 2 * 6.5 * (P.s[i + 1] - P.s[i])));
    b.vl = vl;
  }
  function zoneF(b, sv) {
    var f = 1, Z = b.slow;
    for (var j = 0; j < Z.length; j++) {
      var z = Z[j];
      if (sv < z.s0 - 14 || sv > z.s1 + 12) continue;
      f *= 1 - (1 - z.f) * sstep(z.s0 - 14, z.s0, sv) * (1 - sstep(z.s1, z.s1 + 12, sv));
    }
    return f;
  }
  function vlimAt(b, sv) {
    var s = b.P.s, lo = 0, hi = s.length - 1, base;
    if (sv >= s[hi]) base = b.vl[hi];
    else if (sv <= 0) base = b.vl[0];
    else { while (hi - lo > 1) { var m = (lo + hi) >> 1; if (s[m] <= sv) lo = m; else hi = m; } base = b.vl[lo]; }
    return base * zoneF(b, sv);
  }

  // 1艇を時間に沿って走らせる。先に決めた艇(planned)が前にいれば、間合いを取る
  var V_MIN = 6.5;                                           // どんなときもこれより遅くはならない(m/s)
  function integrate(b, planned) {
    var X = b.X, Y = b.Y, H = b.H, V = b.V, S = b.S, P = b.P, s = 0, v = b.vline, started = false;
    b.done = null;
    for (var i = 0; i < NF; i++) {
      var t = T0 + i * DT;
      if (t < b.st) {
        var r = b.st - t;
        X[i] = -(b.vline * r - b.apre * r * r / 2); Y[i] = b.lane; H[i] = 0; V[i] = b.vline - b.apre * r; S[i] = 0;
        continue;
      }
      if (started) {
        var vlim = vlimAt(b, s + v * 0.25);
        var a = v < vlim ? Math.min(0.95 * (b.vmax - v) + 0.6, (vlim - v) * 2.5) : -Math.min(9, (v - vlim) * 3);
        var hb = H[i - 1], cs = Math.cos(hb), sn = Math.sin(hb), gap = 1e9, lv = 0;
        for (var q = 0; q < planned.length; q++) {
          var o = planned[q], dx = o.X[i - 1] - X[i - 1], dy = o.Y[i - 1] - Y[i - 1];
          if (dx * dx + dy * dy > 900) continue;
          var fw = dx * cs + dy * sn, lt = -dx * sn + dy * cs;
          if (fw > 0 && Math.abs(lt) < HULL_W + 1.0) { var g = fw - HULL_L - 0.4; if (g < gap) { gap = g; lv = o.V[i - 1]; } }
        }
        if (gap < 1e8) { var dv = v - lv, ss = 1.0 + v * 0.2 + v * dv / (2 * Math.sqrt(18)); a -= 3 * Math.pow(Math.max(0, ss) / Math.max(0.25, gap), 2); }
        v = Math.max(V_MIN, v + clamp(a, -12, 4.5) * DT);
        s += v * DT;
      }
      started = true;
      var p = pathAt(P, s);
      X[i] = p.x; Y[i] = p.y; V[i] = v; S[i] = s;
      H[i] = i > 0 ? H[i - 1] + angd(p.h, H[i - 1]) : p.h;
      if (b.done == null && s >= P.sEnd) b.done = t;
    }
    if (b.done == null) b.done = T_MAX;
  }

  // 向きのある長方形どうしが重なるか
  function sat(ax, ay, ah, bx, by, bh, hl, hw) {
    var ca = Math.cos(ah), sa = Math.sin(ah), cb = Math.cos(bh), sb = Math.sin(bh), dx = bx - ax, dy = by - ay;
    var axes = [ca, sa, -sa, ca, cb, sb, -sb, cb];
    for (var k = 0; k < 8; k += 2) {
      var nx = axes[k], ny = axes[k + 1];
      var ra = hl * Math.abs(ca * nx + sa * ny) + hw * Math.abs(-sa * nx + ca * ny);
      var rb = hl * Math.abs(cb * nx + sb * ny) + hw * Math.abs(-sb * nx + cb * ny);
      if (Math.abs(dx * nx + dy * ny) > ra + rb) return false;
    }
    return true;
  }
  var ML = 0.5, MW = 0.6;                                     // ぶつからないように空ける余裕(前後・横)
  function firstConflict(b, planned) {
    var best = null, i0b = Math.max(0, Math.round((b.st - T0) / DT));
    for (var q = 0; q < planned.length; q++) {
      var o = planned[q], i0 = Math.max(i0b, Math.round((o.st - T0) / DT));
      for (var i = i0; i < NF; i++) {
        if (best && i >= best.i) break;
        if (b.S[i] > b.P.sEnd + 12) break;                     // 1マークを出てからの直線では譲らない(速い艇が横を抜いていく)
        var dx = o.X[i] - b.X[i], dy = o.Y[i] - b.Y[i];
        if (dx * dx + dy * dy > 30) continue;
        if (sat(b.X[i], b.Y[i], b.H[i], o.X[i], o.Y[i], o.H[i], (HULL_L + ML) / 2, (HULL_W + MW) / 2)) { best = { i: i, o: o }; break; }
      }
    }
    return best;
  }
  // ぶつかる地点に b を置いたまま、相手がそこを抜けるまでの時間(これだけ遅らせれば先に行かせられる)
  function clearTime(b, cf) {
    var i = cf.i, o = cf.o, x = b.X[i], y = b.Y[i], h = b.H[i], j = i;
    while (j < NF - 1 && sat(x, y, h, o.X[j], o.Y[j], o.H[j], (HULL_L + ML + 0.4) / 2, (HULL_W + MW + 0.3) / 2)) j++;
    return Math.max(0.08, (j - i) * DT + 0.12);
  }
  // 相手が後ろから突っ込んでくる形か(この場合は b を遅らせても避けられない)
  function rearEnd(b, cf) {
    var i = cf.i, o = cf.o, dx = o.X[i] - b.X[i], dy = o.Y[i] - b.Y[i];
    var fw = dx * Math.cos(b.H[i]) + dy * Math.sin(b.H[i]);
    return fw < -1.2 && Math.abs(angd(o.H[i], b.H[i])) < 0.7 && o.V[i] > b.V[i];
  }
  var YIELD_MIN = 0.62;                                       // 譲るときに落とす速さの下限(これより遅くはしない)
  // sv の手前で need 秒ぶん遅らせる(近くに譲る区間があれば、まとめて強める)
  function addYield(b, sv, need) {
    var vb = Math.max(9, vlimAt(b, Math.max(0, sv - 15))), Lz = clamp(need * 80, 26, 60), add = need * vb / Lz;
    for (var j = 0; j < b.slow.length; j++) {
      var z = b.slow[j];
      if (z.kind === "yield" && sv - Lz < z.s1 + 6 && sv + 2 > z.s0 - 6) {
        z.s0 = Math.min(z.s0, sv - Lz); z.s1 = Math.max(z.s1, sv + 2);
        z.f = Math.max(YIELD_MIN, 1 / (1 / z.f + add));
        return;
      }
    }
    b.slow.push({ s0: sv - Lz, s1: sv + 2, f: Math.max(YIELD_MIN, 1 / (1 + add)), kind: "yield" });
  }
  // 1マークの手前(x=128)を通る時刻と、そのときの道のり
  var X_GATE = 128;
  function gateOf(b) {
    for (var i = Math.max(1, Math.round((b.st - T0) / DT)); i < NF; i++) {
      if (b.X[i] >= X_GATE && b.Y[i] > -2 && b.S[i] < b.P.sStart + 6) {
        var f = (X_GATE - b.X[i - 1]) / ((b.X[i] - b.X[i - 1]) || 1);
        return { t: T0 + (i - 1 + f) * DT, s: b.S[i - 1] + (b.S[i] - b.S[i - 1]) * f };
      }
      if (b.S[i] > b.P.sStart + 6) break;
    }
    return null;
  }
  // この艇が1マークの手前で後ろにいるべき艇(戦法の上で、先に回らせる艇)
  function mustFollow(b, boats) {
    var out = [];
    if ((b.role === "sashi" || b.role === "mark") && b.ref) out.push(b.ref);
    if (b.role === "makurizashi" && b.under) out.push(b.under);
    boats.forEach(function (x) {
      if (x === b) return;
      if (x.role === "makurizashi" && x.over.indexOf(b) >= 0) out.push(x);
      if ((x.role === "makuri" || x.role === "nidan") && !x.fail && b.course < x.course &&
          ((x.ref === b && b.role !== "hari") || b.squeezed)) out.push(x);
    });
    return out;
  }
  // 決めた順に時間を決める。後の艇が譲る。後ろから突っ込まれる形になったら、順番の入れ替えを返す
  function timing(order, noSwap) {
    var planned = [], boats = order.slice();
    for (var q = 0; q < order.length; q++) {
      var b = order[q], mf = mustFollow(b, boats).filter(function (o) { return planned.indexOf(o) >= 0; });
      b.slow = b.baseSlow.slice();
      for (var it = 0; it < 40; it++) {
        integrate(b, planned);
        var cf = firstConflict(b, planned);
        if (cf) {
          if (!noSwap && rearEnd(b, cf)) return { first: b, then: cf.o };
          addYield(b, b.S[cf.i], clearTime(b, cf));
          continue;
        }
        var gb = gateOf(b), need = 0;
        if (gb) mf.forEach(function (o) { var go = gateOf(o); if (go) need = Math.max(need, go.t + 0.1 - gb.t); });
        if (need <= 0.005) break;
        addYield(b, gb.s, need + 0.02);
      }
      planned.push(b);
    }
    return null;
  }

  // ---- 優先する順番: 前を横切る艇・捲る艇・先に回る艇が先。差す艇・ついて行く艇・外を回す艇は後(譲る)
  function priorityOrder(boats, byC, swaps) {
    var edges = [];
    function e(a, b) { if (a && b && a !== b) edges.push([a, b]); }
    boats.forEach(function (x) {
      if ((x.role === "makuri" || x.role === "nidan") && !x.fail) boats.forEach(function (o) { if (o.course < x.course) e(x, o); });
      if (x.role === "nidan" && x.ref) e(x, x.ref);
      if ((x.role === "makuri" || x.role === "nidan") && x.fail && byC[1]) e(byC[1], x);
      if (x.role === "sashi") {
        if (x.ref) e(x.ref, x);
        boats.forEach(function (o) { if (o.course < x.course && o.role !== "sashi" && o.role !== "makurizashi") e(o, x); });
      }
      if (x.role === "makurizashi") { if (x.under) e(x.under, x); x.over.forEach(function (o) { e(x, o); }); }
      if (x.role === "mark" && x.ref) e(x.ref, x);
      if (x.role === "soto" || x.role === "zen") boats.forEach(function (o) { if (o.course < x.course && !o.squeezed && o.role !== "makurizashi") e(o, x); });
    });
    (swaps || []).forEach(function (s) {                                   // 後ろから突っ込む形になった組は、前にいる艇を先に(戦法の決まりより優先)
      edges = edges.filter(function (ed) { return !(ed[0] === s.then && ed[1] === s.first); });
      e(s.first, s.then);
    });
    var left = boats.slice(), out = [];
    while (left.length) {
      var free = left.filter(function (b) { return !edges.some(function (ed) { return ed[1] === b && left.indexOf(ed[0]) >= 0 && ed[0] !== b; }); });
      if (!free.length) free = left.slice();                                  // 決まりが食い違うときは、着く順で
      free.sort(function (a, b) { return (a.tArr - b.tArr) || (a.course - b.course); });
      out.push(free[0]); left.splice(left.indexOf(free[0]), 1);
    }
    return out;
  }

  // ---- 戦法ごとの減速(差し構え・待ち・残す・ついて行く)と、捲られた艇が引き波で沈む分
  function roleSlows(b, boats) {
    var P = b.P, s0 = P.sStart, tl = P.sEnd - P.sStart, z = [];
    if (b.role === "sashi") z.push({ s0: s0 - 40, s1: s0 - 4, f: b.squeezed ? 0.93 : 0.955 });
    if (b.wait) z.push({ s0: s0 - 45, s1: s0 - 4, f: 0.95 - 0.04 * b.wait });
    if (b.role === "nokoshi") z.push({ s0: s0 - 30, s1: s0, f: 0.95 });
    if (b.role === "mark") z.push({ s0: s0 - 40, s1: s0 - 6, f: 0.975 });
    // 減速せずに回って流れた艇(全速の1コース・張った1コース・張られた艇)は、膨らんだぶん出口で失速する
    var flow = (b.fail ? 0.85 : b.role === "hari" ? 0.86 : b.role === "zensoku" ? 0.9 : b.flowOut ? 0.87 : b.role === "nigeHari" ? 0.96 : 1) - (b.flowExtra || 0);
    if (flow < 1) z.push({ s0: s0 + tl * 0.35, s1: P.sEnd + 14, f: Math.max(0.7, flow), kind: "flow" });
    b.sunk = 0;
    boats.forEach(function (a) {                                              // 前に出て捲った艇の引き波
      if ((a.role !== "makuri" && a.role !== "nidan") || a.fail || a === b || b.course > a.course) return;
      var victim = a.ref === b || (b.squeezed && b.course < a.course) || (a.role === "nidan" && a.ref === b);
      if (!victim) return;
      var f = a.ref === b ? 0.85 : 0.9;
      z.push({ s0: s0 + tl * 0.25, s1: s0 + tl * 0.95, f: f, kind: "wake" });
      b.sunk = Math.max(b.sunk, 1 - f);
    });
    return z;
  }

  // ---- 引き波: 少し前に他艇が通った跡。左回りの旋回では外側に強い波が残り、内側は弱い。真後ろは泡で進みにくい
  function headCache(boats) {                    // 向きの cos・sin(引き波の計算で何度も使う)
    boats.forEach(function (a) { if (!a.HC) { a.HC = new Float32Array(NF); a.HS = new Float32Array(NF); } for (var j = 0; j < NF; j++) { a.HC[j] = Math.cos(a.H[j]); a.HS[j] = Math.sin(a.H[j]); } });
  }
  var COS_CROSS = Math.cos(0.26), LAGS = [];
  for (var lg = 9; lg <= 96; lg += 9) {                       // 引き波の時間ごとの広がり・弱まり(先に計算しておく)
    var tu = lg * DT;
    LAGS.push({ lag: lg, tau: tu, spread: 0.5 + 2.2 * tu, decay: Math.exp(-tu / 1.1), near: tu < 0.7 ? 0.45 * Math.exp(-tu / 0.45) : 0 });
  }
  function wakeExposure(b, boats, cached) {
    var W = b.WK, iS = Math.max(1, Math.round((b.st + 0.8 - T0) / DT)), iE = Math.min(NF - 1, Math.round((b.done + 1.5 - T0) / DT));
    W.fill(0);
    if (!cached) headCache(boats);
    for (var i = iS; i <= iE; i++) {
      var hbc = b.HC[i], hbs = b.HS[i], w = 0;
      for (var q = 0; q < boats.length; q++) {
        var a = boats[q];
        if (a === b) continue;
        var ddx = a.X[i] - b.X[i], ddy = a.Y[i] - b.Y[i];
        if (ddx * ddx + ddy * ddy > 1600) continue;
        for (var k = 0; k < LAGS.length; k++) {
          var L = LAGS[k], j = i - L.lag;
          if (j < 1 || T0 + j * DT < a.st + 0.2) break;
          var hx = a.HC[j], hy = a.HS[j], dx = b.X[i] - a.X[j], dy = b.Y[i] - a.Y[j];
          var fw = dx * hx + dy * hy;
          if (fw > 2.2 || fw < -2.2) continue;
          var lt = -dx * hy + dy * hx, spread = L.spread, decay = L.decay;
          var turn = clamp(Math.abs(a.H[j] - a.H[j - 1]) / DT / 0.7, 0, 1);
          var outer = (0.3 + 0.7 * turn) * decay, inner = (0.3 - 0.15 * turn) * decay, cr = hbc * hx + hbs * hy < COS_CROSS ? 1 : 0.5, ww = 0;
          if (Math.abs(lt - spread) < 1.0) ww += outer * (1 - Math.abs(lt - spread));
          if (Math.abs(lt + spread) < 1.0) ww += inner * (1 - Math.abs(lt + spread));
          if (L.near && Math.abs(lt) < Math.max(0.4, spread - 1.0)) ww += L.near;
          w += ww * cr;
        }
      }
      W[i] = Math.min(1.5, w);
    }
  }
  // 引き波を受けた区間で速度を落とす(区間ごとに、受けた強さに応じて)
  function wakeDips(boats) {
    headCache(boats);
    boats.forEach(function (b) {
      wakeExposure(b, boats, true);
      b.wakeSlow = [];
      var W = b.WK, i = 0;
      while (i < NF) {
        if (W[i] < 0.3) { i++; continue; }
        var i0 = i, pk = 0;
        while (i < NF && W[i] >= 0.15) { pk = Math.max(pk, W[i]); i++; }
        if (b.S[i - 1] - b.S[i0] > 1.5) b.wakeSlow.push({ s0: b.S[i0], s1: b.S[i - 1], f: 1 - Math.min(0.3, 0.2 * pk), kind: "wake", pk: pk });
      }
    });
  }

  // 軌跡をならして(約0.1秒の幅)、向きは実際の進み方から出す
  function smoothTrack(b) {
    var N = NF, X = b.X, Y = b.Y, sx = new Float32Array(N), sy = new Float32Array(N), K = [], R = 9, sig = 4, i, j, w, sum;
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
      hh = prev + angd(hh, prev);
      H[i] = hh; prev = hh;
    }
    b.X = sx; b.Y = sy; b.H = H;
  }

  // ======================================================================
  // 位置関係: コースに沿った同じ地点(s)を、どちらが先に・どちら側(内外)を通ったか
  // ======================================================================
  var G0 = 70, GS = 0.5, NG = 360;                  // s = 70〜250
  function gridOf(b, iEnd) {
    var T = new Float32Array(NG).fill(NaN), Lg = new Float32Array(NG).fill(NaN), gi = 0;
    var i0 = Math.max(1, Math.round((b.st - T0) / DT) + 1);
    for (var i = i0; i <= iEnd && gi < NG; i++) {
      var s0 = b.CS[i - 1], s1 = b.CS[i];
      while (gi < NG && G0 + gi * GS <= s1) {
        var sg = G0 + gi * GS;
        if (sg >= s0) { var f = s1 > s0 ? (sg - s0) / (s1 - s0) : 0; T[gi] = T0 + (i - 1 + f) * DT; Lg[gi] = b.CL[i - 1] + (b.CL[i] - b.CL[i - 1]) * f; }
        gi++;
      }
    }
    b.Tg = T; b.Lg = Lg;
  }
  function gIdx(s) { return clamp(Math.round((s - G0) / GS), 0, NG - 1); }
  var S_GATE = 125;
  // X から見た Y との関係(同じ地点を通った時刻と、内外)
  function pairRel(X, Y, sLast) {
    var r = { pass: null, crossFront: null, crossBehind: null, gateAhead: false, endAhead: false, dTend: 0, overAt: false };
    var prevT = null, prevL = null, g, gA = gIdx(72), gB = gIdx(sLast), gGate = gIdx(S_GATE);
    for (g = gA; g <= gB; g++) {
      var tx = X.Tg[g], ty = Y.Tg[g], lx = X.Lg[g], ly = Y.Lg[g];
      if (isNaN(tx) || isNaN(ty)) { prevT = prevL = null; continue; }
      var dT = tx - ty, dL = lx - ly, sg = G0 + g * GS;
      if (prevT != null) {
        if (prevT > 0.02 && dT <= 0.02 && sg >= 115) r.pass = { s: sg, g: g, inside: dL < 0 };            // 後ろから前へ(抜いた)。どちら側か
        if (prevL > 0 && dL <= 0 && sg <= 185) {                                                       // 外から内へ線を横切った
          if (dT < -0.1) r.crossFront = r.crossFront || { s: sg, g: g, dT: dT };
          else if (dT > 0.1 && sg >= 115) r.crossBehind = r.crossBehind || { s: sg, g: g, dT: dT };
        }
        if (dT > 0.02 && prevT <= 0.02 && r.pass) r.pass = null;                                      // 抜き返された
      }
      prevT = dT; prevL = dL;
    }
    r.gateDT = 0;
    if (!isNaN(X.Tg[gGate]) && !isNaN(Y.Tg[gGate])) { r.gateDT = X.Tg[gGate] - Y.Tg[gGate]; r.gateAhead = r.gateDT < -0.03; }
    if (!isNaN(X.Tg[gB]) && !isNaN(Y.Tg[gB])) { r.dTend = X.Tg[gB] - Y.Tg[gB]; r.endAhead = r.dTend < 0; }
    else r.endAhead = !isNaN(X.Tg[gB]) && isNaN(Y.Tg[gB]);
    var gm = gIdx(BUOY.x + R0 * Math.PI * 0.4);                 // 旋回の中ほど(ブイの横)で、外を回りながら前にいたか
    r.overAt = !isNaN(X.Tg[gm]) && !isNaN(Y.Tg[gm]) && X.Tg[gm] < Y.Tg[gm] - 0.05 && X.Lg[gm] > Y.Lg[gm];
    return r;
  }
  function relations(boats, iEnd) {
    boats.forEach(function (b) { gridOf(b, iEnd); });
    // 全艇が通った一番先の地点まで比べる
    var sLast = Math.min.apply(null, boats.map(function (b) { for (var g = NG - 1; g >= 0; g--) if (!isNaN(b.Tg[g])) return G0 + g * GS; return G0; }));
    sLast = clamp(sLast, 170, 248);
    var rel = { sLast: sLast };
    boats.forEach(function (X) { boats.forEach(function (Y) { if (X !== Y) rel[X.course + "-" + Y.course] = pairRel(X, Y, sLast); }); });
    return rel;
  }

  // ---- 走らせた結果から、各艇が実際にどう回ったかを決める(吹き出しと、決着パターンとの一致の確認に使う)
  //      1マークの手前で前にいた内の艇を、どちら側から抜いたか。内から抜けば差し、外から抜けば捲り。
  //      内から抜く前に、別の内の艇の前を横切っていれば(捲っていれば)まくり差し。
  //      内の艇より前に出たまま、その外を回って先に出ていれば捲り。
  function labels(boats, rel, iEnd) {
    var out = {}, gL = gIdx(rel.sLast);
    var order = boats.slice().sort(function (a, b) { var ta = a.Tg[gL], tb = b.Tg[gL]; if (isNaN(ta)) ta = 99; if (isNaN(tb)) tb = 99; return (ta - tb) || (b.CS[iEnd] - a.CS[iEnd]); });
    boats.forEach(function (X) {
      var c = X.course, L = { kind: null, inOf: [], outOf: [], over: [], behind: [], pos: order.indexOf(X) + 1 };
      var inner = boats.filter(function (Y) { return Y.course < c; }), aheadAll = inner.length > 0, inOut = [];
      inner.forEach(function (Y) {
        var r = rel[c + "-" + Y.course];
        if (!r.gateAhead) aheadAll = false;
        if (r.pass && r.endAhead && !r.gateAhead) (r.pass.inside ? L.inOf : L.outOf).push(Y);
        else if (r.endAhead && (r.crossFront || r.overAt)) L.over.push(Y);          // 前に出たまま、外を回るか前を横切った(捲った)
        if (r.crossBehind) L.behind.push(Y);
      });
      // 外から捲ってきた艇の内を差した(内から抜いた)
      boats.forEach(function (Y) {
        if (Y.course <= c) return;
        var r = rel[c + "-" + Y.course];
        if (r.pass && r.pass.inside && r.endAhead && !r.gateAhead && (Y.role === "makuri" || Y.role === "nidan")) inOut.push(Y);
      });
      var overAll = L.outOf.concat(L.over.filter(function (y) { return L.outOf.indexOf(y) < 0; }));
      // 決まり手の言葉は、すぐ左(内)の艇との関係で決める(差し: 左の艇の内を抜いた。捲り: 左の艇の外を抜いた。
      // まくり差し: 左の艇の外を抜き、さらにその内の艇の内を抜いた)
      var leftB = boats.filter(function (Y) { return Y.course === c - 1; })[0];
      var leftIn = leftB && L.inOf.indexOf(leftB) >= 0, leftOut = leftB && overAll.indexOf(leftB) >= 0;
      if (c === 1) L.kind = L.pos === 1 ? "nige" : null;
      else if (leftIn) L.kind = "sashi";
      else if (leftOut && L.inOf.some(function (y) { return y.course < c - 1; })) L.kind = c >= 3 ? "makurizashi" : "sashi";
      else if (leftOut && (L.outOf.length || aheadAll)) L.kind = "makuri";
      else if (L.inOf.length) {
        // 内から抜いた艇より外(自分との間)の艇を、前を横切るか外から抜いていれば、まくり差し(3〜6コースだけ)
        var yin = Math.min.apply(null, L.inOf.map(function (y) { return y.course; }));
        L.kind = c >= 3 && overAll.some(function (y) { return y.course > yin && y.course < c; }) ? "makurizashi" : "sashi";
      }
      else if (L.outOf.length || (aheadAll && L.over.length)) L.kind = "makuri";
      else if (inOut.length) L.kind = "sashi";
      else if (L.behind.length) L.kind = "sashiTry";
      L.inOf = L.inOf.concat(inOut);
      L.overAll = overAll;
      out[c] = L;
    });
    return { byCourse: out, order: order };
  }
  var KIND_NAME = { nige: "逃げ", sashi: "差し", makuri: "捲り", makurizashi: "捲り差し" };

  function finishTracks(boats) {
    boats.forEach(function (b) {
      smoothTrack(b);
      var CS = new Float32Array(NF), CL = new Float32Array(NF);
      for (var i = 0; i < NF; i++) { var c = cframe(b.X[i], b.Y[i]); CS[i] = c[0]; CL[i] = c[1]; }
      for (i = 1; i < NF; i++) if (CS[i] < CS[i - 1]) CS[i] = CS[i - 1];   // 前にしか進まない
      b.CS = CS; b.CL = CL;
      var md = 1e9;
      for (i = Math.round((b.st - T0) / DT); i < NF; i += 2) md = Math.min(md, Math.hypot(b.X[i] - BUOY.x, b.Y[i] - BUOY.y));
      b.minBuoy = md;
    });
    return Math.min(T_MAX - 0.1, Math.max.apply(null, boats.map(function (b) { return b.done; })) + 2.0);
  }

  // ======================================================================
  // 全体: 戦法を決め、ラインと時間を作り、決着パターンどおりの先頭・決まり手になるまで調整する
  // ======================================================================
  var WANT = { "逃げ": "nige", "差し": "sashi", "捲り": "makuri", "捲り差し": "makurizashi" };
  // 決着パターン(先頭と決まり手)を守れなかったときは、着順に合わせる手直しなしで作り直し、守れた方を使う
  function plan(entries, sc, vkim, opt) {
    opt = opt || {};
    var P = plan1(entries, sc, vkim, opt);
    var bad = function (Q) { return !Q.labels || Q.labels.order[0] !== Q.winner || Q.labels.byCourse[Q.winner.course].kind !== Q.want; };
    if (bad(P) && (opt.order || (sc && sc.order))) {
      var sc2 = Object.assign({}, sc, { order: null }), opt2 = Object.assign({}, opt, { order: null });
      var P2 = plan1(entries, sc2, vkim, opt2);
      if (!bad(P2)) return P2;
    }
    return P;
  }
  function plan1(entries, sc, vkim, opt) {
    var boats = prepare(entries), byC = {};
    boats.forEach(function (b) { byC[b.course] = b; });
    var dec = decide(boats, sc, vkim, opt);
    boats.forEach(function (b) { b.adj = { dz: 0, yo: 0 }; b.extra = []; });
    var winner = boats.filter(function (b) { return b.win; })[0] || boats[0];
    var want = WANT[dec.kim] || "nige", swaps = [], tEnd = 0, iEnd = 0, rel = null, lab = null, outer = 0, guard = 0, lastOuter = -1;
    function drift(b, k) { if (b && !b.win) { b.adj.dz = Math.min(3.2, b.adj.dz + 0.8 * k); b.adj.yo = Math.max(-4.8, b.adj.yo - 1.2 * k); } }
    function hold(b, f) {
      if (!b || b.win || !b.P) return;
      var z = b.extra.filter(function (x) { return x.kind === "adj"; })[0];
      if (z) z.f = Math.max(0.86, z.f * (1 - (1 - f) * 0.5));
      else b.extra.push({ s0: b.P.sStart - 34, s1: b.P.sStart + 6, f: f, kind: "adj" });
    }
    for (outer = 0; outer < 7 && guard < 40; outer++, guard++) {
      boats.forEach(function (b) { b.vmax = b.vmax0 + b.bias.vmax; b.alat = b.alat0 * b.bias.alat; runTable(b); });
      arrivals(boats);
      geometry(boats, byC);
      boats.forEach(function (b) { b.wakeSlow = []; b.baseSlow = roleSlows(b, boats).concat(b.extra); });
      if (outer !== lastOuter) { swaps = []; lastOuter = outer; }          // 入れ替えは、ラインを作り直すたびに決め直す
      var order = priorityOrder(boats, byC, swaps), full = swaps.length >= 8;
      var sw = timing(order, full);
      if (sw) { swaps.push(sw); outer--; continue; }
      wakeDips(boats);
      boats.forEach(function (b) { b.baseSlow = b.baseSlow.concat(b.wakeSlow); });
      sw = timing(order, full);
      if (sw) { swaps.push(sw); outer--; continue; }
      tEnd = finishTracks(boats);
      iEnd = Math.round((tEnd - T0) / DT);
      rel = relations(boats, iEnd);
      lab = labels(boats, rel, iEnd);
      var lead = lab.order[0], kind = lab.byCourse[winner.course].kind;
      if (lead === winner && (kind === want || outer >= 5)) break;
      if (outer >= 6) break;
      // 調整: 勝つ艇を少し強く、戦法の相手をそれらしく(差しなら相手がもう少し流れる、まくり差しなら横切られる艇が待つ、捲りなら捲られる艇が待つ)
      if (lead === winner && want === "makurizashi" && kind === "makuri" && winner.under && !winner.under.win) {
        // まくり差しのはずが、早く着きすぎて全部の外を回った: 勝つ艇は差し場を待ち、差される艇(捲りに行った艇)が先に1マークへ
        winner.wait = Math.min(1.2, (winner.wait || 0) + 0.4);
        winner.under.bias.vmax = Math.min(1.4, winner.under.bias.vmax + 0.3);
        winner.over.forEach(function (o) { hold(o, 0.94); });
        continue;
      }
      if (lead !== winner || kind !== want) {
        winner.bias.vmax = Math.min(1.4, winner.bias.vmax + 0.15);
        winner.bias.alat = Math.min(1.2, winner.bias.alat * 1.025);
        var tgt = want === "sashi" ? (winner.ref || byC[1]) : want === "makurizashi" ? winner.under : null;
        if (tgt && lead === tgt && !tgt.win) tgt.flowExtra = Math.min(0.14, (tgt.flowExtra || 0) + 0.035);   // 差される艇がもっと流れる
        if (want === "sashi") { drift(winner.ref || byC[1], 1); if (kind === "makuri") winner.adj.dz -= 0.5; }
        else if (want === "makurizashi") {
          drift(winner.under, 0.8);
          if (kind !== "makurizashi") winner.over.forEach(function (o) { hold(o, 0.92); });
          if (kind === "makuri") winner.adj.dz -= 0.5;
        } else if (want === "makuri") boats.forEach(function (o) { if (o.course < winner.course) hold(o, 0.95); });
        else if (want === "nige" && lead !== winner) hold(lead, 0.95);
        if (lead === byC[1] && (want === "sashi" || want === "makurizashi") && byC[1].role === "nokoshi") byC[1].role = "hari";
        if (lead === byC[1] && (want === "sashi" || want === "makurizashi")) byC[1].flowExtra = Math.min(0.14, (byC[1].flowExtra || 0) + 0.035);
        if (lead !== winner && lead !== winner.ref && lead !== winner.under && winner.over.indexOf(lead) < 0 && want !== "nige") {
          if (lead.role === "makuri" || lead.role === "nidan" || lead.role === "mark" || lead.role === "zen" || lead.role === "soto") drift(lead, 1);
          else hold(lead, 0.95);
        }
      }
    }
    // 2着以下の並び: 着順のモデル(model.js の orderFor)が出した並びになるよう、前に出したい艇を少し速く・小回りに、
    // 前にいすぎる艇を1マークの手前で少し待たせる(先頭と決まり手は変えない。合わなければ一番近かった形に戻す)
    var tgt = opt.order || (sc && sc.order);
    if (tgt && tgt.length === 6 && lab && tgt[0] === winner.course) {
      var kindOk = function () { return lab.order[0] === winner && lab.byCourse[winner.course].kind === want; };
      var miss = function () {                                             // 並びの食い違い(上の着ほど重く数える)
        var cur = lab.order.map(function (b) { return b.course; }), m = 0;
        for (var a = 1; a < 6; a++) for (var c2 = a + 1; c2 < 6; c2++) if (cur.indexOf(tgt[a]) > cur.indexOf(tgt[c2])) m += 6 - a;
        return m + (kindOk() ? 0 : 1000);
      };
      var save = function () {
        var st = boats.map(function (b) {
          return { b: b, vmax: b.bias.vmax, alat: b.bias.alat, dz: b.adj.dz, yo: b.adj.yo, fx: b.flowExtra, role: b.role, ref: b.ref, wait: b.wait, sinkZ: b.sinkZ,
                   extra: b.extra.map(function (z) { return Object.assign({}, z); }) };
        });
        st.res = { lab: lab, rel: rel, tEnd: tEnd, iEnd: iEnd };              // その形で走らせた結果(戻したときに並びも戻す)
        return st;
      };
      var restore = function (st) {
        st.forEach(function (x) { var b = x.b; b.bias.vmax = x.vmax; b.bias.alat = x.alat; b.adj.dz = x.dz; b.adj.yo = x.yo; b.flowExtra = x.fx;
                                  b.extra = x.extra.map(function (z) { return Object.assign({}, z); });   // 保存した形は書きかえない
                                  b.role = x.role; b.ref = x.ref; b.wait = x.wait; b.sinkZ = x.sinkZ; });
        if (st.res) { lab = st.res.lab; rel = st.res.rel; tEnd = st.res.tEnd; iEnd = st.res.iEnd; }
      };
      var runOnce = function (fast) {
        // fast: 引き波は前回の計算の分をそのまま使う(途中の調整を軽くする。最後に1回、引き波も計算し直す)
        var sws = [], prevWake = boats.map(function (b) { return b.wakeSlow || []; });
        for (var g2 = 0; g2 < 12; g2++) {
          boats.forEach(function (b) { b.vmax = b.vmax0 + b.bias.vmax; b.alat = b.alat0 * b.bias.alat; runTable(b); });
          arrivals(boats);
          geometry(boats, byC);
          boats.forEach(function (b, bi) { b.wakeSlow = fast ? prevWake[bi] : []; b.baseSlow = roleSlows(b, boats).concat(b.extra).concat(fast ? b.wakeSlow : []); });
          var od = priorityOrder(boats, byC, sws), fl = sws.length >= 8, s2 = timing(od, fl);
          if (s2) { sws.push(s2); continue; }
          if (fast) break;
          wakeDips(boats);
          boats.forEach(function (b) { b.baseSlow = b.baseSlow.concat(b.wakeSlow); });
          s2 = timing(od, fl);
          if (s2) { sws.push(s2); continue; }
          break;
        }
        tEnd = finishTracks(boats);
        iEnd = Math.round((tEnd - T0) / DT);
        rel = relations(boats, iEnd);
        lab = labels(boats, rel, iEnd);
      };
      var best = miss(), bestSt = save(), st0 = bestSt, moved = false, tries = {}, fullOk = false, noBoost = {};
      for (var it = 0; it < (opt.orderIters || 10) && best > 0 && best < 1000; it++) {
        var cur = lab.order.map(function (b) { return b.course; }), k2 = -1;
        for (var q = 1; q < 5; q++) if (cur[q] !== tgt[q]) { k2 = q; break; }
        if (k2 < 0) break;
        var up = byC[tgt[k2]], dn = byC[cur[k2]];
        if (!up || !dn || up.win || dn.win) break;
        var key = up.course + ">" + dn.course, ahead = byC[tgt[k2 - 1]];
        tries[key] = (tries[key] || 0) + 1;
        if (tries[key] === 1) {
          // 1回目は動き方を変える: 捲られた1コースは張って流れる、外を回す艇は前の艇について行く、差し・まくり差しの艇は待つ
          if (dn.course === 1 && dn.role === "nokoshi" && up.course > 1) dn.role = "hari";
          if ((up.role === "soto" || up.role === "zen" || (up.role === "sashi" && dn.course < up.course)) && k2 <= 3 && ahead && ahead.course < up.course && !ahead.win) { up.role = "mark"; up.ref = ahead; }
          if (dn.role === "sashi" || dn.role === "makurizashi" || dn.role === "mark") dn.wait = Math.min(1.5, (dn.wait || 0) + 0.6);
          if (up.wait) up.wait = Math.max(0, up.wait - 0.4);                  // 前に出したい艇は、待ちを短く
          // 捲られて大きく後ろへ下がる艇(見立てで2つ以上後ろ)は、最初から引き波に沈む形にする
          if ((want === "makuri" || want === "makurizashi") && dn.course < winner.course && tgt.indexOf(dn.course) - k2 >= 2 && !dn.sinkZ && dn.P) {
            dn.sinkZ = true;
            dn.extra.push({ s0: dn.P.sStart + (dn.P.sEnd - dn.P.sStart) * 0.25, s1: dn.P.sEnd + 12, f: 0.86, kind: "wake" });
          }
        }
        if (tries[key] === 2 && ahead && (ahead.win || ahead.course < up.course) && ["sashi", "makurizashi", "soto", "zen"].indexOf(up.role) >= 0) {
          up.role = "mark"; up.ref = ahead; up.wait = 0;                    // 2回目も抜けないときは、すぐ前の着の艇について回る(差し続く・外を続く)
        }
        var soft = !!noBoost[key];                                          // 前の艇を抜いて先頭が崩れた組は、後ろの艇を下げるだけにする
        if (tries[key] >= 2 && !dn.sinkZ && dn.P) {                        // 抜けないときは、前の艇が引き波に沈む形にする(出口で失速)
          dn.sinkZ = true;
          dn.extra.push({ s0: dn.P.sStart + (dn.P.sEnd - dn.P.sStart) * 0.3, s1: dn.P.sEnd + 10, f: 0.87, kind: "wake" });
        }
        if (tries[key] >= 3) { dn.flowExtra = Math.min(0.2, (dn.flowExtra || 0) + 0.04); hold(dn, 0.93); }   // 何度やっても抜けないときは、前の艇をもっと下げる
        if (!soft) {
          var stepV = ahead && !ahead.win ? 0.22 : 0.35;                   // すぐ前の着の艇まで抜いてしまわないよう、少しずつ
          up.bias.vmax = Math.min(1.4, up.bias.vmax + stepV);
          up.bias.alat = Math.min(1.15, up.bias.alat * 1.04);
        } else up.adj.dz = Math.max(-1.2, up.adj.dz - 0.3);
        if ((up.role === "soto" || up.role === "zen" || up.role === "mark") && k2 <= 2) up.adj.dz = Math.max(-1.2, up.adj.dz - 0.5);   // 外を回す艇は内寄りに
        dn.flowExtra = Math.min(0.18, (dn.flowExtra || 0) + (soft ? 0.06 : 0.045));   // 出口で流れる(引き波に沈む)
        hold(dn, soft ? 0.94 : 0.96);
        if (dn.course !== 1) drift(dn, soft ? 0.6 : 0.4);
        runOnce(true);
        moved = true;
        var m2 = miss();
        if (m2 < best) { runOnce(false); m2 = miss(); }                    // 良くなったら、引き波も含めて確かめる
        if (m2 < best) { best = m2; bestSt = save(); fullOk = true; }
        else if (m2 >= 1000) { restore(bestSt); noBoost[key] = true; fullOk = false; }   // 先頭・決まり手が崩れたら戻して、別のやり方で
      }
      if (moved && (!fullOk || miss() > best)) { restore(bestSt); runOnce(false); if (miss() >= 1000) { restore(st0); runOnce(false); } }
    }
    // 引き波の強さ(映像のしぶきと「沈む」に使う)
    headCache(boats);
    boats.forEach(function (b) {
      wakeExposure(b, boats, true);
      var pk = 0, ip = null;
      b.wakeSlow.forEach(function (z) { if (z.pk > pk) { pk = z.pk; ip = z.s0; } });
      b.sinkI = null;
      var loss = Math.max(b.sunk || 0, pk >= 0.5 ? 0.2 * pk : 0);
      if (loss >= 0.12) {
        var s0 = ip != null && pk * 0.2 >= (b.sunk || 0) ? ip : b.P.sStart + (b.P.sEnd - b.P.sStart) * 0.45;
        for (var i = 0; i < NF; i++) if (b.S[i] >= s0 && T0 + i * DT > b.st) { b.sinkI = i; break; }
      }
      b.loss = loss;
    });
    var P = { boats: boats, winner: winner, sc: sc, kim: dec.kim, want: want, tEnd: tEnd, total: tEnd - T0, N: NF, labels: lab, rel: rel, iters: outer, swaps: swaps.length,
              order: lab ? lab.order.map(function (b) { return b.course; }) : null, target: tgt || null };
    P.cam = camera(boats, P);
    P.events = events(boats, rel, lab, P);
    return P;
  }

  function idxAtS(b, sv) { for (var i = 0; i < NF; i++) if (T0 + i * DT >= b.st && b.S[i] >= sv) return i; return null; }
  function idxAtG(b, g) { var t = b.Tg[g]; return isNaN(t) ? null : clamp(Math.round((t - T0) / DT), 0, NF - 1); }

  // ---- 展開の重要ポイント(吹き出し)。走らせた結果の位置関係から作る。多くても4つ、時間が重ならないように選ぶ
  function events(boats, rel, lab, P) {
    var ev = [], L = lab.byCourse, gTurn = gIdx(BUOY.x + R0 * Math.PI * 0.35), gIn = gIdx(128);
    function add(b, i, text, pr) { if (i != null) ev.push({ i: i, b: b, text: text, pr: pr }); }
    boats.forEach(function (b) {
      var c = b.course, l = L[c];
      // 絞る: 内の艇の前へ3m以上寄せた
      var moved = b.lane - b.sp.yi;
      if (b.sp.sq && moved >= 3) {
        var xm = 14 + (Math.min(95, b.sp.xin - 12) - 14) * 0.45;
        add(b, idxAtS(b, xm), c + "コース 絞る", b.win ? 2.2 : 2.6);
      }
      if (c === 1) {
        if ((b.role === "hari" || b.role === "nigeHari") && b.sp.yi - b.lane >= 0.5) add(b, idxAtS(b, b.sp.xin - 22), "1コース 張る", 2.4);
        if (l.kind === "nige" && b.win) add(b, idxAtG(b, gTurn), "1コース 逃げる", 1);
        else if (b.role === "nokoshi" && l.pos <= 3) add(b, idxAtG(b, gTurn), "1コース 小回りで残す", 3.0);
        return;
      }
      var txt = null, pr = 3.2, gi = gTurn;
      if (l.kind === "makurizashi") { txt = "まくり差し"; pr = 2.6; }
      else if (l.kind === "makuri") {
        var twoStep = l.overAll.concat(l.outOf).some(function (o) { return (o.role === "makuri" || o.role === "nidan") && o !== b; }) || b.role === "nidan";
        txt = twoStep ? "二段まくり" : "捲る"; pr = 2.4; gi = gIn;
      } else if (l.kind === "sashi") { txt = "差す"; pr = 2.8; }
      else if ((b.role === "makuri" || b.role === "nidan") && b.fail) { txt = "捲りに行く"; pr = 2.7; gi = gIn; }
      else if (b.role === "mark" && b.ref && L[b.ref.course].kind === "makuri") { txt = "捲りについて行く"; pr = 3.4; }
      // 勝つ艇でない差し・捲りは、実際に内の艇を抜いて順位を2つ以上上げたときだけ出す
      if (txt && !b.win && (l.kind === "sashi" || l.kind === "makuri") && (l.pos > b.course - 2 || !(l.inOf.length || l.outOf.length))) txt = null;
      // 勝つ艇でない艇の戦法の吹き出しは、3着以内に入る艇だけ(後ろの艇が外を回って少し前に出ただけのものは出さない)
      if (txt && !b.win && txt !== "捲りに行く" && l.pos > 3) txt = null;
      if (b.win) {
        // 決着パターンの決まり手と、実際の動きが同じときだけ、その言葉を使う
        if (l.kind === P.want) { txt = { sashi: "差す", makuri: "捲る", makurizashi: "まくり差し" }[P.want] || txt; pr = 1; }
        else txt = null;                                         // 動きが決まり手と食い違うときは、言葉を出さない
      }
      if (txt) add(b, idxAtG(b, gi), c + "コース " + txt, pr);
    });
    // 沈む: 引き波を受けて順位を落とした艇のうち、展開に関わった艇(1コース、または1マークの手前で3番手以内にいた艇)を1つだけ
    var gg = gIdx(S_GATE), gate = boats.slice().sort(function (a, b) { var ta = a.Tg[gg], tb = b.Tg[gg]; return (isNaN(ta) ? 99 : ta) - (isNaN(tb) ? 99 : tb); });
    var sinker = boats.filter(function (b) {
      var gp = gate.indexOf(b) + 1;
      return b.sinkI != null && !b.win && (b.course === 1 ? L[1].pos >= 4 : gp <= 3 && L[b.course].pos >= gp + 2);   // 1コースは4番手以下に下がったとき
    }).sort(function (a, b) { return b.loss - a.loss; })[0];
    if (sinker) add(sinker, sinker.sinkI, sinker.course + "コース 沈む", sinker.course === 1 ? 2.9 : 3.6);
    ev.sort(function (a, b) { return a.pr - b.pr; });
    var out = [];
    ev.forEach(function (e) {
      if (out.length >= 4) return;
      if (out.some(function (o) { return o.b === e.b && o.text === e.text; })) return;
      if (out.every(function (o) { return Math.abs(o.i - e.i) * DT > 0.55 && o.b !== e.b || Math.abs(o.i - e.i) * DT > 1.8; })) out.push(e);
    });
    out.forEach(function (e) { e.t = T0 + e.i * DT; });
    out.sort(function (a, b) { return a.t - b.t; });
    out.forEach(function (e, k) { e.below = k % 2 === 1; });    // 続けて出る吹き出しは上下に分けて重ならないようにする
    return out;
  }

  // ---- カメラ: ドローンが全艇を追うように、位置と画角をなめらかに変える
  function camera(boats, R) {
    var n = Math.round((R.tEnd + 1.6 - T0) / DT), CX = [], CY = [], CW = [];
    for (var i = 0; i < n; i++) {
      var t = T0 + i * DT, j = Math.min(i, NF - 1);
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
    return { x: b.X[i] + (b.X[i + 1] - b.X[i]) * u, y: b.Y[i] + (b.Y[i + 1] - b.Y[i]) * u, h: h, w: (b.H[i + 1] - b.H[i]) / DT, v: b.V[i], wk: b.WK[i] };
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h - r); ctx.arcTo(x + w, y + h, x + w - r, y + h, r); ctx.lineTo(x + r, y + h);
    ctx.arcTo(x, y + h, x, y + h - r, r); ctx.lineTo(x, y + r); ctx.arcTo(x, y, x + r, y, r); ctx.closePath();
  }

  // 吹き出し(艇の上に出して、艇についていく)
  function bubble(ctx, text, b, sx, sy, cw, ch, u, alpha, wantBelow, others, rBoat, memo, placed) {
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
    function clash(p) {                                               // ほかの吹き出しと重なるか
      return placed.some(function (r) { return p[1] < r[0] + r[2] + u && p[1] + w + u > r[0] && p[2] < r[1] + r[3] + u * 0.6 && p[2] + h + u * 0.6 > r[1]; });
    }
    function hits(p) { return others.some(function (o) { return o[0] + rBoat > p[1] && o[0] - rBoat < p[1] + w && o[1] + rBoat > p[2] && o[1] - rBoat < p[2] + h; }); }
    // 一度決めた置き場所は、ほかの艇や吹き出しにかからない限り変えない(ちらつかない)
    if (memo.k != null && fits(at(memo.k)) && !clash(at(memo.k)) && !hits(at(memo.k))) pick = at(memo.k);
    for (var k = 0; k < cands.length && !pick; k++) {
      var p = at(k);
      if (fits(p) && !clash(p) && !hits(p)) { pick = p; memo.k = k; }
    }
    if (!pick && memo.k != null && fits(at(memo.k)) && !clash(at(memo.k))) pick = at(memo.k);
    for (k = 0; k < cands.length && !pick; k++) { var q = at(k); if (fits(q) && !clash(q)) { pick = q; memo.k = k; } }
    if (!pick) { var bl0 = !(sy - h - gap >= u * 11); pick = [bl0, clamp(sx - w / 2, u, cw - w - u), bl0 ? sy + gap : sy - h - gap]; }
    var below = pick[0], bx = pick[1], by = pick[2];
    placed.push([bx, by, w, h]);
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
    // 引き波(水面に残る。旋回の外側を太く白く)
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
        var turn = clamp(Math.abs(c.w) / 0.8, 0, 1);
        ctx.strokeStyle = "rgba(255,255,255," + (0.26 * f).toFixed(3) + ")";
        ctx.lineWidth = 0.9 + i * 0.045;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(c.x, c.y); ctx.stroke();
        ctx.strokeStyle = "rgba(255,255,255," + ((0.4 + 0.25 * turn) * f).toFixed(3) + ")";      // 外側(左回りなら右)の波
        ctx.lineWidth = 0.28 + 0.3 * turn;
        ctx.beginPath(); ctx.moveTo(a.x + ax * d0, a.y + ay * d0); ctx.lineTo(c.x + cxn * d1, c.y + cyn * d1); ctx.stroke();
        ctx.strokeStyle = "rgba(255,255,255," + ((0.4 - 0.2 * turn) * f).toFixed(3) + ")";      // 内側の波
        ctx.lineWidth = 0.28;
        ctx.beginPath(); ctx.moveTo(a.x - ax * d0, a.y - ay * d0); ctx.lineTo(c.x - cxn * d1, c.y - cyn * d1); ctx.stroke();
      }
    });
    // ボートと、旋回中・波を受けたときの水しぶき
    var now = P.boats.map(function (b) { return sample(b, tt); });
    P.boats.forEach(function (b, k) {
      var p = now[k], col = COLORS[b.waku] || COLORS[1];
      var amt = t < P.tEnd + 1 ? Math.max(clamp((Math.abs(p.w) - 0.3) * 1.2, 0, 1), clamp((p.wk || 0) * 1.4, 0, 1)) : 0;
      if (amt > 0) {
        var ox = -Math.sin(p.h), oy = Math.cos(p.h), bx = p.x - Math.cos(p.h) * HULL_L * 0.45, by = p.y - Math.sin(p.h) * HULL_L * 0.45;
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
    var spots = now.map(scr), rBoat = HULL_L * 0.55 * sc + 6, placed = [];
    P.events.forEach(function (e) {
      if (t < e.t - 0.15 || t > e.t + 2.0) { e.k = null; return; }   // 出ていないときは置き場所を忘れる(次に出るとき選び直す)
      var k = P.boats.indexOf(e.b), s2 = spots[k];
      var a = Math.min(sstep(e.t - 0.15, e.t + 0.1, t), 1 - sstep(e.t + 1.7, e.t + 2.0, t));
      bubble(ctx, e.text, e.b, s2[0], s2[1], cw, ch, u, a, e.below, spots.filter(function (_, j) { return j !== k; }), rBoat, e, placed);
    });
    function pill(text, x, y, align, bg, fg, size) {
      ctx.font = "700 " + size + "px " + FONT; ctx.textBaseline = "middle";
      var w = ctx.measureText(text).width + size * 1.1, h = size * 1.7, left = align === "right" ? x - w : x;
      ctx.fillStyle = bg; roundRect(ctx, left, y, w, h, h / 2); ctx.fill();
      ctx.fillStyle = fg; ctx.textAlign = "left"; ctx.fillText(text, left + size * 0.55, y + h / 2 + 1);
    }
    var fs = Math.max(11, u * 2.5);
    pill(opt.title || "1周1マーク", u * 2, u * 2, "left", "rgba(8,26,34,0.72)", "#ffffff", fs);
    var tag = P.sc.label ? P.sc.label + " " + P.sc.course + "コース " + P.sc.kim : P.sc.course + "コース " + P.sc.kim + (P.sc.p != null ? " " + Math.round(P.sc.p) + "%" : "");
    pill(tag, cw - u * 2, u * 2, "right", "#f2cf1d", "#14212b", fs);
    if (t < 0) pill("スタートまで " + (-t).toFixed(1), u * 2, u * 3.2 + fs * 1.7, "left", "rgba(8,26,34,0.72)", "#ffffff", fs * 0.9);
    ctx.font = Math.max(9, u * 1.6) + "px " + FONT; ctx.fillStyle = "rgba(255,255,255,0.8)"; ctx.textAlign = "right"; ctx.textBaseline = "bottom";
    ctx.fillText((opt.brand ? opt.brand + " ・ " : "") + (P.sc.label ? "実際のSTでの再現" : "データに基づくシミュレーション"), cw - u * 2, ch - u * 1.5);
    if (t > P.tEnd - 0.6) {                                       // 最後に、1マークを回ったあとの並び(枠番)を出す
      ctx.globalAlpha = sstep(P.tEnd - 0.6, P.tEnd, t);
      var byCw = {};
      P.boats.forEach(function (b) { byCw[b.course] = b.waku; });
      var ord = (P.order || [P.winner.course]).map(function (c) { return byCw[c]; }).join("-");
      pill("1周1マーク後の並び " + ord, u * 2, ch - u * 2 - fs * 1.9, "left", "rgba(8,26,34,0.8)", "#ffffff", fs * 1.05);
      ctx.globalAlpha = 1;
    }
  }

  function mount(canvas, opt) {
    var ctx = canvas.getContext("2d");
    var P = plan(opt.entries, opt.scen, opt.kimarite, { fixedST: !!opt.fixedST });
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
      setScenario: function (sc, entries, title, fixedST) {
        if (entries) opt.entries = entries;
        if (title) opt.title = title;
        opt.fixedST = !!fixedST;
        opt.scen = sc; P = plan(opt.entries, sc, opt.kimarite, { fixedST: opt.fixedST }); api.replay();
      },
      plan: function () { return P; },
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

  root.Turn1 = { mount: mount, plan: plan, KIND_NAME: KIND_NAME };
})(typeof window !== "undefined" ? window : globalThis);
