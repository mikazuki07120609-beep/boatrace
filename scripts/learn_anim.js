#!/usr/bin/env node
/* 1周1マークの映像が、実際のレース(進入・ST・決まり手・着順)をどこまで再現できたかを数える(学習の記録。サイトには出さない)。
   前の日のレースのページ(_site)から、実際の結果で映像を作り、先頭・決まり手・2着・3着が実際と同じになったかを、
   決まり手ごとにまとめて data/learn/YYYYMMDD.json の anim に書く。
     node scripts/learn_anim.js [YYYYMMDD] */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
require(path.join(ROOT, "site", "assets", "turn1.js"));
const T = globalThis.Turn1;
const KIND = { "逃げ": "nige", "差し": "sashi", "捲り": "makuri", "捲り差し": "makurizashi" };

function main() {
  const arg = process.argv[2];
  const jst = new Date(Date.now() + 9 * 3600e3 - 24 * 3600e3);
  const day = arg || jst.toISOString().slice(0, 10).replace(/-/g, "");
  const dir = path.join(ROOT, "_site", day);
  if (!fs.existsSync(dir)) { console.log("ページがありません:", day); return; }
  const by = {}, tot = { races: 0, lead: 0, kind: 0, p2: 0, p3: 0, inv: 0 }, fails = [];
  for (const v of fs.readdirSync(dir).filter((x) => /^\d{2}$/.test(x)).sort()) {
    for (const f of fs.readdirSync(path.join(dir, v)).filter((x) => /^\d{2}\.html$/.test(x)).sort()) {
      const html = fs.readFileSync(path.join(dir, v, f), "utf8");
      const m = html.match(/<script type="application\/json" id="race-data">([\s\S]*?)<\/script>/);
      if (!m) continue;
      const D = JSON.parse(m[1].replace(/<\\\//g, "</"));
      const R = D.result;
      if (!R || !KIND[R.kimarite]) continue;
      const res = R.entries;
      if (res.length !== 6 || res.some((x) => !x.course || !x.rank || x.st == null || x.flying)) continue;
      const win = res.find((x) => x.rank === 1);
      const target = res.slice().sort((a, b) => a.rank - b.rank).map((x) => x.course);
      const ents = D.entries.map((e) => {
        const x = res.find((y) => y.waku === e.waku), cs = (e.cs || {})[String(x.course)] || {};
        return { waku: e.waku, course: x.course, name: e.name, st: x.st, motor2: e.motor2, ex: x.ex, cls: e.cls, km: cs.km, ls: cs.ls, n: cs.n, w1: cs.w1 };
      });
      let P;
      try { P = T.plan(ents, { course: win.course, kim: R.kimarite, order: target }, D.venue.kimarite, { fixedST: true }); }
      catch (err) { continue; }
      const got = P.order || [];
      const key = win.course + R.kimarite;
      const b = by[key] = by[key] || { races: 0, lead: 0, kind: 0, p2: 0, p3: 0 };
      const lead = got[0] === win.course, kind = P.labels.byCourse[win.course].kind === KIND[R.kimarite];
      let inv = 0;
      for (let a = 0; a < 6; a++) for (let c = a + 1; c < 6; c++) if (got.indexOf(target[a]) > got.indexOf(target[c])) inv++;
      for (const o of [b, tot]) { o.races++; o.lead += lead ? 1 : 0; o.kind += kind ? 1 : 0; o.p2 += got[1] === target[1] ? 1 : 0; o.p3 += got[2] === target[2] ? 1 : 0; }
      tot.inv += inv;
      if (!lead || !kind || got[1] !== target[1]) fails.push({ v, no: D.race.no, sc: key, want: target.join(""), got: got.join(""), kind: P.labels.byCourse[win.course].kind });
    }
  }
  if (!tot.races) { console.log("比べられるレースがありません:", day); return; }
  const pct = (a, n) => Math.round(a / n * 1000) / 10;
  const anim = { races: tot.races, lead: pct(tot.lead, tot.races), kind: pct(tot.kind, tot.races), hit2: pct(tot.p2, tot.races), hit3: pct(tot.p3, tot.races),
                 inv: Math.round(tot.inv / tot.races * 100) / 100,
                 byScenario: Object.fromEntries(Object.entries(by).sort((a, b) => b[1].races - a[1].races).map(([k, o]) =>
                   [k, { races: o.races, lead: pct(o.lead, o.races), kind: pct(o.kind, o.races), hit2: pct(o.p2, o.races) }])),
                 fails: fails.slice(0, 40) };
  const file = path.join(ROOT, "data", "learn", day + ".json");
  const cur = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : { date: `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}` };
  cur.anim = anim;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(cur));
  console.log(`${day}: 映像の再現 ${tot.races}レース 先頭${anim.lead}% 決まり手${anim.kind}% 2着${anim.hit2}% 3着${anim.hit3}%`);
}

main();
