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

function main() {
  const mp = path.join(ROOT, "data", "model.json");
  if (!fs.existsSync(mp) || !fs.existsSync(SITE)) return;
  const params = JSON.parse(fs.readFileSync(mp, "utf8"));
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
      n++;
    }
    fs.writeFileSync(file, JSON.stringify(S));
    console.log(`${ymd}: ${n}レースに見立てを足しました`);
  }
}

main();
