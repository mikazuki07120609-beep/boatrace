/* 裏水面ノート(レースのページ): 裏の部分を描く。計算は ura.js、見立ては race.js(model.js)。
   race.js が描き直すたびに SuimenUraPage.render(R, ctx) を呼ぶ(R: race.js の analyze の結果、ctx: 直前情報・オッズなど)。 */
(function () {
  "use strict";
  var UP = window.SUIMEN_URA, UX = window.SuimenUra;
  function $(s) { return document.querySelector(s); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function pc(x, d) { return x == null || !isFinite(x) ? "—" : (x * 100).toFixed(d || 0) + "%"; }
  function pk(x) { return x >= 0.995 ? "99%以上" : pc(x); }            // その決着のオッズが全部100倍以上なら、ほぼ必ず万舟
  function wk(w) { return '<span class="waku w' + w + '">' + w + "</span>"; }
  function put(sel, html) { var el = $(sel); if (el) el.innerHTML = html; }
  function surname(n) { return String(n || "").split(/[ 　]/)[0]; }
  var last = null;

  function stateText(ctx, U) {
    if (ctx.finished) return "締切前の計算";
    if (U.odds) return "展示とオッズを入れた計算";
    if (ctx.ready) return "展示のあとの計算";
    return "展示の前の目安(枠なり・ふだんのST)";
  }
  function hero(U, ctx, why) {
    var base = UX.venueBase(UP, ctx.venue), lv = UX.level(U.pMan, base), nat = ((UP.stats || {}).nat || 16) / 100;
    var L = U.lead, b = L && L.b;
    var val = U.pop && U.pop.value.length ? U.pop.value[0] : null;
    return '<div class="uh">' +
      '<div class="uh-main"><div class="uh-k">万舟の見込み<span class="uh-st">' + esc(stateText(ctx, U)) + "</span></div>" +
      '<div class="uh-v"><b>' + Math.round(U.pMan * 100) + '</b><small>%</small><span class="ulv ' + lv[1] + '">' + lv[0] + "</span></div>" +
      '<div class="uh-bar" role="img" aria-label="万舟の見込み ' + pc(U.pMan) + "、この場のふだん " + pc(base) + '"><i style="width:' + Math.min(100, U.pMan * 250).toFixed(1) + '%"></i>' +
      '<span class="uh-base" style="left:' + Math.min(100, base * 250).toFixed(1) + '%"></span></div>' +
      '<div class="uh-sub">この場のふだん ' + pc(base) + "・全国 " + pc(nat) + "</div></div>" +
      (L ? '<div class="uh-line"><div class="uh-k">裏本線</div><div class="uh-lv">' + wk(b.waku) + "<b>" + L.c + "コース " + esc(L.k) + "</b>" +
        '<span class="uh-who">' + esc(b.name || "") + "</span></div>" +
        '<div class="uh-sub">この決着になる見込み ' + pc(L.p, L.p < 0.1 ? 1 : 0) + "・そのとき万舟 " + pk(L.pk) + "</div></div>" : "") +
      (why.length ? '<ul class="uh-why">' + why.slice(0, 3).map(function (r) { return "<li>" + esc(r.t) + "</li>"; }).join("") + "</ul>" : "") +
      (val ? '<div class="uh-val"><span class="uv-k">人気より見立てが上</span>' + wk(val.b.waku) + esc(surname(val.b.name)) + " " + val.rank + "番人気(単勝" + val.odds.toFixed(1) +
        "倍)・見立ての1着 " + pc(val.pw) + "</div>" : "") +
      "</div>";
  }
  // 穴の材料(艇ごと)
  function card(U, ctx) {
    var tot = U.scen.reduce(function (a, s) { return a + s.s; }, 0) || 1;
    var rows = ctx.B.slice().sort(function (a, b) { return a.waku - b.waku; }).map(function (b) {
      var pw = U.pc[b.course - 1], ps = U.scen.filter(function (s) { return s.c === b.course; }).reduce(function (a, s) { return a + s.s; }, 0) / tot;
      var tags = [], cs = (b.cs || {})[String(b.course)] || {}, km = cs.km || {};
      if (b.course >= 3 && cs.n >= 10 && ((km["捲り"] || 0) + (km["捲り差し"] || 0)) / cs.n >= 0.08) tags.push(["攻め", "捲り系1着 " + ((km["捲り"] || 0) + (km["捲り差し"] || 0)) + "回"]);
      if (b.stf && b.stf.pOut >= 0.18) tags.push(["一撃", "一撃 " + pc(b.stf.pOut)]);
      if (b.stf && b.stf.pDent >= 0.18) tags.push(["凹み", "凹み " + pc(b.stf.pDent)]);
      if (ctx.exRank && ctx.exRank[b.waku] === 1) tags.push(["足", "展示1位"]);
      else if (ctx.exRank && ctx.exRank[b.waku] >= 5) tags.push(["弱", "展示" + ctx.exRank[b.waku] + "位"]);
      if (b.mgGrade && /^(S\+|S|A)$/.test(b.mgGrade)) tags.push(["機", "モーター" + b.mgGrade]);
      if (b.mgGrade && /^[DE]$/.test(b.mgGrade)) tags.push(["弱", "モーター" + b.mgGrade]);
      if ((b.fp || 0) > 0) tags.push(["F", "F" + b.fp + "持ち"]);
      if (b.course === 1 && cs.n >= 5 && cs.w1 / cs.n < 0.4) tags.push(["弱", "イン1着率 " + Math.round(cs.w1 / cs.n * 100) + "%"]);
      if (b.course !== b.waku) tags.push(["進入", b.waku + "→" + b.course + "コース"]);
      var pop = U.pop ? U.pop.rows.filter(function (r) { return r.b === b; })[0] : null;
      return "<tr" + (U.lead && U.lead.b === b ? ' class="ulead"' : "") + "><td>" + wk(b.waku) + "</td><td class=\"unc\"><div class=\"un\"><b>" + esc(b.name || "") + "</b>" +
        '<span class="dim">' + b.course + "コース " + esc(b.cls || "") + (U.lead && U.lead.b === b ? ' <i class="ubtag">裏本線</i>' : "") + "</span>" +
        (tags.length ? '<span class="utags">' + tags.map(function (t) { return '<span class="utag t' + esc(t[0]) + '">' + esc(t[1]) + "</span>"; }).join("") + "</span>" : "") + "</div></td>" +
        '<td class="num">' + pc(pw) + "</td>" + '<td class="num"><b>' + pc(ps) + "</b></td>" +
        '<td class="num">' + (pop ? pop.rank + "番人気<span class=\"dim\">" + pop.odds.toFixed(1) + "倍</span>" : "—") + "</td></tr>";
    }).join("");
    return '<div class="scroll"><table class="gridt utab"><thead><tr><th></th><th class="unc">選手・穴の材料</th><th class="num">1着の<br>見込み</th><th class="num">荒れた<br>とき1着</th>' +
      '<th class="num">人気</th></tr></thead><tbody>' + rows + "</tbody></table></div>" +
      '<p class="note">荒れたとき1着は、万舟になったとしたら、どの艇が1着の形が多いか(見立てで万舟になる決着の中での割合)です。人気は単勝オッズの順位(締切の15分前から)。' +
      "穴の材料: 捲り系1着=このコースでの捲り・捲り差しの1着の回数、一撃=一撃スタートの見込み、凹み=スタートで凹む見込み、展示=展示タイムの順位、F持ち=今期のフライング(スタートを控えやすい)。</p>";
  }
  // 外の攻め手と、1号艇の負け方
  function tac(U, ctx) {
    var st = UP.stats || {}, rows = [], nat = ctx.nt || {};
    ctx.B.slice().sort(function (a, b) { return a.course - b.course; }).forEach(function (b) {
      var cs = (b.cs || {})[String(b.course)] || {}, km = cs.km || {}, n = cs.n || 0;
      if (b.course === 1) {
        var ls = cs.ls || {}, lt = ["差し", "捲り", "捲り差し"].filter(function (k) { return ls[k]; }).map(function (k) { return { "差し": "差され", "捲り": "捲られ", "捲り差し": "捲り差され" }[k] + ls[k]; }).join("・");
        rows.push("<li>" + wk(b.waku) + "<b>1コース " + esc(b.name || "") + "</b>: " + (n ? "1コースの1着 " + (cs.w1 || 0) + "回/" + n + "走(" + Math.round((cs.w1 || 0) / n * 100) + "%)" : "1コースの記録が少ない") +
          (lt ? "。負けたときは " + esc(lt) : "") + "</li>");
        return;
      }
      var mk = (km["捲り"] || 0), ms = (km["捲り差し"] || 0), sa = (km["差し"] || 0);
      var nt = nat[String(b.course)] || {}, nk = nt.km || {}, nn = nt.n || 0;
      var natMk = nn ? ((nk["捲り"] || 0) + (nk["捲り差し"] || 0)) / nn : null;
      var mine = n ? (mk + ms) / n : null;
      var strong = mine != null && natMk != null && n >= 15 && mine >= natMk * 1.5 && mk + ms >= 3;
      rows.push("<li" + (strong ? ' class="ust"' : "") + ">" + wk(b.waku) + "<b>" + b.course + "コース " + esc(b.name || "") + "</b>: " +
        (n ? "1着 " + (cs.w1 || 0) + "回/" + n + "走(捲り" + mk + "・捲り差し" + ms + "・差し" + sa + ")" : "このコースの記録が少ない") +
        (mine != null && natMk != null ? '。捲り系の1着は走数の ' + pc(mine) + '<span class="dim">(全国 ' + pc(natMk) + ")</span>" : "") +
        (b.stf ? "。一撃スタート " + pc(b.stf.pOut) : "") + (strong ? '<span class="utag t攻め">捲り屋</span>' : "") + "</li>");
    });
    return '<ul class="points">' + rows.join("") + "</ul>";
  }
  // 荒れのサイン(直前情報)
  function before(U, ctx) {
    var BI = ctx.BI;
    if (!BI || !BI.ready) return '<p class="wait">展示航走のあと(締切の10〜15分前ごろ)に、展示タイム・スタート展示・進入・チルト・部品交換・風と波から、荒れにつながるサインを探します。</p>';
    var out = [], B = ctx.B, byW = {};
    B.forEach(function (b) { byW[b.waku] = b; });
    var ex = ctx.exRank || {};
    var outer = B.filter(function (b) { return b.course >= 4 && ex[b.waku] && ex[b.waku] <= 2; });
    if (outer.length) out.push("外の伸び: " + outer.map(function (b) { return b.waku + "号艇(" + b.course + "コース)が展示タイム" + ex[b.waku] + "位"; }).join("、") + "。外から攻める足がありそうです。");
    var b1 = B.filter(function (b) { return b.course === 1; })[0];
    if (b1 && ex[b1.waku] >= 5) out.push("1コースの" + b1.waku + "号艇は展示タイム" + ex[b1.waku] + "位。足が見劣りします。");
    var est = BI.est || {};
    if (b1 && est[String(b1.waku)] != null) {
      var e1 = est[String(b1.waku)], inn = B.filter(function (b) { return b.course >= 2 && b.course <= 3 && est[String(b.waku)] != null; }).map(function (b) { return est[String(b.waku)]; });
      if (inn.length && e1 - Math.min.apply(null, inn) >= 0.05) out.push("スタート展示で1コースが遅れ気味(" + (e1 < 0 ? "F" : "") + Math.abs(e1).toFixed(2) + ")。本番でも凹むと、2・3コースの攻めが入ります。");
    }
    var fast = B.filter(function (b) { return b.course >= 3 && est[String(b.waku)] != null; }).sort(function (a, b) { return est[String(a.waku)] - est[String(b.waku)]; })[0];
    if (fast) {
      var ef = est[String(fast.waku)], others = B.filter(function (b) { return b !== fast && est[String(b.waku)] != null; }).map(function (b) { return est[String(b.waku)]; });
      if (others.length && ef <= Math.min.apply(null, others) - 0.03) out.push(fast.course + "コースの" + fast.waku + "号艇がスタート展示で一番早い(" + (ef < 0 ? "F" : "") + Math.abs(ef).toFixed(2) + ")。踏み込んでくれば一撃があります。");
    }
    var co = BI.course || [];
    if (co.length === 6 && co.some(function (w, i) { return w !== i + 1; })) out.push("進入が動きました(" + co.join("") + ")。" + (U.x.mz ? "前づけで起こしが深くなり、スロー勢のスタートが遅れやすくなります。" : ""));
    var tilt = BI.tilt || {};
    B.forEach(function (b) { var t = tilt[String(b.waku)]; if (t != null && t >= 0.5) out.push(b.waku + "号艇がチルト+" + t.toFixed(1) + "。伸びで攻める構えです。"); });
    var parts = BI.parts || {};
    B.forEach(function (b) { var p = (parts[String(b.waku)] || []).filter(Boolean); if (p.length) out.push(b.waku + "号艇が部品交換(" + p.join("・") + ")。足の変化に注意。"); });
    var W = BI.weather || {};
    if (W.wind != null || W.wave != null) out.push("水面: 風速" + (W.wind != null ? W.wind : "—") + "m・波" + (W.wave != null ? W.wave : "—") + "cm。" + (W.wind >= 5 ? "強めの風で、スタートがばらつきやすい条件です。" : ""));
    return out.length ? '<ul class="points">' + out.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul>" : '<p class="sub">展示では、目立った荒れのサインは見つかりませんでした。</p>';
  }
  // 人気と見立てのずれ
  function odds(U, ctx) {
    if (!U.pop) return '<p class="wait">締切の15分前から、オッズ(人気)と見立ての1着の見込みを並べ、人気しすぎの艇と、人気より見立てが上の艇を探します。</p>';
    var rows = U.pop.rows.slice().sort(function (a, b) { return a.rank - b.rank; }).map(function (r) {
      var mark = r.ratio >= 1.3 && r.pw >= 0.05 && r.b.course !== U.oc ? '<span class="utag t攻め">見立てが上</span>' : r.pm - r.pw >= 0.08 ? '<span class="utag t弱">人気しすぎ</span>' : "";
      var mvc = r.mv == null ? '<span class="dim">—</span>' : (r.mv <= 0.8 ? '<span class="umv dn">' + r.f0.toFixed(1) + "→<b>" + r.odds.toFixed(1) + "</b></span>" :
        r.mv >= 1.3 ? '<span class="umv up">' + r.f0.toFixed(1) + "→" + r.odds.toFixed(1) + "</span>" : '<span class="dim">' + r.f0.toFixed(1) + "→" + r.odds.toFixed(1) + "</span>");
      return "<tr><td class=\"num\">" + r.rank + "</td><td>" + wk(r.b.waku) + " " + esc(surname(r.b.name)) + "</td><td class=\"num\">" + r.odds.toFixed(1) + "</td>" +
        '<td class="num">' + mvc + "</td>" +
        '<td class="num">' + pc(r.pm) + '</td><td class="num"><b>' + pc(r.pw) + "</b></td><td>" + mark + "</td></tr>";
    }).join("");
    var c100 = 0, p100 = 0, O = ctx.odds && ctx.odds["3t"];
    if (O) {
      for (var a = 1; a <= 6; a++) for (var b = 1; b <= 6; b++) for (var c = 1; c <= 6; c++) {
        if (a === b || b === c || a === c) continue;
        var od = O[U.c2w[a] + "-" + U.c2w[b] + "-" + U.c2w[c]];
        if (od >= 100) { c100++; p100 += U.T[(a - 1) * 36 + (b - 1) * 6 + (c - 1)]; }
      }
    }
    return '<div class="scroll"><table class="gridt"><thead><tr><th class="num">人気</th><th>艇</th><th class="num">単勝</th><th class="num">締切前の<br>動き</th><th class="num">人気からの<br>見込み</th>' +
      '<th class="num">見立ての<br>1着</th><th></th></tr></thead><tbody>' + rows + "</tbody></table></div>" +
      (O ? '<p class="sub">3連単で100倍以上の組み合わせは120通り中 <b>' + c100 + "通り</b>。見立てでは、そのどれかで決まる見込みが <b>" + pc(p100) + "</b>(これが万舟の見込みのもとです)。</p>" : "") +
      '<p class="note">人気からの見込みは、単勝オッズの逆数を6艇で合計1にしたもの。見立てが人気の1.3倍以上の艇を「見立てが上」、人気からの見込みが見立てより8ポイント以上高い艇を「人気しすぎ」にしています。' +
      "締切前の動きは、このレースで最初に取り込んだ単勝オッズ(締切の約15分前)から今までの変化で、赤は2割以上下がった(売れた)艇です。</p>";
  }
  // この場の荒れ方
  function venueData(U, ctx) {
    var st = UP.stats || {}, v = ctx.venue, base = UX.venueBase(UP, v);
    function tbl(title, obj, order, fmt) {
      if (!obj) return "";
      var ks = order.filter(function (k) { return obj[k]; });
      if (!ks.length) return "";
      return '<div class="gridt-wrap"><table class="gridt ukt"><caption>' + esc(title) + "</caption><thead><tr><th></th><th class=\"num\">万舟率</th><th class=\"num\">数</th></tr></thead><tbody>" +
        ks.map(function (k) { var x = obj[k]; return "<tr><td>" + esc(fmt(k)) + '</td><td class="num' + (x[0] / 100 >= base * 1.15 ? " hi" : "") + '">' + x[0].toFixed(0) + '%</td><td class="num dim">' + x[1] + "</td></tr>"; }).join("") +
        "</tbody></table></div>";
    }
    var html = '<p class="sub">' + esc(ctx.vname) + "のふだんの万舟率は <b>" + pc(base) + "</b>(全国 " + pc((st.nat || 16) / 100) + "・過去1年)。</p>" + '<div class="ukts">' +
      tbl("風速", (st.wind || {})[v], ["0-2", "3-4", "5-6", "7+"], function (k) { return k === "7+" ? "7m以上" : k.replace("-", "〜") + "m"; }) +
      tbl("波", (st.wave || {})[v], ["0-2", "3-5", "6-9", "10+"], function (k) { return k === "10+" ? "10cm以上" : k.replace("-", "〜") + "cm"; }) +
      tbl("レース番号", (st.time || {})[v], ["1-4", "5-8", "9-12"], function (k) { return k.replace("-", "〜") + "R"; }) +
      tbl("風向き(3m以上)", (st.dir || {})[v], ["北", "北東", "東", "南東", "南", "南西", "西", "北西"], function (k) { return k; }) + "</div>";
    var kim = st.kim || {}, ks = Object.keys(kim).filter(function (k) { return kim[k][1] >= 100; }).sort(function (a, b) { return kim[b][0] - kim[a][0]; }).slice(0, 6);
    if (ks.length) html += '<p class="sub">全国で万舟になりやすい決着: ' + ks.map(function (k) { return esc(k.replace(/^(\d)/, "$1コース")) + " " + kim[k][0].toFixed(0) + "%"; }).join("・") + "</p>";
    var rec = (st.recent || {})[v] || [];
    if (rec.length) html += '<div class="gridt-wrap"><table class="gridt"><caption>最近の万舟(この場)</caption><thead><tr><th>日</th><th class="num">R</th><th>3連単</th><th class="num">払戻金</th><th class="num">人気</th><th>決まり手</th></tr></thead><tbody>' +
      rec.map(function (x) { return "<tr><td>" + esc(x[0]) + '</td><td class="num">' + x[1] + "</td><td>" + esc(x[2]) + '</td><td class="num">' + Number(x[3]).toLocaleString() + "円</td>" +
        '<td class="num">' + (x[4] || "—") + "</td><td>" + (x[5] ? x[5] + "コース " : "") + esc(x[6] || "") + "</td></tr>"; }).join("") + "</tbody></table></div>";
    return html;
  }
  function post(U, ctx, why) {
    var base = UX.venueBase(UP, ctx.venue), lv = UX.level(U.pMan, base), L = U.lead;
    var lines = ["【" + ctx.vname + ctx.no + "R 裏メモ】", "万舟の見込み" + pc(U.pMan) + "(" + lv[0] + "・この場のふだん" + pc(base) + ")。"];
    if (L) lines.push("裏本線は" + L.c + "コース" + surname(L.b.name) + "の" + L.k + "(この決着になる見込み" + pc(L.p, L.p < 0.1 ? 1 : 0) + "、そのとき万舟" + pk(L.pk) + ")。");
    why.slice(0, 2).forEach(function (r) { lines.push(r.t); });
    lines.push("", "※データから見た荒れの目安です。舟券の推奨ではありません。", "#ボートレース #万舟 #" + ctx.vname);
    return lines.join("\n");
  }

  // ---- まとめて描く(race.js から)。戻り値: ura.js の計算結果(裏本線など)
  function render(R, ctx) {
    if (!UP || !UX || !UP.proxy || !R || !R.M) {
      put("#uraHero", '<p class="sub">裏の見立ての学習がまだできていないため、このレースの万舟の見込みは出せません。</p>');
      return null;
    }
    var U = UX.compute(R.M, R.B, { venue: ctx.venue, name: ctx.name, wind: ctx.wind, wave: ctx.wave, odds: ctx.odds }, UP);
    if (!U) return null;
    var why = UX.reasons(U, ctx, UP);
    U.why = why;
    put("#uraHero", hero(U, ctx, why));
    put("#uraCard", card(U, ctx));
    put("#uraTac", tac(U, ctx));
    put("#uraBefore", before(U, ctx));
    put("#uraOdds", odds(U, ctx));
    if (!last || last.venue !== ctx.venue) put("#uraData", venueData(U, ctx));
    put("#points", why.length ? why.map(function (r) { return "<li>" + esc(r.t) + "</li>"; }).join("") : "<li>目立った荒れの材料は見つかりませんでした。</li>");
    var pb = $("#post");
    if (pb) pb.value = post(U, ctx, why);
    last = { venue: ctx.venue, U: U };
    return U;
  }
  // 欠場などで見立てを出せないときも、この場の荒れ方(過去の集計)は出す
  function venueOnly(ctx) { if (UP && UX) put("#uraData", venueData(null, ctx)); }
  window.SuimenUraPage = { render: render, venue: venueOnly, pc: pc };
})();
