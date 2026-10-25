#!/usr/bin/env python3
"""開催のグレード(SG・G1・G2・G3・一般と、女子戦などの印)と、女子レーサーの登番を公式サイトから取り込む。

  - グレード: BOAT RACE オフィシャルウェブサイトの「本日のレース」(日付ごとの一覧)にある、場ごとのグレードの印から。
    data/grades.json に {日付: {場コード: [グレード, 印...]}}。印は "lady"(オールレディース)・"venus"(ヴィーナスシリーズ)・"rookie"(ルーキーシリーズ)。
  - 女子レーサー: 公式の「選手期別成績」(ファン手帳のデータ。半年ごと)の性別の欄から。data/fem.json。
    新しい期のファイルが出たら取り直す。ファイルが出たあとにデビューした選手は、次のファイルまで入らない。
出走表の「この開催のグレード(女子戦)のコース成績」と、女子レーサーの印に使う。
公式サーバーへの負担を抑えるため、1回の実行で取りに行くページの数に上限を設け、ページの間をあける。

  python3 scripts/grades.py --backfill 30   # 今日・明日と、まだない過去の日を30日分
"""
import argparse
import datetime as dt
import pathlib
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from common import DATA, PROGRAM, VENUES, load_json, save_json, today_jst

GRADES = DATA / "grades.json"
FEM = DATA / "fem.json"
UA = "suimen-note/1.0 (+https://mikazuki07120609-beep.github.io/boatrace/)"
INDEX_URL = "https://www.boatrace.jp/owpc/pc/race/index?hd={ymd}"
FAN_URL = "https://www.boatrace.jp/static_extra/pc_static/download/data/kibetsu/{name}.lzh"
WAIT_SEC = 2.5
KEEP_DAYS = 372
NAME2CODE = {v: k for k, v in VENUES.items()}
GRADE_RE = re.compile(r"is-(SG|PG1|G1|G2|G3|ippan)")
GRADE_NAME = {"SG": "SG", "PG1": "G1", "G1": "G1", "G2": "G2", "G3": "G3", "ippan": "一般"}


def _get(url: str, log: list) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        log.append(f"{url} -> HTTP {e.code}")
    except Exception as e:  # noqa: BLE001
        log.append(f"{url} -> {type(e).__name__}: {e}")
    return None


def parse_index(page: str) -> dict:
    """「本日のレース」のページから {場コード: [グレード, 印...]}。"""
    out = {}
    for tb in re.findall(r"<tbody>(.*?)</tbody>", page, re.S):
        m = re.search(r'alt="([^"]+)"', tb)
        code = NAME2CODE.get(m.group(1).strip()) if m else None
        if not code:
            continue
        cls = " ".join(re.findall(r'<td rowspan="2" class="([^"]*)"', tb))
        g = GRADE_RE.search(cls)
        if not g:
            continue
        out[code] = [GRADE_NAME[g.group(1)]] + [f for f in ("lady", "venus", "rookie") if "is-" + f in cls]
    return out


def update_grades(today: dt.date, backfill: int, log: list) -> int:
    G = load_json(GRADES, {}) or {}
    todo = []
    for d in (today, today + dt.timedelta(days=1)):          # 今日と明日は、番組表の場がそろうまで取り直す
        key = f"{d:%Y%m%d}"
        prog = load_json(PROGRAM / f"{key}.json", {}) or {}
        want = set(prog.get("venues", {}))
        if not G.get(key) or (want and not want <= set(G[key])):
            todo.append(d)
    n = 0
    for i in range(1, 366):                                  # 過去の日は、まだないものを少しずつ
        if n >= backfill:
            break
        d = today - dt.timedelta(days=i)
        if f"{d:%Y%m%d}" not in G:
            todo.append(d)
            n += 1
    got = 0
    for d in todo:
        page = _get(INDEX_URL.format(ymd=f"{d:%Y%m%d}"), log)
        time.sleep(WAIT_SEC)
        if not page:
            continue
        g = parse_index(page.decode("utf-8", "replace"))
        if g or d < today:                                    # 開催がなかった日も、取ったことを残す(何度も取りに行かない)
            G[f"{d:%Y%m%d}"] = g
            got += 1
    cutoff = f"{today - dt.timedelta(days=KEEP_DAYS):%Y%m%d}"
    G = {k: v for k, v in G.items() if k >= cutoff}
    save_json(GRADES, dict(sorted(G.items())))
    log.append(f"グレード: {got}日分を取り込み(全{len(G)}日)")
    return got


def fan_names(today: dt.date) -> list:
    """選手期別成績のファイル名の候補(新しい順)。fanYYMM の MM は期の終わりの月(04・10)。"""
    out = []
    for y in (today.year, today.year - 1):
        for mo in (10, 4):
            if dt.date(y, mo, 1) <= today:
                out.append(f"fan{y % 100:02d}{mo:02d}")
    return out


def parse_fan(text: str) -> list:
    """選手期別成績のテキスト(1行1選手)から、女子レーサーの登番。性別は先頭から39文字目(1: 男性、2: 女性)。"""
    fem = []
    for line in text.splitlines():
        if len(line) > 40 and line[:4].isdigit() and line[38] == "2":
            fem.append(line[:4])
    return sorted(set(fem))


def update_fem(today: dt.date, log: list) -> bool:
    F = load_json(FEM, {}) or {}
    if F.get("checked") == today.isoformat():
        return False
    have = F.get("file") or ""
    for name in fan_names(today):
        if name <= have:
            break                                             # 持っているものより新しいファイルはまだない
        data = _get(FAN_URL.format(name=name), log)
        time.sleep(WAIT_SEC)
        if not data:
            continue
        with tempfile.TemporaryDirectory() as td:
            arc = pathlib.Path(td) / f"{name}.lzh"
            arc.write_bytes(data)
            out = pathlib.Path(td) / "x"
            if not shutil.which("lha"):
                log.append("選手期別成績: 解凍ツール(lha)がありません")
                return False
            subprocess.run(["lha", f"-xw={out}", str(arc)], capture_output=True)
            files = [p for p in out.rglob("*") if p.is_file()] if out.exists() else []
            if not files:
                log.append(f"選手期別成績 {name}: 解凍できませんでした")
                continue
            text = b"".join(p.read_bytes() for p in files).decode("cp932", "replace")
        fem = parse_fan(text)
        lines = len(text.splitlines())
        if lines < 1000 or not 80 <= len(fem) <= 500:          # 形が変わっていたら使わない
            log.append(f"選手期別成績 {name}: 読み取りがおかしいので使いません({lines}行・女子{len(fem)}人)")
            continue
        save_json(FEM, {"file": name, "checked": today.isoformat(), "fem": fem})
        log.append(f"選手期別成績 {name}: 女子レーサー{len(fem)}人")
        return True
    F["checked"] = today.isoformat()
    save_json(FEM, F)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=20)
    a = ap.parse_args()
    log: list = []
    today = today_jst()
    update_fem(today, log)
    update_grades(today, a.backfill, log)
    print("\n".join(log))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
