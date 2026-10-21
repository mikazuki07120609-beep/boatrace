"""モーター評価(S〜E)。

公式のモーター2連率は、乗った選手の腕前も混ざった数字なので、次の3つを合わせて評価する。
  1) 直近60日の成績から、乗った選手の勝率とコースの有利不利を差し引いた分(このモーターで、いつもより着順が良いか)
  2) 直近60日の展示タイムが、同じレースの他の艇より速いか
  3) 公式のモーター2連率(その場のモーターの中での位置)
レースの直前には、そのレースの展示タイム(他の艇との差)も加えて評価し直す(race.js)。
過去30日で確かめると、1)と2)はどちらも次のレースの着順と関係があり、当日の展示タイムを加えると一番よく当たる。
"""
import datetime as dt
import math
import statistics

from common import RESULTS, load_json, parse_ymd
from stats import POINTS, races_of

MOTOR_DAYS = 60
BETA = 0.9            # 選手の勝率が1点高いと、着順点がどれだけ上がるとみなすか
K_RES, K_EX = 12, 8   # 走数が少ないモーターを平均に寄せる強さ
W_BASE = (0.45, 0.30, 0.25)       # 成績の上ぶれ・展示の速さ・公式の2連率
W_LIVE = 0.45                      # 直前の展示タイムの重み(残りはここまでの評価)
EX_SD = 0.047                      # 同じレースの中での展示タイムの差のばらつき(秒)
GRADES = [(1.4, "S"), (0.65, "A"), (0.0, "B"), (-0.65, "C"), (-1.4, "D")]


def grade(z: float) -> str:
    for t, g in GRADES:
        if z >= t:
            return g
    return "E"


def raw_scores(day: dt.date, racers: dict) -> dict:
    """場ごと・モーター番号ごとの [成績の上ぶれの合計, 走数, 展示の速さの合計, 展示の走数]。"""
    rows = []
    for p in sorted(RESULTS.glob("*.json")):
        d = parse_ymd(p.stem)
        if day - dt.timedelta(days=MOTOR_DAYS) <= d < day:
            rows.append(load_json(p, {}) or {})
    # 場ごと・コースごとの平均の着順点
    cm: dict = {}
    for res in rows:
        for code, v in res.get("venues", {}).items():
            for race in races_of(v):
                for x in race["entries"]:
                    if x.get("rank") and x.get("course"):
                        a = cm.setdefault((code, x["course"]), [0.0, 0])
                        a[0] += POINTS[x["rank"]]
                        a[1] += 1

    def cmean(code, c):
        s, n = cm.get((code, c), (0.0, 0))
        return (s + 5.17 * 20) / (n + 20)

    def rmean(toban):
        s, n = (racers.get(toban) or {}).get("pts", [0, 0])
        return (s + 5.17 * 10) / (n + 10)

    out: dict = {}
    for res in rows:
        for code, v in res.get("venues", {}).items():
            for race in races_of(v):
                exs = [x["ex"] for x in race["entries"] if x.get("ex")]
                exm = sum(exs) / len(exs) if len(exs) >= 5 else None
                for x in race["entries"]:
                    if x.get("motor") is None:
                        continue
                    a = out.setdefault(code, {}).setdefault(str(x["motor"]), [0.0, 0, 0.0, 0])
                    if x.get("rank") and x.get("course"):
                        a[0] += POINTS[x["rank"]] - cmean(code, x["course"]) - BETA * (rmean(x["toban"]) - 5.17)
                        a[1] += 1
                    if exm and x.get("ex"):
                        a[2] += exm - x["ex"]          # 速いほど大きい
                        a[3] += 1
    return out


RATE_DAYS = 180


def motor_rates(day: dt.date) -> dict:
    """場ごと・モーター番号ごとの、直近180日の成績の2連率(%)。見立てのモデルが学習に使うのと同じ式(fit.py の motor_rate)。"""
    acc: dict = {}
    for p in sorted(RESULTS.glob("*.json")):
        d = parse_ymd(p.stem)
        if not (day - dt.timedelta(days=RATE_DAYS) <= d < day):
            continue
        for code, v in (load_json(p, {}) or {}).get("venues", {}).items():
            for race in races_of(v):
                for x in race["entries"]:
                    if x.get("motor") is None or not (x.get("rank") or x.get("status")):
                        continue
                    a = acc.setdefault(code, {}).setdefault(str(x["motor"]), [0, 0])
                    a[0] += 1
                    a[1] += 1 if x.get("rank") in (1, 2) else 0
    return {c: {k: round((t + 10 / 3) / (n + 10) * 100, 2) for k, (n, t) in v.items() if n} for c, v in acc.items()}


def _z(vals: dict) -> dict:
    xs = [v for v in vals.values() if v is not None]
    if len(xs) < 3:
        return {k: 0.0 for k in vals}
    m, s = statistics.mean(xs), statistics.pstdev(xs) or 1.0
    return {k: (0.0 if v is None else (v - m) / s) for k, v in vals.items()}


def venue_grades(code: str, vprog: dict, raw: dict) -> dict:
    """その日の番組表に出てくるモーターの評価 {番号: {z, grade, n, res, ex}}。"""
    m2 = {}
    for race in vprog.get("races", []):
        for x in race["entries"]:
            if x.get("motor") is not None:
                m2[str(x["motor"])] = x.get("motor2")
    rv = raw.get(code, {})
    res = {k: (rv[k][0] / (rv[k][1] + K_RES) if k in rv else 0.0) for k in m2}
    exd = {k: (rv[k][2] / (rv[k][3] + K_EX) if k in rv else 0.0) for k in m2}
    zr, ze, zm = _z(res), _z(exd), _z(m2)
    base = {k: W_BASE[0] * zr[k] + W_BASE[1] * ze[k] + W_BASE[2] * zm[k] for k in m2}
    zb = _z(base)
    out = {}
    for k in m2:
        n = rv[k][1] if k in rv else 0
        out[k] = {"z": round(zb[k], 3), "grade": grade(zb[k]), "n": n,
                  "res": round(res[k], 2), "ex": round(exd[k], 3)}
    return out


def live_z(zb: float, ex_dev: float | None) -> float:
    """直前の展示タイム(レースの平均より何秒速いか)を加えた評価。"""
    if ex_dev is None:
        return zb
    zt = max(-3.0, min(3.0, ex_dev / EX_SD))
    return ((1 - W_LIVE) * zb + W_LIVE * zt) / math.hypot(1 - W_LIVE, W_LIVE)
