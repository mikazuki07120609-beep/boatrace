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

function r3(x) { return x == null ? null : Math.round(x * 1000) / 1000; }

function main() {
  const mp = path.join(ROOT, "data", "model.json");
  if (!fs.existsSync(mp) || !fs.existsSync(SITE)) { console.log("見立てモデルかサイトがないので記録しません"); return; }
  const params = JSON.parse(fs.readFileSync(mp, "utf8"));
  const jst = new Date(Date.now() + 9 * 3600e3);           // UTCの値として読むと日本時間になる
  const today = jst.toISOString().slice(0, 10), hm = jst.toISOString().slice(11, 16);
  const day = today.replace(/-/g, "");
  if (!fs.existsSync(path.join(SITE, day))) return;
  const file = path.join(LIVE, day, "pred.json");
  const log = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
  let n = 0;
  for (const v of fs.readdirSync(path.join(SITE, day)).filter((x) => /^\d{2}$/.test(x)).sort()) {
    for (const f of fs.readdirSync(path.join(SITE, day, v)).filter((x) => /^\d{2}\.html$/.test(x)).sort()) {
      const html = fs.readFileSync(path.join(SITE, day, v, f), "utf8");
      const m = html.match(/<script type="application\/json" id="race-data">([\s\S]*?)<\/script>/);
      if (!m) continue;
      const D = JSON.parse(m[1].replace(/<\\\//g, "</"));
      const BI = D.before;
      if (!BI || !BI.ready || D.result || D.live) continue;
      if (D.race.deadline && hm >= D.race.deadline) continue;
      const old = (log[v] || {})[String(D.race.no)];
      if (old && old.before_at === BI.fetched && old.fitted === params.fitted) continue;
      const order = BI.course || [];
      const wind = BI.weather && BI.weather.wind != null ? Math.round(BI.weather.wind) : 2;
      const race = {
        vt: D.vt, nt: D.nt, wind, date: today, venue: D.venue.code,
        boats: D.entries.map((b) => ({ waku: b.waku, course: order.indexOf(b.waku) >= 0 ? order.indexOf(b.waku) + 1 : b.waku,
                                       pts: b.pts || [0, 0], stx: b.stx || [0, 0, 0], r8: b.r8 || [], f: b.f || [], cs: b.cs || {}, motor2: b.motor2,
                                       ex: BI.ex ? BI.ex[String(b.waku)] ?? null : null, est: BI.est ? BI.est[String(b.waku)] ?? null : null,
                                       cb: b.cb || [0, 0] })),
      };
      const R = M.predict(race, params, { samples: 400 });
      if (!R) continue;
      (log[v] = log[v] || {})[String(D.race.no)] = {
        fitted: params.fitted, before_at: BI.fetched || null,
        at: jst.toISOString().slice(0, 16).replace("T", " "),
        course: order,
        p: R.p.map((x) => Math.round(x * 1e4) / 1e4),
        // 起こりやすい決着パターン(上位6つ)ごとの、2着〜6着の並び(コース)
        ord: Object.fromEntries(R.p.map((x, i) => [i, x]).sort((a, b) => b[1] - a[1]).slice(0, 6)
          .map(([i]) => [i, (R.order(i) || {}).order || null]).filter((x) => x[1])),
        st: R.st.slice().sort((a, b) => a.waku - b.waku).map((s) => [r3(s.mean), r3(s.pOut), r3(s.pDent)]),   // 枠番の順
      };
      n++;
    }
  }
  if (n) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(log));
  }
  console.log(`${day}: ${n}レースのスタート展示後の見立てを記録`);
}

main();
