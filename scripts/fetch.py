#!/usr/bin/env python3
"""公式の番組表(B)・競走成績(K)ファイルをダウンロードして解凍し、UTF-8のテキストで保存する。

使い方:
  python3 scripts/fetch.py --kind B --date 20261021 --out data/raw
  python3 scripts/fetch.py --sample --out sample   # 動作確認用(今日・明日の番組表と、昨日・一昨日の成績)

公式サーバーに負担をかけないよう、1ファイルごとに間隔をあけて取得する。
"""
import argparse
import datetime as dt
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
UA = "boatrace-site/0.1 (+https://github.com/mikazuki07120609-beep/boatrace)"
HOSTS = ["https://www1.mbrace.or.jp", "http://www1.mbrace.or.jp"]
WAIT_SEC = 3


def urls_for(kind: str, day: dt.date):
    path = f"/od2/{kind}/{day:%Y%m}/{kind.lower()}{day:%y%m%d}.lzh"
    return [h + path for h in HOSTS]


def download(day: dt.date, kind: str, dest: pathlib.Path, log: list) -> bool:
    for url in urls_for(kind, day):
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=40) as r:
                    data = r.read()
                    ctype = r.headers.get("Content-Type", "")
                if len(data) < 64 or b"<html" in data[:200].lower():
                    log.append(f"{url} -> 200 だが中身がLZHではない ({len(data)} bytes, {ctype})")
                    break
                dest.write_bytes(data)
                log.append(f"{url} -> OK {len(data)} bytes")
                return True
            except urllib.error.HTTPError as e:
                log.append(f"{url} -> HTTP {e.code}")
                if e.code in (403, 404):
                    break
            except Exception as e:  # noqa: BLE001
                log.append(f"{url} -> {type(e).__name__}: {e}")
            time.sleep(WAIT_SEC * (attempt + 1))
    return False


def extract(lzh: pathlib.Path, log: list) -> bytes | None:
    """LZHを解凍して、中のテキストファイルの中身(Shift_JISのまま)を返す。"""
    attempts = []
    if shutil.which("lha"):
        attempts += [["lha", "-xw={dir}", str(lzh)], ["lha", "xw={dir}", str(lzh)]]
    if shutil.which("7z"):
        attempts += [["7z", "x", "-y", "-o{dir}", str(lzh)]]
    for cmd in attempts:
        with tempfile.TemporaryDirectory() as td:
            real = [c.replace("{dir}", td) for c in cmd]
            res = subprocess.run(real, capture_output=True, text=True)
            files = [p for p in pathlib.Path(td).rglob("*") if p.is_file()]
            if res.returncode == 0 and files:
                log.append(f"解凍OK: {' '.join(cmd[:2])} -> {[f.name for f in files]}")
                return b"".join(f.read_bytes() for f in sorted(files))
            log.append(f"解凍失敗: {' '.join(cmd[:2])} rc={res.returncode} {res.stderr.strip()[:200]}")
    try:
        import lhafile  # type: ignore

        arc = lhafile.Lhafile(str(lzh))
        names = arc.namelist()
        log.append(f"解凍OK: lhafile -> {names}")
        return b"".join(arc.read(n) for n in names)
    except Exception as e:  # noqa: BLE001
        log.append(f"解凍失敗: lhafile {type(e).__name__}: {e}")
    return None


def fetch_one(kind: str, day: dt.date, out: pathlib.Path, log: list) -> pathlib.Path | None:
    out.mkdir(parents=True, exist_ok=True)
    target = out / kind / f"{day:%Y%m%d}.txt"
    if target.exists() and target.stat().st_size > 0:
        log.append(f"{kind} {day} は取得済み")
        return target
    with tempfile.TemporaryDirectory() as td:
        lzh = pathlib.Path(td) / "f.lzh"
        if not download(day, kind, lzh, log):
            return None
        raw = extract(lzh, log)
    if raw is None:
        return None
    text = raw.decode("cp932", errors="replace").replace("\r\n", "\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    log.append(f"保存: {target} ({len(text)} 文字)")
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["B", "K"])
    ap.add_argument("--date", action="append", default=[], help="YYYYMMDD(複数可)")
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--sample", action="store_true")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    log: list[str] = []
    today = dt.datetime.now(JST).date()
    jobs: list[tuple[str, dt.date]] = []
    if a.sample:
        jobs = [("B", today), ("B", today + dt.timedelta(days=1)),
                ("K", today - dt.timedelta(days=1)), ("K", today - dt.timedelta(days=2))]
    else:
        if not a.kind or not a.date:
            ap.error("--kind と --date を指定してください")
        jobs = [(a.kind, dt.datetime.strptime(d, "%Y%m%d").date()) for d in a.date]
    ok = 0
    for i, (kind, day) in enumerate(jobs):
        if i:
            time.sleep(WAIT_SEC)
        if fetch_one(kind, day, out, log):
            ok += 1
    log.append(f"完了: {ok}/{len(jobs)} ファイル (JST {dt.datetime.now(JST):%Y-%m-%d %H:%M})")
    print("\n".join(log))
    if a.sample:
        (out / "fetch-log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
