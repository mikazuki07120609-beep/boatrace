#!/usr/bin/env python3
"""払戻金(公式の競走成績ファイルから読み取ったもの)を、日ごとに data/pays/YYYYMMDD.json に置く。

  {"date": "2026-10-28", "venues": {"23": {"2": {"3t": [["4-1-5", 94190, 73]], "tan": [[4, 1800]], …}}}}
    3t: 3連単 [組み合わせ, 円(100円あたり), 人気]、3f: 3連複、2t: 2連単、2f: 2連複、kf: 拡連複、tan: 単勝 [枠, 円]、fuku: 複勝
裏水面ノートの「荒れ」(万舟=3連単が1万円以上)の学習と、答え合わせに使う。

  python3 scripts/pays.py --backfill 200 [--commit-every 25]   # まだない日を、新しい日から順に(Actions で)
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time

import fetch
import parse
from common import DATA, RAW, RESULTS, ROOT, load_json, save_json

PAYS = DATA / "pays"


def extract(results: dict) -> dict:
    """読み取った成績(parse_results の戻り値)から、場ごと・レースごとの払戻金を取り出す。"""
    out: dict = {}
    for code, v in results.get("venues", {}).items():
        for r in v.get("races", []):
            if r.get("pay"):
                out.setdefault(code, {})[str(r["no"])] = r["pay"]
    return out


def save(day: dt.date, results: dict) -> int:
    """その日の払戻金を保存する。保存したレースの数を返す。"""
    pv = extract(results)
    n = sum(len(x) for x in pv.values())
    if n:
        save_json(PAYS / f"{day:%Y%m%d}.json", {"date": day.isoformat(), "venues": pv})
    return n


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)


def push(msg: str) -> None:
    _git("add", "data/pays")
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
    todo = [d for d in days if not (PAYS / f"{d:%Y%m%d}.json").exists()][:limit]
    print(f"払戻金がまだない日: {len(todo)}日を取り込みます", flush=True)
    done = 0
    for i, d in enumerate(todo):
        log: list = []
        path = fetch.fetch_one("K", d, RAW, log)
        time.sleep(fetch.WAIT_SEC)
        if not path:
            print(f"{d}: 取れませんでした {log[-1:] }", flush=True)
            continue
        res = parse.parse_results(path.read_text(encoding="utf-8"))
        n = save(d, res)
        done += 1
        print(f"{d}: {n}レース", flush=True)
        if commit_every and done % commit_every == 0:
            push(f"払戻金の取り込み(過去分)〜{d} [skip ci]")
    push(f"払戻金の取り込み(過去分) {dt.date.today()} [skip ci]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0)
    ap.add_argument("--commit-every", type=int, default=25)
    a = ap.parse_args()
    if a.backfill:
        return backfill(a.backfill, a.commit_every)
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
