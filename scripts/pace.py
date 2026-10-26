"""展示とレースのタイムから、直前情報の推定タイム(一周・まわり足)と、展示タイム1位の艇の1着率を作る。

公式のデータには、展示航走の一周タイム・まわり足タイムはないので、競走成績のレースタイム(3周)から推定する。
  - レースのペース: 同じレースの完走艇の平均より、何秒速く・遅く回ったか(着順ごとの平均の差を引く。先頭は波のない水面を走れるため)
  - モーター(直近60日)・選手(直近1年)ごとに、そのずれを平均する(走数が少ないほど0に寄せる)
  - 展示タイムが同じレースの平均より速いと、どれだけペースが速いか(β)も同じデータから求める
  - 一周(推定) = その場の標準の一周 + モーターと選手のずれ ÷ 3 + β × 展示タイムの差 ÷ 3
  - まわり足(推定) = モーターと選手のずれのうち、展示タイム(直線の速さ)では説明できない分 ÷ 3(旋回の速さの目安)
展示タイム1位の成績: 6艇とも展示タイムがあるレースで、一番速かった艇(同タイムは全部)の回数と、1着・2着・3着になった回数。
  [回数, 1着, 2着, 3着] の形。全国・コース別(直近半年)と、選手ごと・コース別(直近1年。そのレースの展示タイム1位の選手の成績に使う)。
"""
import datetime as dt
import statistics

from common import RESULTS, load_json, parse_ymd
from stats import races_of, race_time

DAYS = 180
EX1_DAYS = 365             # 選手ごとの「展示タイム1位のときの成績」を数える期間
MOTOR_DAYS = 60
K_M, K_R = 10, 15          # モーター・選手のずれを0に寄せる強さ(走数)


def _ex1_add(slot: list, rk) -> None:
    slot[0] += 1
    if rk in (1, 2, 3):
        slot[rk] += 1


def build(day: dt.date) -> dict:
    rows, ex1r = [], {}
    ex1 = {"nat": [0, 0, 0, 0], "course": {}}
    for p in sorted(RESULTS.glob("*.json")):
        d = parse_ymd(p.stem)
        if not (day - dt.timedelta(days=EX1_DAYS) <= d < day):
            continue
        res = load_json(p, {}) or {}
        recent = d >= day - dt.timedelta(days=DAYS)
        if recent:
            rows.append((d, res))
        # 展示タイム1位だった艇の [回数, 1着, 2着, 3着]: 選手ごと・コース別(直近1年)と、全国・コース別(直近半年)
        for code, v in res.get("venues", {}).items():
            for race in races_of(v):
                ents = race["entries"]
                exs = [e.get("ex") for e in ents]
                if len(ents) == 6 and all(isinstance(x, (int, float)) and 6.0 <= x <= 7.6 for x in exs):
                    mn = min(exs)
                    for e in ents:
                        if e["ex"] == mn and e.get("course"):
                            c, rk = str(e["course"]), e.get("rank")
                            _ex1_add(ex1r.setdefault(e["toban"], {}).setdefault(c, [0, 0, 0, 0]), rk)
                            if recent:
                                _ex1_add(ex1["nat"], rk)
                                _ex1_add(ex1["course"].setdefault(c, [0, 0, 0, 0]), rk)
    # 1) 着順ごとの平均の差(レースの平均からのずれ)
    gap: dict = {}
    races = []
    for d, res in rows:
        for code, v in res.get("venues", {}).items():
            for race in races_of(v):
                ents = race["entries"]
                fin = [(e, race_time(e.get("time"))) for e in ents if e.get("rank")]
                fin = [(e, t) for e, t in fin if t and 90 < t < 140]
                if len(fin) < 4:
                    continue
                m = sum(t for _, t in fin) / len(fin)
                exs_ok = [e["ex"] for e, _ in fin if isinstance(e.get("ex"), (int, float)) and 6.0 <= e["ex"] <= 7.6]
                exm = sum(exs_ok) / len(exs_ok) if len(exs_ok) >= 4 else None
                races.append((d, code, m, [(e, t) for e, t in fin], exm))
                for e, t in fin:
                    g = gap.setdefault(e["rank"], [0.0, 0])
                    g[0] += t - m
                    g[1] += 1
    gavg = {r: s / n for r, (s, n) in gap.items() if n}
    # 2) 着順の差を引いたずれ。展示タイムの差との関係(β)
    xs, ys, items = [], [], []
    laps: dict = {}
    for d, code, m, fin, exm in races:
        laps.setdefault(code, []).append(m / 3)
        for e, t in fin:
            r = (t - m) - gavg.get(e["rank"], 0.0)
            x = (e["ex"] - exm) if exm is not None and isinstance(e.get("ex"), (int, float)) and 6.0 <= e["ex"] <= 7.6 else None
            items.append((d, code, e, r, x))
            if x is not None:
                xs.append(x)
                ys.append(r)
    beta = 0.0
    if len(xs) >= 200:
        mx, my = statistics.mean(xs), statistics.mean(ys)
        vx = sum((a - mx) ** 2 for a in xs)
        beta = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / vx if vx > 0 else 0.0
    motor: dict = {}
    racer: dict = {}
    for d, code, e, r, x in items:
        turn = r - beta * x if x is not None else r
        if e.get("motor") is not None and (day - d).days <= MOTOR_DAYS:
            a = motor.setdefault(code, {}).setdefault(str(e["motor"]), [0.0, 0.0, 0])
            a[0] += r
            a[1] += turn
            a[2] += 1
        a = racer.setdefault(e["toban"], [0.0, 0.0, 0])
        a[0] += r
        a[1] += turn
        a[2] += 1
    nat_lap = statistics.median([x for v in laps.values() for x in v]) if laps else 36.5
    venue_lap = {c: round((statistics.median(v) * len(v) + nat_lap * 30) / (len(v) + 30), 3) for c, v in laps.items()}
    return {"beta": round(beta, 3), "nat_lap": round(nat_lap, 3), "venue_lap": venue_lap,
            "motor": {c: {k: [round(a[0] / (a[2] + K_M), 3), round(a[1] / (a[2] + K_M), 3), a[2]] for k, a in v.items()} for c, v in motor.items()},
            "racer": {k: [round(a[0] / (a[2] + K_R), 3), round(a[1] / (a[2] + K_R), 3), a[2]] for k, a in racer.items()},
            "ex1": ex1, "ex1r": ex1r, "races": len(races)}


def for_race(P: dict, code: str, ents: list) -> dict:
    """ページに埋め込む分: 場の標準の一周・β・展示1位の成績(全国のコース別と、出走する選手ごとのコース別)と、艇ごとのモーター・選手のずれ。"""
    mv = P["motor"].get(code, {})
    out = {"lap": P["venue_lap"].get(code, P["nat_lap"]), "beta": P["beta"], "races": P["races"],
           "ex1": P["ex1"],
           "ex1r": {str(x["waku"]): P.get("ex1r", {}).get(x["toban"], {}) for x in ents},
           "boats": {}}
    for x in ents:
        m = mv.get(str(x.get("motor")), [0.0, 0.0, 0])
        r = P["racer"].get(x["toban"], [0.0, 0.0, 0])
        out["boats"][str(x["waku"])] = {"res": round(m[0] + r[0], 3), "turn": round(m[1] + r[1], 3), "n": [m[2], r[2]]}
    return out
