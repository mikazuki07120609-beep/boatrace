#!/usr/bin/env python3
"""直前情報(展示タイム・チルト・部品交換・体重・スタート展示・水面気象)を取り込む。

公式の配布ファイル(番組表・競走成績)には直前情報がないので、BOAT RACE オフィシャルウェブサイトの
直前情報のページを読みに行く。サーバーに負担をかけないよう、
  - 締切が近く、まだ取れていないレースだけを読む(1レースにつき、取れるまで多くても数回)
  - 1回の実行で読むページ数に上限を設け、読むたびに数秒あける
取り込んだ内容は data/before/YYYYMMDD.json に保存し、レースのページの見立てと映像に使う。

  python3 scripts/beforeinfo.py               # 締切が近いレース(GitHub Actions で10分ごと)
  python3 scripts/beforeinfo.py --day 20261021 --all   # その日のまだ取っていないレースを全部(答え合わせと学習用)
  python3 scripts/beforeinfo.py --parse FILE  # 保存したページを読み取って表示(確認用)
"""
import argparse
import datetime as dt
import html as htmlmod
import json
import re
import sys
import time
import urllib.request

from common import DATA, PROGRAM, JST, load_json, save_json

BEFORE = DATA / "before"
URL = "https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno={no}&jcd={jcd}&hd={ymd}"
UA = "suimen-note/1.0 (+https://mikazuki07120609-beep.github.io/boatrace/)"
WAIT_SEC = 3            # 読むたびにあける秒数
MAX_PER_RUN = 40        # 1回の実行で読むページ数の上限
WINDOW_MIN = (1, 32)    # 締切の何分前から何分前までのレースを読みに行くか(展示はおおむね締切の20分前ごろ)
MAX_TRIES = 4           # まだ出ていないときに読みに行く回数の上限


def _text(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return htmlmod.unescape(s).replace("　", " ").strip()


def _num(s: str):
    try:
        return float(_text(s).replace("kg", "").strip())
    except ValueError:
        return None


def _st(s: str):
    """スタート展示のST(".09"、フライングは "F.03" → -0.03)。読めなければ None。"""
    t = _text(s)
    m = re.fullmatch(r"(F)?\s*(\d?)\.(\d{2})", t)
    if not m:
        return None
    v = float(f"{m.group(2) or 0}.{m.group(3)}")
    return -v if m.group(1) else v


def parse(page: str) -> dict | None:
    """直前情報のページを読み取る。まだ出ていなければ None。"""
    if "データがありません" in page or "is-boatColor1" not in page:
        return None
    out = {"ex": {}, "tilt": {}, "prop": {}, "parts": {}, "weight": {}, "adj": {}, "course": [], "est": {}, "weather": {}}
    for tb in re.findall(r'<tbody class="is-fs12[^"]*">(.*?)</tbody>', page, re.S):
        m = re.search(r"is-boatColor(\d)", tb)
        if not m:
            continue
        w = m.group(1)
        trs = re.findall(r"<tr>(.*?)</tr>", tb, re.S)
        if not trs:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", trs[0], re.S)
        if len(tds) < 8:
            continue
        out["weight"][w] = _num(tds[3])
        out["ex"][w] = _num(tds[4])
        out["tilt"][w] = _num(tds[5])
        out["prop"][w] = _text(tds[6])
        out["parts"][w] = [_text(x) for x in re.findall(r'<span class="label4[^"]*">(.*?)</span>', tds[7], re.S)]
        if len(trs) >= 3:
            t3 = re.findall(r"<td[^>]*>(.*?)</td>", trs[2], re.S)
            if t3:
                out["adj"][w] = _num(t3[0])
    # スタート展示(上から1コース、2コース…の順)
    for num, st in re.findall(r'table1_boatImage1Number is-type\d">(\d)</span>.*?table1_boatImage1Time">(.*?)</span>', page, re.S):
        out["course"].append(int(num))
        out["est"][num] = _st(st)
    # 水面気象
    W = out["weather"]
    m = re.search(r"水面気象情報\s*(\d{1,2}:\d{2})", page)
    W["at"] = m.group(1) if m else None
    for unit, key in (("is-direction", "temp"), ("is-wind", "wind"), ("is-waterTemperature", "water"), ("is-wave", "wave")):
        m = re.search(r'weather1_bodyUnit %s">.*?weather1_bodyUnitLabelData">(.*?)</span>' % unit, page, re.S)
        if m:
            v = re.sub(r"[^\d.\-]", "", _text(m.group(1)))
            W[key] = float(v) if v not in ("", ".", "-") else None
    m = re.search(r'weather1_bodyUnit is-weather">.*?weather1_bodyUnitLabelTitle">(.*?)</span>', page, re.S)
    W["weather"] = _text(m.group(1)) if m else None
    m = re.search(r"is-wind(\d+)\"", page)
    W["wind_icon"] = int(m.group(1)) if m else None           # 風向の矢印(場の図に対する向き。1〜16)
    m = re.search(r"is-direction(\d+)\"", page)
    W["dir_icon"] = int(m.group(1)) if m else None
    if not out["ex"]:
        return None
    return out


def fetch(jcd: str, no: int, ymd: str) -> str | None:
    req = urllib.request.Request(URL.format(no=no, jcd=jcd, ymd=ymd), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as ex:  # noqa: BLE001  通信の失敗は次の回にまわす
        print("直前情報を読めませんでした:", jcd, no, ex)
        return None


def due_races(prog: dict, now: dt.datetime, everything: bool):
    """読みに行くレース(締切が近いもの。everything なら全部)。締切の近い順。"""
    out = []
    for code, v in prog.get("venues", {}).items():
        for race in v.get("races", []):
            dl = race.get("deadline")
            if not dl:
                continue
            hh, mm = map(int, dl.split(":"))
            dline = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            mins = (dline - now).total_seconds() / 60
            if everything or WINDOW_MIN[0] <= mins <= WINDOW_MIN[1]:
                out.append((mins, code, race["no"]))
    out.sort()
    return out


def run(day: dt.date, everything: bool, now: dt.datetime | None = None) -> int:
    prog = load_json(PROGRAM / f"{day:%Y%m%d}.json", None)
    if not prog:
        print("番組表がないので、直前情報は取りません:", day)
        return 0
    now = now or dt.datetime.now(JST)
    if everything:
        now = dt.datetime.combine(day, dt.time(0, 0), tzinfo=JST)
    path = BEFORE / f"{day:%Y%m%d}.json"
    log = load_json(path, None) or {"date": day.isoformat(), "venues": {}}
    tries = log.setdefault("tries", {})
    got = 0
    n = 0
    for mins, code, no in due_races(prog, now, everything):
        key = f"{code}-{no}"
        if str(no) in log["venues"].get(code, {}):
            continue
        if tries.get(key, 0) >= (1 if everything else MAX_TRIES):
            continue
        if n >= MAX_PER_RUN:
            break
        if n:
            time.sleep(WAIT_SEC)
        n += 1
        tries[key] = tries.get(key, 0) + 1
        page = fetch(code, no, f"{day:%Y%m%d}")
        info = parse(page) if page else None
        if info:
            info["fetched"] = dt.datetime.now(JST).strftime("%H:%M")
            log["venues"].setdefault(code, {})[str(no)] = info
            got += 1
    if n:
        save_json(path, log)
    print(f"直前情報: {day} {n}ページを読み、{got}レース分を取り込みました")
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--parse")
    a = ap.parse_args()
    if a.parse:
        print(json.dumps(parse(open(a.parse, encoding="utf-8").read()), ensure_ascii=False, indent=1))
        return 0
    day = dt.datetime.strptime(a.day, "%Y%m%d").date() if a.day else dt.datetime.now(JST).date()
    run(day, a.all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
