#!/usr/bin/env node
/* レース検索のデータ({ymd}/search.json)に、見立て(1号艇の逃げの起こりやすさ・起こりやすい決着の上位3つ・本線)を足す。
   できあがったレースのページ(_site)から入力データを読み、ページと同じ model.js で計算する(直前情報があればそれも使う)。
     node scripts/searchidx.js */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SITE = process.env.SITE_DIR || path.join(ROOT, "_site");
const M = require(path.join(ROOT, "site", "assets", "model.js"));
const UR = require(path.join(ROOT, "site", "assets", "ura.js"));

// 同じ場の、いちばん新しい直前情報の風・波(展示の前のレースの、裏の見込みの目安)
const LIVE_CACHE = {};
function venueWeather(ymd, code) {
  const key = ymd + code;
  if (!(key in LIVE_CACHE)) {
    let w = null;
    try {
      const L = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "live", ymd, code + ".json"), "utf8"));
      for (const x of Object.values(L.before || {})) {
        const ww = x && x.weather;
        if (ww && ww.wind != null && (!w || String(x.fetched || "") > w.at)) w = { wind: ww.wind, wave: ww.wave, at: String(x.fetched || "") };
      }
    } catch (e) { w = null; }
    LIVE_CACHE[key] = w;
  }
  return LIVE_CACHE[key];
}

function main() {
  const mp = path.join(ROOT, "data", "model.json");
  if (!fs.existsSync(mp) || !fs.existsSync(SITE)) return;
  const params = JSON.parse(fs.readFileSync(mp, "utf8"));
  const up = path.join(ROOT, "data", "ura.json");
  const UP = fs.existsSync(up) ? JSON.parse(fs.readFileSync(up, "utf8")) : null;
  for (const ymd of fs.readdirSync(SITE).filter((x) => /^\d{8}$/.test(x))) {
    const file = path.join(SITE, ymd, "search.json");
    if (!fs.existsSync(file)) continue;
    const S = JSON.parse(fs.readFileSync(file, "utf8"));
    let n = 0;
    for (const r of S.races || []) {
      const page = path.join(SITE, ymd, r.c, String(r.no).padStart(2, "0") + ".html");
      if (!fs.existsSync(page)) continue;
      const m = fs.readFileSync(page, "utf8").match(/<script type="application\/json" id="race-data">([\s\S]*?)<\/script>/);
      if (!m) continue;
      const D = JSON.parse(m[1].replace(/<\\\//g, "</"));
      const BI = D.before && D.before.ready ? D.before : null;
      const order = BI && BI.course && BI.course.length === 6 ? BI.course : null;
      const wind = BI && BI.weather && BI.weather.wind != null ? Math.round(BI.weather.wind) : 2;
      const race = {
        vt: D.vt, nt: D.nt, wind, date: D.race.date, venue: D.venue.code, name: D.race.name,
        boats: D.entries.map((b) => ({ waku: b.waku, course: order ? order.indexOf(b.waku) + 1 : b.waku,
          pts: b.pts || [0, 0], stx: b.stx || [0, 0, 0], r8: b.r8 || [], f: b.f || [], cs: b.cs || {}, motor2: b.motor2, motorR: b.motorR,
          lv: b.lv || [0, 0], ex: BI && BI.ex ? BI.ex[String(b.waku)] ?? null : null, est: BI && BI.est ? BI.est[String(b.waku)] ?? null : null,
          cb: b.cb || [0, 0] })),
      };
      let R = null;
      try { R = M.predict(race, params, { samples: 200 }); } catch (e) { R = null; }
      if (!R) continue;
      const wakuOf = {};
      race.boats.forEach((b) => { wakuOf[b.course] = b.waku; });
      const ranked = R.p.map((p, i) => [i, p]).sort((a, b) => b[1] - a[1]);
      r.p1 = Math.round(R.p[M.CI["1逃げ"]] * 1000) / 1000;
      r.top = ranked.slice(0, 3).map(([i, p]) => [wakuOf[M.CLASSES[i][0]], M.CLASSES[i][0], M.CLASSES[i][1], Math.round(p * 1000) / 1000]);
      // 本線(レースのページと同じ決め方): 1着になる見込み(勝ち方を全部足したもの)が一番高い艇と、その一番起こりやすい勝ち方
      const pc = [0, 0, 0, 0, 0, 0];
      R.p.forEach((p, i) => { pc[M.CLASSES[i][0] - 1] += p; });
      const lc = pc.indexOf(Math.max(...pc)) + 1;
      const li = R.p.map((p, i) => [i, p]).filter(([i]) => M.CLASSES[i][0] === lc).sort((a, b) =>
        (M.CLASSES[a[0]][1] === "抜き") - (M.CLASSES[b[0]][1] === "抜き") || b[1] - a[1])[0][0];
      r.lead = [wakuOf[lc], lc, M.CLASSES[li][1], Math.round(pc[lc - 1] * 1000) / 1000, Math.round(pc[0] * 1000) / 1000];
      r.pre = !BI;                                   // 展示の前の見立て(枠なり・ふだんのST)
      // 裏: 万舟の見込みと裏本線(レースのページの ura.js と同じ計算。オッズは入れない)
      if (UP && UP.proxy && UP.cal) {
        try {
          const vw = BI && BI.weather && BI.weather.wind != null ? BI.weather : venueWeather(ymd, r.c);
          const B = race.boats.map((b) => ({ waku: b.waku, course: b.course, name: (D.entries.find((e) => e.waku === b.waku) || {}).name }));
          const U = UR.compute(R, B, { venue: D.venue.code, name: D.race.name, wind: vw ? Math.round(vw.wind) : null, wave: vw && vw.wave != null ? Math.round(vw.wave) : null }, UP);
          if (U) {
            const base = UR.venueBase(UP, D.venue.code);
            r.u = { pm: Math.round(U.pMan * 1000) / 1000, r: Math.round(U.pMan / Math.max(base, 0.01) * 100) / 100, lv: UR.level(U.pMan, base)[0], pre: !BI,
                    ul: U.lead ? [U.lead.b.waku, U.lead.c, U.lead.k, Math.round(U.lead.p * 1000) / 1000, Math.round(U.lead.pk * 1000) / 1000] : null, oc: U.oc };
          }
        } catch (e) { /* 裏が計算できなくても、表の見立ては残す */ }
      }
      n++;
    }
    fs.writeFileSync(file, JSON.stringify(S));
    console.log(`${ymd}: ${n}レースに見立てを足しました`);
  }
}

main();
