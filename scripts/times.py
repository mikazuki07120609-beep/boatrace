#!/usr/bin/env python3
"""レースの締切予定時刻(番組表から)を、日ごとに data/times/YYYYMMDD.json に置く。

  {"date": "2026-10-28", "venues": {"23": ["10:45", "11:12", …]}}   … 1R から順に
裏水面ノートで、潮の満ち引き(潮位表)とレースの時刻を合わせるのに使う(過去のレースの、そのときの潮)。
番組表のファイルは数日で消すので、時刻だけを残しておく。

  python3 scripts/times.py --backfill 400 [--commit-every 50]   # まだない日を、新しい日から順に(Actions で)
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time

import fetch
import parse
from common import DATA, RAW, RESULTS, ROOT, save_json

TIMES = DATA / "times"


def save(day: dt.date, prog: dict) -> int:
    """番組表(parse_program の戻り値)から、場ごとの締切予定時刻を保存する。保存したレースの数を返す。"""
    out = {}
    for code, v in (prog.get("venues") or {}).items():
        rs = sorted(v.get("races", []), key=lambda r: r["no"])
        if rs:
            out[code] = [r.get("deadline") for r in rs]
    n = sum(len(x) for x in out.values())
    if n:
        save_json(TIMES / f"{day:%Y%m%d}.json", {"date": day.isoformat(), "venues": out})
    return n


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)


def push(msg: str) -> None:
    _git("add", "data/times")
    if _git("diff", "--cached", "--quiet").returncode == 0:
        return
    _git("commit", "-q", "-m", msg)
    for _ in range(4):
        if _git("pull", "--rebase", "-q", "origin", "main").returncode != 0:
            _git("rebase", "--abort")
            _git("pull", "--rebase", "-X", "theirs", "-q", "origin", "main")
        if _git("push", "-q").returncode == 0:
            return
        time.sleep(5)
    print("送れませんでした", flush=True)


def backfill(limit: int, commit_every: int) -> int:
    days = sorted((dt.datetime.strptime(p.stem, "%Y%m%d").date() for p in RESULTS.glob("*.json")), reverse=True)
    todo = [d for d in days if not (TIMES / f"{d:%Y%m%d}.json").exists()][:limit]
    print(f"締切時刻がまだない日: {len(todo)}日を取り込みます", flush=True)
    done = 0
    for d in todo:
        log: list = []
        path = fetch.fetch_one("B", d, RAW, log)
        time.sleep(fetch.WAIT_SEC)
        if not path:
            print(f"{d}: 取れませんでした {log[-1:]}", flush=True)
            continue
        n = save(d, parse.parse_program(path.read_text(encoding="utf-8")))
        done += 1
        print(f"{d}: {n}レース", flush=True)
        if commit_every and done % commit_every == 0:
            push(f"締切時刻の取り込み(過去分)〜{d} [skip ci]")
    push(f"締切時刻の取り込み(過去分) {dt.date.today()} [skip ci]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0)
    ap.add_argument("--commit-every", type=int, default=50)
    a = ap.parse_args()
    if a.backfill:
        return backfill(a.backfill, a.commit_every)
    return 0


if __name__ == "__main__":
    sys.exit(main())
