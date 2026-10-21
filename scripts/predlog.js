#!/usr/bin/env node
/* 本番前の見立てを記録する(答え合わせ用)。
   できあがったレースのページ(_site)から入力データを読み、ページと同じ model.js・同じ初期状態
   (進入は枠なり・展示タイムなし・風速2m)で見立てを計算して、data/pred/YYYYMMDD.json に書く。
   締切を過ぎたレースと、結果が出たレースは書き換えない(締切前に最後に記録した見立てが残る)。
     node scripts/predlog.js */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SITE = path.join(ROOT, "_site");
const OUT = path.join(ROOT, "data", "pred");
const M = require(path.join(ROOT, "site", "assets", "model.js"));

function r3(x) { return x == null ? null : Math.round(x * 1000) / 1000; }

function main() {
  const mp = path.join(ROOT, "data", "model.json");
  if (!fs.existsSync(mp) || !fs.existsSync(SITE)) { console.log("見立てモデルかサイトがないので記録しません"); return; }
  const params = JSON.parse(fs.readFileSync(mp, "utf8"));
  const jst = new Date(Date.now() + 9 * 3600e3);           // UTCの値として読むと日本時間になる
  const today = jst.toISOString().slice(0, 10), hm = jst.toISOString().slice(11, 16);
  fs.mkdirSync(OUT, { recursive: true });
  for (const day of fs.readdirSync(SITE).filter((x) => /^\d{8}$/.test(x)).sort()) {
    const iso = `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`;
    if (iso < today) continue;                              // 過去の日の記録は書き換えない
    const file = path.join(OUT, `${day}.json`);
    const log = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : { date: iso, venues: {} };
    let n = 0;
    for (const v of fs.readdirSync(path.join(SITE, day)).filter((x) => /^\d{2}$/.test(x)).sort()) {
      for (const f of fs.readdirSync(path.join(SITE, day, v)).filter((x) => /^\d{2}\.html$/.test(x)).sort()) {
        const html = fs.readFileSync(path.join(SITE, day, v, f), "utf8");
        const m = html.match(/<script type="application\/json" id="race-data">([\s\S]*?)<\/script>/);
        if (!m) continue;
        const D = JSON.parse(m[1].replace(/<\\\//g, "</"));
        if (D.result) continue;
        if (iso === today && D.race.deadline && hm >= D.race.deadline) continue;
        const race = {
          vt: D.vt, nt: D.nt, wind: 2, date: iso, venue: D.venue.code,
          boats: D.entries.map((b) => ({ waku: b.waku, course: b.waku, pts: b.pts || [0, 0], stx: b.stx || [0, 0, 0], r8: b.r8 || [],
                                         f: b.f || [], cs: b.cs || {}, motor2: b.motor2, ex: null })),
        };
        const R = M.predict(race, params, { samples: 400 });
        if (!R) continue;
        (log.venues[v] = log.venues[v] || {})[String(D.race.no)] = {
          fitted: params.fitted,
          at: jst.toISOString().slice(0, 16).replace("T", " "),
          p: R.p.map((x) => Math.round(x * 1e4) / 1e4),
          st: R.st.map((s) => [r3(s.mean), r3(s.pOut), r3(s.pDent)]),
        };
        n++;
      }
    }
    fs.writeFileSync(file, JSON.stringify(log));
    console.log(`${day}: ${n}レースの本番前の見立てを記録`);
  }
}

main();
