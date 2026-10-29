// 調べもの(一時): 公式のリプレイのプレーヤーを、ふつうに見るのと同じようにブラウザ(Google Chrome)で開き、
// 何秒かおきに映像の画面を撮って probe_out/ に置く。映像のファイルは取らない。読み取れる映像かどうかを確かめるため。
//   node .github/probe_video.js "<プレーヤーのURL>" [撮る秒(カンマ区切り)]
const { chromium } = require("playwright");
const fs = require("fs");
(async () => {
  const url = process.argv[2], times = (process.argv[3] || "0,10,20,30,40,50,60,70,80,90,100,110,120").split(",").map(Number);
  fs.mkdirSync("probe_out", { recursive: true });
  const log = [];
  const b = await chromium.launch({ channel: "chrome", args: ["--autoplay-policy=no-user-gesture-required"] });
  const pg = await b.newPage({ viewport: { width: 960, height: 540 } });
  pg.on("console", (m) => log.push("console: " + m.text().slice(0, 300)));
  pg.on("response", (r) => { const u = r.url(); if (/m3u8|\.ts\b|\.m4s|\.mp4|playback\.api/.test(u)) log.push("response: " + r.status() + " " + u.slice(0, 200)); });
  await pg.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  // 公式のリプレイのページ(プレーヤーを中に埋め込んだページ)のときは、中のプレーヤーの画面を見る
  await pg.waitForTimeout(6000);
  const fr = pg.frames().find((f) => /front\.player\.boatrace-cdn\.jp/.test(f.url()));
  log.push("frames: " + pg.frames().map((f) => f.url().slice(0, 120)).join(" | "));
  const ctx = fr || pg;
  let ok = false;
  for (let i = 0; i < 40 && !ok; i++) {
    await pg.waitForTimeout(1000);
    ok = await ctx.evaluate(() => { const v = document.querySelector("video"); return !!(v && v.readyState >= 2 && v.duration > 0); });
  }
  const info = await ctx.evaluate(() => { const v = document.querySelector("video"); return v ? { duration: v.duration, w: v.videoWidth, h: v.videoHeight, src: (v.currentSrc || "").slice(0, 80) } : null; });
  log.push("video: " + JSON.stringify(info));
  if (ok) {
    await ctx.evaluate(() => { const v = document.querySelector("video"); v.muted = true; v.pause(); });
    for (const t of times) {
      if (info && t > info.duration) break;
      await ctx.evaluate((t) => new Promise((res) => { const v = document.querySelector("video"); v.addEventListener("seeked", () => res(), { once: true }); v.currentTime = t; setTimeout(res, 8000); }), t);
      await pg.waitForTimeout(700);
      const el = await ctx.$("video");
      await el.screenshot({ path: `probe_out/frame_${String(t).padStart(4, "0")}.png` });
    }
  }
  fs.writeFileSync("probe_out/summary.txt", log.join("\n"));
  console.log(log.join("\n"));
  await b.close();
})();
