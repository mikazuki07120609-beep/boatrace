/* レースページの展開の見立て。出走表と選手のコース別成績(ページに埋め込んだJSON)から計算し、
   直前情報(展示タイム・進入・風)を入れると計算し直す。買い目は出さない。 */
(function () {
  "use strict";
  var el = document.getElementById("race-data");
  if (!el) return;
  var D = JSON.parse(el.textContent);
  var V = D.venue;
  var KIM = ["逃げ", "捲り", "差し", "捲り差し", "抜き", "恵まれ"];
  var SHRINK = 10; // 走数が少ない選手の成績を、場の平均に寄せる強さ
  function $(s) { return document.querySelector(s); }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function fmt(n, d) { return n == null || isNaN(n) ? "—" : Number(n).toFixed(d == null ? 1 : d); }
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

  function analyze() {
    var B = readState();
    var wind = $("#wind") ? $("#wind").value : "none";
    var wspd = parseFloat($("#windspd") ? $("#windspd").value : "0") || 0;
    var strong = wspd >= 4;
    B.forEach(function (b) {
      b.power = b.rate == null ? null : (b.local ? b.rate * 0.7 + b.local * 0.3 : b.rate);
      var cs = (b.cs || {})[String(b.course)] || null;
      b.csNow = cs;
      b.stUse = cs && cs.st != null && cs.n >= 3 ? cs.st : (b.st_all != null ? b.st_all : null);
    });
    var aPow = avg(B.map(function (b) { return b.power; })), aSt = avg(B.map(function (b) { return b.stUse; }));
    var aMo = avg(B.map(function (b) { return b.motor2; })), aEx = avg(B.map(function (b) { return b.ex; }));
    B.forEach(function (b) {
      var base = ((V.place[b.course - 1] || [0])[0] || 0) / 100;
      var fc = 1;
      if (b.csNow && base > 0) {
        var est = (b.csNow.w1 + SHRINK * base) / (b.csNow.n + SHRINK);
        fc = Math.min(3, Math.max(0.3, est / base));
      }
      var f = fc;
      if (b.power != null && aPow != null) f *= Math.pow(1.25, b.power - aPow);
      if (b.stUse != null && aSt != null) f *= Math.pow(1.15, (aSt - b.stUse) / 0.05);
      if (b.motor2 != null && aMo != null) f *= Math.pow(1.06, (b.motor2 - aMo) / 10);
      if (b.ex != null && aEx != null) f *= Math.pow(1.08, (aEx - b.ex) / 0.05);
      b.factor = f; b.base = base;
    });
    var kw = [1, 1, 1, 1, 1, 1], inWind = 1;
    if (strong && wind === "head") { kw[1] *= 1.15; kw[3] *= 1.1; inWind = 0.9; }
    if (strong && wind === "tail") { kw[2] *= 1.1; kw[1] *= 0.9; }
    if (strong && wind === "side") { inWind = 0.95; }
    // 1コースの選手の負け方(差され・捲られ・捲り差され)の傾向。決まりやすい攻め方を少し重くする
    var b1 = B.filter(function (b) { return b.course === 1; })[0], lsW = { "差し": 1, "捲り": 1, "捲り差し": 1 };
    if (b1 && b1.csNow && b1.csNow.ls) {
      var ls = b1.csNow.ls, lt = (ls["差し"] || 0) + (ls["捲り"] || 0) + (ls["捲り差し"] || 0);
      ["差し", "捲り", "捲り差し"].forEach(function (k) { lsW[k] = 0.7 + 0.9 * (((ls[k] || 0) + 4 / 3) / (lt + 4)); });
    }
    var scen = [];
    B.forEach(function (b) {
      var d = kimDist(b);
      d.forEach(function (p, j) {
        if (p <= 0) return;
        var w = b.base * 100 * b.factor * p * kw[j] * (b.course === 1 ? 1 : (lsW[KIM[j]] || 1));
        if (b.course === 1) w *= inWind;
        scen.push({ b: b, kim: KIM[j], w: w });
      });
    });
    var tot = scen.reduce(function (s, x) { return s + x.w; }, 0) || 1;
    scen.forEach(function (s) { s.p = s.w / tot * 100; });
    scen.sort(function (a, b) { return b.p - a.p; });
    B.forEach(function (b) { b.share = scen.filter(function (s) { return s.b === b; }).reduce(function (s, x) { return s + x.p; }, 0); });
    return { B: B, scen: scen, aPow: aPow, aSt: aSt, aMo: aMo, aEx: aEx, wind: wind, wspd: wspd, strong: strong };
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

  function render() {
    var R = analyze(), B = R.B, scen = R.scen;
    function byCourse(c) { return B.filter(function (b) { return b.course === c; })[0]; }
    var p1 = V.place[0][0], t = tier(p1);
    // 展開
    var top = scen.slice(0, 6), max = top.length ? top[0].p : 1;
    $("#scen").innerHTML = top.map(function (s) {
      return '<div class="scen-row"><span class="waku w' + s.b.waku + '">' + s.b.waku + '</span><div><div>' + s.b.course + "コース" + s.kim +
        '<span class="sub"> ・' + esc(s.b.name) + '</span></div><div class="bar"><i style="width:' + (s.p / max * 100).toFixed(1) +
        '%"></i></div></div><span class="pct">' + s.p.toFixed(0) + "%</span></div>";
    }).join("");
    var lead = scen[0];
    $("#scenLead").textContent = lead ? "本線は「" + lead.b.course + "コース" + lead.kim + "」。上位6つの決着パターンと、起こりやすさの目安です。" : "";
    // ポイント
    var pts = [];
    var b1 = byCourse(1), b2 = byCourse(2), b3 = byCourse(3), b4 = byCourse(4);
    if (b1) {
      var rec = courseRecord(b1);
      if (b1.share >= 55) pts.push("1コース" + b1.name + "が逃げる形が濃厚。" + V.name + "は" + t[0] + "(1コース1着率" + fmt(p1) + "%)。" + (rec ? rec + "。" : ""));
      else if (b1.share >= 40) pts.push("1コース" + b1.name + "が中心だが、絶対ではない。スタートで遅れると2コースの差しが届く。" + (rec ? rec + "。" : ""));
      else pts.push("1コース" + b1.name + "は数字的に苦しい。外からの攻めで主導権を取られる可能性が高い。" + (rec ? rec + "。" : ""));
    }
    if (b2 && b3 && b2.stUse != null && b3.stUse != null && b2.stUse - b3.stUse >= 0.03)
      pts.push("2コースの平均ST(" + fmt(b2.stUse, 2) + ")が3コース(" + fmt(b3.stUse, 2) + ")より遅い。2コースが凹むと、3コースのまくりが入りやすい。");
    if (b2 && b1 && b2.power != null && b1.power != null && b2.power > b1.power + 0.5)
      pts.push("2コース" + b2.name + "の方が1コースより勝率が上。差しが決まる場面に注意。");
    if (b4 && R.aSt != null && b4.stUse != null && b4.stUse <= R.aSt - 0.02)
      pts.push("4コース(カド)" + b4.name + "はスタートが速い(平均ST" + fmt(b4.stUse, 2) + ")。内が凹めばカドまくりの展開。");
    var mTop = B.filter(function (b) { return b.motor2 != null; }).sort(function (a, b) { return b.motor2 - a.motor2; })[0];
    if (mTop && R.aMo != null && mTop.motor2 >= R.aMo + 8) pts.push("モーターは" + mTop.course + "コース" + mTop.name + "(2連率" + fmt(mTop.motor2) + "%)が抜けている。道中で伸びてくる可能性。");
    var eTop = B.filter(function (b) { return b.ex != null; }).sort(function (a, b) { return a.ex - b.ex; })[0];
    if (eTop && R.aEx != null && eTop.ex <= R.aEx - 0.04) pts.push("展示タイムは" + eTop.course + "コース" + eTop.name + "(" + fmt(eTop.ex, 2) + ")が一番。当日の足は良さそう。");
    var moved = B.filter(function (b) { return b.course !== b.waku; });
    if (moved.length) pts.push("進入は枠なりではない(" + moved.map(function (b) { return b.waku + "号艇→" + b.course + "コース"; }).join("、") + ")。");
    if (R.strong && R.wind === "head") pts.push("向かい風" + R.wspd + "m。内が伸びにくく、まくりが決まりやすい条件。");
    if (R.strong && R.wind === "tail") pts.push("追い風" + R.wspd + "m。1マークで流れやすく、差しが入りやすい条件。");
    if (R.wspd >= 6) pts.push("風速" + R.wspd + "mは強め。水面が荒れると、旋回の上手さと経験の差が出やすい。");
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
      if (b.stUse != null && R.aSt != null) { var ds = R.aSt - b.stUse; if (ds >= 0.02) li.push("STが速い(" + fmt(b.stUse, 2) + ")。先手を取れる。"); else if (ds <= -0.02) li.push("STが遅め(" + fmt(b.stUse, 2) + ")。スタートで後手に回りやすい。"); }
      if (b.local && b.rate) { var dl = b.local - b.rate; if (dl >= 0.4) li.push("当地勝率が全国より高い。この水面は得意。"); else if (dl <= -0.4) li.push("当地勝率が全国より低い。この水面は苦手寄り。"); }
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

  // ---- 1周1マーク展開ビュー(turn1.js)。展開の見立てと同じ決着パターンで、直前情報を入れたら作り直す
  var view = null, viewSig = "", patKey = "", patIdx = 0, pats = [], ents = [], viewTimer = null, started = false, wasPlaying = false;
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function viewTitle() { return V.name + " " + D.race.no + "R 1周1マーク"; }
  function scenOf(i) { var s = pats[i]; return { course: s.b.course, kim: s.kim, p: s.p }; }
  function drawPats() {
    var box = $("#t1Pats");
    if (!box) return;
    box.innerHTML = pats.map(function (s, i) {
      return '<button type="button" class="pat' + (i === patIdx ? " on" : "") + '" data-i="' + i + '" aria-pressed="' + (i === patIdx) + '"><span class="waku w' + s.b.waku + '">' + s.b.waku + "</span>" +
        s.b.course + "コース " + s.kim + '<span class="p">' + s.p.toFixed(0) + "%</span></button>";
    }).join("");
  }
  function updateView(R) {
    var canvas = $("#t1view");
    if (!canvas || !window.Turn1) return;
    pats = R.scen.filter(function (s) { return s.kim !== "抜き" && s.kim !== "恵まれ"; }).slice(0, 4);
    if (!pats.length) return;
    var pk = pats.map(function (s) { return s.b.waku + s.kim; }).join(",");
    if (pk !== patKey) { patKey = pk; patIdx = 0; }
    ents = R.B.map(function (b) {
      var c = b.csNow || {};
      return { waku: b.waku, course: b.course, name: b.name, st: b.stUse, motor2: b.motor2, ex: b.ex, cls: b.cls, km: c.km, ls: c.ls, n: c.n, w1: c.w1 };
    });
    drawPats();
    var sc = scenOf(patIdx), sig = JSON.stringify([sc.course, sc.kim, ents.map(function (e) { return [e.waku, e.course, e.st, e.ex]; })]);
    if (sig === viewSig) return;
    viewSig = sig;
    if (!view) {
      view = Turn1.mount(canvas, { entries: ents, scen: sc, title: viewTitle(), kimarite: V.kimarite, brand: "水面ノート",
                                   onEnd: function () { var b = $("#t1Pause"); if (b) b.textContent = "再生"; } });
      watch(canvas);
    } else {
      clearTimeout(viewTimer);
      viewTimer = setTimeout(function () { view.setScenario(sc, ents, viewTitle()); $("#t1Pause").textContent = "一時停止"; }, 700);
    }
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
      patIdx = +b.getAttribute("data-i"); drawPats();
      viewSig = JSON.stringify([scenOf(patIdx).course, scenOf(patIdx).kim, ents.map(function (x) { return [x.waku, x.course, x.st, x.ex]; })]);
      view.setScenario(scenOf(patIdx), ents, viewTitle()); started = true; pause.textContent = "一時停止";
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
  render();
})();
