#!/usr/bin/env python3
"""直前情報・結果(live.yml)とオッズ(odds.yml)の取り込みを、止めないための見張り。

GitHub の予約の起動(cron)は、混んでいると数時間遅れたり、来なかったりする(2026-11-26 は朝6:40の起動が昼を過ぎても来ず、
午前のレースの直前情報を取りこぼした)。そこで、予約だけに任せず、
  - live.yml は夜も含めていつも1つ動かしておき、時間いっぱいまで動いたら自分で次を起こして引き継ぐ(--next)
  - それぞれの実行が、もう一方が止まっていないかを10分ごとに見て、止まっていれば起こす(watch)
  - 毎日の更新(update.yml)も、終わるときに同じように見る(引数なし)
同じ仕組みの実行は「同時に動くのは1つ・待つのは1つ」(concurrency)なので、重ねて起こしても2つは動かない。

  python3 scripts/keepalive.py                          # 止まっていれば起こす(live.yml はいつも、odds.yml は開催の時間帯だけ)
  python3 scripts/keepalive.py --next live.yml --since 1764123456   # 次の実行を起こす(始まってから10分たつまでは待つ)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time

from common import JST, PROGRAM, ROOT, load_json

MIN_RUN_SEC = 600            # これより早く終わった実行(何かの失敗)は、ここまで待ってから次を起こす(起こし続けないように)
ODDS_BEFORE = 40             # 最初のレースの締切の何分前から、オッズの取り込みを動かしておくか
ODDS_AFTER = 90              # 最後のレースの締切の何分後まで(遅れて始まったレースと、締切時オッズの取り直しの分)
ACTIVE = ("queued", "in_progress", "waiting", "pending", "requested")


def _gh(*a: str, timeout: int = 60) -> subprocess.CompletedProcess | None:
    if not os.environ.get("GH_TOKEN"):
        return None
    try:
        return subprocess.run(["gh", *a], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except Exception as ex:  # noqa: BLE001
        print("gh を動かせませんでした:", ex, flush=True)
        return None


def active(workflow: str) -> bool | None:
    """その仕組みの実行が、いま動いているか・待っているか。わからないとき(通信の失敗など)は None。"""
    r = _gh("run", "list", "--workflow", workflow, "--limit", "10", "--json", "status")
    if r is None or r.returncode != 0:
        return None
    try:
        return any(x.get("status") in ACTIVE for x in json.loads(r.stdout or "[]"))
    except ValueError:
        return None


def dispatch(workflow: str, tries: int = 3) -> bool:
    """その仕組みの実行を起こす(うまくいかなければ少し待って、もう一度)。"""
    for i in range(tries):
        r = _gh("workflow", "run", workflow, "--ref", "main")
        if r is None:
            return False
        if r.returncode == 0:
            print(f"{workflow} を起こしました", flush=True)
            return True
        print(f"{workflow} を起こせませんでした: {(r.stderr or '').strip()[:200]}", flush=True)
        if i + 1 < tries:
            time.sleep(20)
    return False


def ensure(workflow: str) -> bool:
    """止まっていれば起こす。起こしたら True。"""
    if active(workflow) is False:
        print(f"{workflow} が動いていないので起こします", flush=True)
        return dispatch(workflow)
    return False


def odds_hours(now: dt.datetime | None = None) -> bool:
    """今日のレースのオッズを取り込む時間帯か(最初の締切の少し前から、最後の締切の少しあとまで)。"""
    now = now or dt.datetime.now(JST)
    prog = load_json(PROGRAM / f"{now:%Y%m%d}.json", None) or {}
    times = [r["deadline"] for v in prog.get("venues", {}).values() for r in v.get("races", []) if r.get("deadline")]
    if not times:
        return False

    def at(hm: str) -> dt.datetime:
        hh, mm = map(int, hm.split(":"))
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return at(min(times)) - dt.timedelta(minutes=ODDS_BEFORE) <= now <= at(max(times)) + dt.timedelta(minutes=ODDS_AFTER)


def watch(now: dt.datetime | None = None) -> None:
    """live.yml はいつも、odds.yml は開催の時間帯だけ、止まっていれば起こす。"""
    ensure("live.yml")
    if odds_hours(now):
        ensure("odds.yml")


def next_run(workflow: str, since: float) -> int:
    """次の実行を起こして引き継ぐ。始まってから MIN_RUN_SEC たたずに終わったときは、そこまで待ってから。"""
    wait = MIN_RUN_SEC - (time.time() - since)
    if wait > 0:
        print(f"始まってから{(time.time() - since) / 60:.0f}分で終わったので、{wait / 60:.0f}分待ってから次を起こします", flush=True)
        time.sleep(wait)
    return 0 if dispatch(workflow) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--next", metavar="WORKFLOW", help="次の実行を起こして引き継ぐ")
    ap.add_argument("--since", type=float, default=0, help="この実行が始まった時刻(UNIX 秒)")
    a = ap.parse_args()
    if a.next:
        return next_run(a.next, a.since or time.time())
    watch()
    return 0


if __name__ == "__main__":
    sys.exit(main())
