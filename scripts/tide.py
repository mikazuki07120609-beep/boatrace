#!/usr/bin/env python3
"""潮の満ち引き(気象庁の潮位表の推算潮位)。裏水面ノートの「荒れる理由」と学習に使う。

潮位表のテキスト(1日1行): 毎時の潮位 3けた×24、年月日(2けたずつ)、地点記号、満潮の時刻と潮位 4組、干潮の時刻と潮位 4組。
  https://www.data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/{年}/{地点記号}.txt
取り込んだものは data/tide/{地点記号}_{年}.json に置く:
  {"code": "TK", "name": "東京", "year": 2026, "days": {"0101": {"h": [毎時の潮位(cm)×24], "hi": [["04:08", 169], …], "lo": [["09:01", 123], …]}}}

潮の満ち引きの差がある場(公式のレース場データの「干満差: あり」)だけ、いちばん近い潮位表の地点を当てる。
大村は大村湾の中に潮位表の地点がない(湾の外とは潮の時刻と大きさがずれる)ため入れていない。

  python3 scripts/tide.py --fetch 2025 2026      # Actions で(気象庁のサイトから取り込む)
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import sys
import time
import urllib.request

from common import DATA, load_json, save_json

TIDE = DATA / "tide"
URL = "https://www.data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/{year}/{code}.txt"
UA = "suimen-note/1.0 (+https://suimennote.com/)"
# 場コード → (潮位表の地点記号, 地点名)。いちばん近い地点(気象庁の潮位表掲載地点一覧から)
STATIONS = {
    "03": ("TK", "東京"), "04": ("TK", "東京"), "06": ("MI", "舞阪"), "14": ("KM", "小松島"), "15": ("TX", "多度津"),
    "16": ("J8", "与島"), "17": ("Q8", "広島"), "18": ("QA", "徳山"), "19": ("CF", "長府"), "20": ("N1", "日明"), "22": ("QF", "博多"),
}
NEAR_MIN = 45            # 満潮・干潮の前後この分のうちは「満潮前後」「干潮前後」
PHASES = ["上げ潮", "下げ潮", "満潮前後", "干潮前後"]


def parse_text(text: str, code: str) -> dict:
    """潮位表のテキストを、日ごとの毎時の潮位と満潮・干潮に。"""
    days = {}
    for line in text.splitlines():
        if len(line) < 136 or line[78:80] != code:
            continue
        try:
            h = [int(line[i * 3:i * 3 + 3]) for i in range(24)]
            mm, dd = int(line[74:76]), int(line[76:78])
        except ValueError:
            continue

        def events(start):
            out = []
            for k in range(4):
                s = line[start + k * 7:start + k * 7 + 7]
                t, v = s[:4], s[4:]
                if t.strip() == "9999" or v.strip() == "999":
                    continue
                try:
                    hh, mi, cm = int(t[:2]), int(t[2:]), int(v)
                except ValueError:
                    continue
                out.append([f"{hh:02d}:{mi:02d}", cm])
            return out
        days[f"{mm:02d}{dd:02d}"] = {"h": h, "hi": events(80), "lo": events(108)}
    return days


def fetch(years: list[int]) -> int:
    codes = sorted({c for c, _ in STATIONS.values()})
    names = {c: n for c, n in STATIONS.values()}
    n = 0
    for y in years:
        for code in codes:
            req = urllib.request.Request(URL.format(year=y, code=code), headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    text = r.read().decode("utf-8", errors="replace")
            except Exception as ex:  # noqa: BLE001
                print(f"{y} {code}: 取れませんでした {ex}", flush=True)
                continue
            days = parse_text(text, code)
            if len(days) >= 300:
                save_json(TIDE / f"{code}_{y}.json", {"code": code, "name": names[code], "year": y, "days": days})
                n += 1
            print(f"{y} {code}({names[code]}): {len(days)}日", flush=True)
            time.sleep(2)
    return n


def ensure(today: dt.date) -> None:
    """今年(12月は来年も)の潮位表がまだなければ取り込む(毎日の更新から)。"""
    years = [today.year] + ([today.year + 1] if today.month == 12 else [])
    codes = sorted({c for c, _ in STATIONS.values()})
    need = [y for y in years if any(not (TIDE / f"{c}_{y}.json").exists() for c in codes)]
    if need:
        fetch(need)


# ---------------------------------------------------------------- 使う側(サイトを作るとき・学習)
_CACHE: dict = {}


def _year(code: str, y: int) -> dict | None:
    k = (code, y)
    if k not in _CACHE:
        _CACHE[k] = load_json(TIDE / f"{code}_{y}.json", None)
    return _CACHE[k]


def _day(code: str, d: dt.date) -> dict | None:
    Y = _year(code, d.year)
    return ((Y or {}).get("days") or {}).get(f"{d:%m%d}")


def _events(code: str, d: dt.date) -> list:
    """前の日から次の日までの満潮・干潮(分の通し番号, 'hi'/'lo', 潮位)。"""
    out = []
    for k in (-1, 0, 1):
        dd = d + dt.timedelta(days=k)
        x = _day(code, dd)
        if not x:
            continue
        for kind in ("hi", "lo"):
            for t, cm in x.get(kind) or []:
                hh, mi = map(int, t.split(":"))
                out.append((k * 1440 + hh * 60 + mi, kind, cm))
    out.sort()
    return out


def level(code: str, d: dt.date, minute: float) -> float | None:
    """その時刻の潮位(cm。毎時の値をつないだもの)。"""
    x = _day(code, d)
    if not x:
        return None
    h = x["h"]
    i = int(minute // 60)
    f = (minute - i * 60) / 60
    if i >= 23:
        nx = _day(code, d + dt.timedelta(days=1))
        return h[23] + f * (((nx or {}).get("h") or [h[23]])[0] - h[23])
    return h[i] + f * (h[i + 1] - h[i])


def at(venue: str, d: dt.date, hhmm: str | None) -> dict | None:
    """その場・その時刻の潮(潮の満ち引きの差がある場だけ)。
    ph: 上げ潮/下げ潮/満潮前後/干潮前後、h: 潮位(cm)、dh: 1時間あたりの変化(cm)、rg: その日の干満の差(cm)、
    hi/lo: その時刻のあとの満潮・干潮 [時刻, 潮位]、st: 地点名"""
    s = STATIONS.get(venue)
    if not s or not hhmm:
        return None
    code, name = s
    try:
        hh, mi = map(int, hhmm.split(":"))
    except ValueError:
        return None
    m = hh * 60 + mi
    ev = _events(code, d)
    if not ev:
        return None
    times = [e[0] for e in ev]
    j = bisect.bisect_left(times, m)
    prev = ev[j - 1] if j > 0 else None
    nxt = ev[j] if j < len(ev) else None
    if not prev or not nxt:
        return None
    near = min((e for e in (prev, nxt)), key=lambda e: abs(e[0] - m))
    if abs(near[0] - m) <= NEAR_MIN:
        ph = "満潮前後" if near[1] == "hi" else "干潮前後"
    else:
        ph = "上げ潮" if nxt[1] == "hi" else "下げ潮"
    h0, h1 = level(code, d, max(0, m - 30)), level(code, d, min(1439, m + 30))
    today = [e for e in ev if 0 <= e[0] < 1440]
    his = [e[2] for e in today if e[1] == "hi"]
    los = [e[2] for e in today if e[1] == "lo"]
    rg = (max(his) - min(los)) if his and los else None

    def hm(e):
        mm_ = e[0] % 1440
        return f"{mm_ // 60:02d}:{mm_ % 60:02d}"
    nhi = next((e for e in ev[j:] if e[1] == "hi"), None)
    nlo = next((e for e in ev[j:] if e[1] == "lo"), None)
    lv = level(code, d, m)
    return {"st": name, "ph": ph, "h": round(lv) if lv is not None else None,
            "dh": round(h1 - h0) if h0 is not None and h1 is not None else None, "rg": rg,
            "hi": [hm(nhi), nhi[2]] if nhi else None, "lo": [hm(nlo), nlo[2]] if nlo else None,
            "ev": [hm(near), near[2]] if abs(near[0] - m) <= NEAR_MIN else None}   # 満潮前後・干潮前後のときの、その満潮・干潮


def range_level(venue: str, rg) -> str | None:
    """その日の干満の差が、その地点のふだん(1年)と比べて大きいか(大きい/ふつう/小さい)。"""
    s = STATIONS.get(venue)
    if not s or rg is None:
        return None
    key = ("q", s[0])
    if key not in _CACHE:
        rs = []
        for p in sorted(TIDE.glob(f"{s[0]}_*.json")):
            Y = load_json(p, {}) or {}
            for x in (Y.get("days") or {}).values():
                if x.get("hi") and x.get("lo"):
                    rs.append(max(c for _, c in x["hi"]) - min(c for _, c in x["lo"]))
        rs.sort()
        _CACHE[key] = (rs[len(rs) // 3], rs[2 * len(rs) // 3]) if len(rs) >= 30 else None
    q = _CACHE[key]
    if not q:
        return None
    return "大きい" if rg >= q[1] else "小さい" if rg < q[0] else "ふつう"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", nargs="*", type=int)
    a = ap.parse_args()
    if a.fetch:
        print(f"{fetch(a.fetch)}ファイルを保存しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
