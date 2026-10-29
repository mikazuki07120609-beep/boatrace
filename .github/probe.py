#!/usr/bin/env python3
"""調べもの(一時): 指定したページと、そのページが読み込むスクリプトを取ってきて probe_out/ に置き、
動画の配信のしかた(m3u8・mp4・API の URL など)の手がかりを summary.txt にまとめる。動画そのものは取らない。
  python3 .github/probe.py URL [URL ...]"""
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "suimen-note/1.0 (+https://mikazuki07120609-beep.github.io/boatrace/)"
OUT = pathlib.Path("probe_out")
MAX_BYTES = 3_000_000
MAX_FILES = 25
HINT = re.compile(r"""["'(]([^"'()\s]*(?:m3u8|\.mp4|/api/|replay|movie|video|stream|vod|hls|cdn)[^"'()\s]*)["')]""", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, dict(r.headers), r.read(MAX_BYTES)


def name_of(url):
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[-1])
    return s[:150]


def main(urls):
    OUT.mkdir(exist_ok=True)
    seen, queue, summary = set(), list(urls), []
    n = 0
    while queue and n < MAX_FILES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            st, hd, body = get(url)
        except Exception as ex:  # noqa: BLE001
            summary.append(f"== {url}\n  読めませんでした: {ex}")
            continue
        n += 1
        f = OUT / name_of(url)
        f.write_bytes(body)
        text = body.decode("utf-8", "replace")
        summary.append(f"== {url}\n  {st} {hd.get('Content-Type')} {len(body)}バイト → {f.name}")
        hints = sorted(set(m.group(1) for m in HINT.finditer(text)))
        for h in hints[:80]:
            summary.append(f"  手がかり: {h}")
        for m in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", text, re.I):     # ページが読むスクリプトも見る
            u = urllib.parse.urljoin(url, m.group(1))
            if u not in seen:
                queue.append(u)
        time.sleep(2)
    (OUT / "summary.txt").write_text("\n".join(summary), encoding="utf-8")
    print("\n".join(summary))


if __name__ == "__main__":
    main(sys.argv[1:] if len(sys.argv) > 2 else (sys.argv[1].split() if len(sys.argv) > 1 else []))
