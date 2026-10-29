#!/usr/bin/env node
/* スタート展示のあとに出した見立てを記録する(学習用。サイトには出さない)。
   できあがったレースのページ(_site)から入力データを読み、ページと同じ model.js・同じ入力
   (展示の進入・展示タイム・展示ST・風速)で見立てを計算して、data/live/YYYYMMDD/pred.json に書く。
   締切を過ぎたレースは書き換えない(締切前に最後に記録した見立てが残る)。
     node scripts/predlog.js */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SITE = path.join(ROOT, "_site");
const LIVE = path.join(ROOT, "data", "live");
const M = require(path.join(ROOT, "site", "assets", "model.js"));
const UR = require(path.join(ROOT, "site", "assets", "ura.js"));

function r3(x) { return x == null ? null : Math.round(x * 1000) / 1000; }
const SITE_URL = process.env.SITE_URL || "https://suimennote.com/";

// ---- 裏: 展示のあとの万舟の見込みと裏本線を ura.json にまとめる(裏の今日のレースが読む)。大荒れ注意になったレースは知らせ(RSS・X)に足す
function xesc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[c])); }
function raceData(day, v, no) {
  const f = path.join(SITE, day, v, String(no).padStart(2, "0") + ".html");
  if (!fs.existsSync(f)) return null;
  const m = fs.readFileSync(f, "utf8").match(/<script type="application\/json" id="race-data">([\s\S]*?)<\/script>/);
  return m ? JSON.parse(m[1].replace(/<\\\//g, "</")) : null;
}
function writeUra(day, today, hm, log, UP) {
  const file = path.join(LIVE, day, "ura.json");
  const old = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
  const races = {}, alerts = old.alerts || [], seen = new Set(alerts.map((a) => a.k));
  for (const [v, rs] of Object.entries(log)) {
    for (const [no, x] of Object.entries(rs)) {
      const u = x.u;
      if (!u || u.pm == null) continue;
      const base = UR.venueBase(UP, v), lv = UR.level(u.pm, base);
      const ck = u.ul ? M.CLASSES[u.ul[0]] : null;
      const k = v + "-" + no;
      const ul = u.ul && ck ? [u.ul[1], ck[0], ck[1], u.ul[2], u.ul[3]] : null;
      races[k] = { pm: u.pm, r: Math.round(u.pm / Math.max(base, 0.01) * 100) / 100, lv: lv[0], ul, at: String(x.at || "").slice(11) };
      if (lv[1] === "L3" && !seen.has(k)) {                       // 展示のあとで大荒れ注意(場のふだんの1.5倍以上)になったレース
        const D = raceData(day, v, no) || {};
        const nm = ul ? ((D.entries || []).find((e) => e.waku === ul[0]) || {}).name || "" : "";
        alerts.push({ k, v, no: +no, vn: (D.venue || {}).name || v, dl: (D.race || {}).deadline || null, at: hm, pm: u.pm, base: Math.round(base * 1000) / 1000,
                      ul, ulName: nm });
        seen.add(k);
      }
    }
  }
  fs.writeFileSync(file, JSON.stringify({ date: today, updated: hm, races, alerts }));
  // RSS(直近の大荒れ注意。日をまたいで新しい順に60件まで)
  const fj = path.join(LIVE, "feed.json");
  const feed = fs.existsSync(fj) ? JSON.parse(fs.readFileSync(fj, "utf8")) : [];
  const have = new Set(feed.map((a) => a.id));
  for (const a of alerts) {
    const id = day + "-" + a.k;
    if (have.has(id)) continue;
    feed.unshift({ id, day, date: today, ...a });
  }
  feed.splice(60);
  fs.writeFileSync(fj, JSON.stringify(feed));
  const items = feed.map((a) => {
    const url = SITE_URL + "ura/" + a.day + "/" + a.v + "/" + String(a.no).padStart(2, "0") + ".html";
    const pub = new Date(a.date + "T" + (a.at || "00:00") + ":00+09:00").toUTCString();
    const line = a.ul ? "裏本線は" + a.ul[1] + "コース" + (a.ulName ? a.ulName.split(/[ 　]/)[0] : "") + "の" + a.ul[2] + "。" : "";
    return "<item><title>" + xesc("【大荒れ注意】" + a.vn + a.no + "R" + (a.dl ? "(" + a.dl + "締切)" : "") + " 万舟の見込み" + Math.round(a.pm * 100) + "%") + "</title>" +
      "<link>" + xesc(url) + "</link><guid isPermaLink=\"false\">ura-" + xesc(a.id) + "</guid><pubDate>" + pub + "</pubDate>" +
      "<description>" + xesc("この場のふだんの万舟率は" + Math.round(a.base * 100) + "%。" + line + "展示のあとの計算です。") + "</description></item>";
  }).join("");
  fs.writeFileSync(path.join(LIVE, "feed.xml"), '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>' +
    "<title>裏水面ノート 大荒れ注意</title><link>" + SITE_URL + "ura/</link>" +
    "<description>スタート展示のあとで、万舟の見込みがその場のふだんの1.5倍以上(大荒れ注意)になったレース。</description><language>ja</language>" + items + "</channel></rss>");
}

// 裏: そのレースの最新のオッズ(Cloudflare の置き場所。締切の15分前から1分ごと)。読めなければ null
const DATA_BASE = process.env.DATA_BASE || "https://data.suimennote.com/";
async function getOdds(day, v, no) {
  try {
    const r = await fetch(DATA_BASE + "odds/" + day + "/" + v + "/" + String(no).padStart(2, "0") + ".json?t=" + Date.now(), { signal: AbortSignal.timeout(5000) });
    if (!r.ok) return null;
    const j = await r.json();
    return j && (j["3t"] || j.tan) ? j : null;
  } catch (e) { return null; }
}

async function main() {
  const mp = path.join(ROOT, "data", "model.json");
  if (!fs.existsSync(mp) || !fs.existsSync(SITE)) { console.log("見立てモデルかサイトがないので記録しません"); return; }
  const params = JSON.parse(fs.readFileSync(mp, "utf8"));
  const up = path.join(ROOT, "data", "ura.json");
  const UP = fs.existsSync(up) ? JSON.parse(fs.readFileSync(up, "utf8")) : null;
  const jst = new Date(Date.now() + 9 * 3600e3);           // UTCの値として読むと日本時間になる
  const today = jst.toISOString().slice(0, 10), hm = jst.toISOString().slice(11, 16);
  const day = today.replace(/-/g, "");
  if (!fs.existsSync(path.join(SITE, day))) return;
  const file = path.join(LIVE, day, "pred.json");
  const log = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
  let n = 0, nu = 0;
  for (const v of fs.readdirSync(path.join(SITE, day)).filter((x) => /^\d{2}$/.test(x)).sort()) {
    for (const f of fs.readdirSync(path.join(SITE, day, v)).filter((x) => /^\d{2}\.html$/.test(x)).sort()) {
      const html = fs.readFileSync(path.join(SITE, day, v, f), "utf8");
      const m = html.match(/<script type="application\/json" id="race-data">([\s\S]*?)<\/script>/);
      if (!m) continue;
      const D = JSON.parse(m[1].replace(/<\\\//g, "</"));
      const BI = D.before;
      if (!BI || !BI.ready || D.result || D.live) continue;
      if (D.race.deadline && hm >= D.race.deadline) continue;
      const no = String(D.race.no);
      const old = (log[v] || {})[no];
      const fresh = !(old && old.before_at === BI.fetched && old.fitted === params.fitted);
      const useU = !!(UP && UP.proxy && UP.cal);
      const O = useU ? await getOdds(day, v, no) : null, oat = O ? (O.at || O.t || "") : null;
      if (!fresh && (!useU || ((old.u || {}).pm != null && ((old.u || {}).od || null) === oat))) continue;   // 展示もオッズも変わっていない
      const order = BI.course || [];
      const wind = BI.weather && BI.weather.wind != null ? Math.round(BI.weather.wind) : 2;
      const race = {
        vt: D.vt, nt: D.nt, wind, date: today, venue: D.venue.code, name: D.race.name,
        boats: D.entries.map((b) => ({ waku: b.waku, course: order.indexOf(b.waku) >= 0 ? order.indexOf(b.waku) + 1 : b.waku,
                                       pts: b.pts || [0, 0], stx: b.stx || [0, 0, 0], r8: b.r8 || [], f: b.f || [], cs: b.cs || {}, motor2: b.motor2, motorR: b.motorR, lv: b.lv || [0, 0],
                                       ex: BI.ex ? BI.ex[String(b.waku)] ?? null : null, est: BI.est ? BI.est[String(b.waku)] ?? null : null,
                                       cb: b.cb || [0, 0] })),
      };
      const R = M.predict(race, params, { samples: 400 });
      if (!R) continue;
      if (fresh) {
        (log[v] = log[v] || {})[no] = {
          fitted: params.fitted, before_at: BI.fetched || null,
          at: jst.toISOString().slice(0, 16).replace("T", " "),
          course: order,
          p: R.p.map((x) => Math.round(x * 1e4) / 1e4),
          // 起こりやすい決着パターン(上位6つ)ごとの、2着〜6着の並び(コース)
          ord: Object.fromEntries(R.p.map((x, i) => [i, x]).sort((a, b) => b[1] - a[1]).slice(0, 6)
            .map(([i]) => [i, (R.order(i) || {}).order || null]).filter((x) => x[1])),
          st: R.st.slice().sort((a, b) => a.waku - b.waku).map((s) => [r3(s.mean), r3(s.pOut), r3(s.pDent)]),   // 枠番の順
          u: old && old.before_at === BI.fetched ? old.u : undefined,
        };
        n++;
      }
      // 裏: 万舟の見込みと裏本線(レースのページの ura.js と同じ計算。そのときのオッズも入れる)。締切まで、オッズが変わるたびに計算し直す。答え合わせは learn.py
      if (useU) {
        try {
          const rec = log[v][no];
          const B = race.boats.map((b) => ({ waku: b.waku, course: b.course }));
          const U = UR.compute(R, B, { venue: D.venue.code, name: D.race.name, wind: BI.weather && BI.weather.wind != null ? Math.round(BI.weather.wind) : null,
                                       wave: BI.weather && BI.weather.wave != null ? Math.round(BI.weather.wave) : null,
                                       odds: O ? { "3t": O["3t"] || null, tan: O.tan || null } : null }, UP);
          if (U) {
            const pw = [0, 0, 0, 0, 0, 0];                          // 1着の見込み(枠番の順)
            U.pc.forEach((p, c) => { const w = U.c2w[c + 1]; if (w) pw[w - 1] = r3(p); });
            rec.u = { ura: UP.fitted || null, pm: r3(U.pMan), m: r3(U.m), ow: U.c2w[U.oc] || null,
              ul: U.lead ? [U.lead.i, U.lead.b ? U.lead.b.waku : U.c2w[U.lead.c], r3(U.lead.p), r3(U.lead.pk)] : null, pw, od: oat };
            nu++;
          }
        } catch (e) { /* 裏が計算できなくても、表の記録は残す */ }
      }
    }
  }
  if (n || nu) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(log));
  }
  if (UP && (n || nu || !fs.existsSync(path.join(LIVE, day, "ura.json")))) {
    try { writeUra(day, today, hm, log, UP); } catch (e) { console.log("裏のまとめを書けませんでした:", e.message); }
  }
  console.log(`${day}: ${n}レースのスタート展示後の見立てを記録` + (nu ? `(裏の見込みを${nu}レース計算し直し)` : ""));
}

main().catch((e) => { console.log("見立ての記録でつまずきました:", e && e.message); });
