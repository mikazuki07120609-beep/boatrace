"""一節まとめ: 開催中の場の、前検から優勝戦までのまとめ(モーターの変化・相性・スタート・得点率の順位・優勝候補と、日ごとのまとめ)。

data/setsu/{場}_{初日}.json に、前検が終わった時点(初日の番組表が出たとき)の数字を残す:
  出場選手(級別・勝率・当地勝率・モーター・ボート)と、前検の時点の選手・モーターの数字、優勝の見込み、注目モーター・注目選手。
  (番組表は数日で消すので、節の間はここに残しておく。作ったあとは、途中から来た選手を足すだけで書き換えない)
ページ(build_site.py から render)は、これと日ごとの競走成績・直前情報(部品交換・プロペラ・チルト・展示)・レース直後の結果から毎回作り直す。

優勝の見込みは、過去1年の節(約850)で学んだ条件付きロジット(data/setsu_model.json。1日1回学び直す):
  前検: 選手の着順点の平均(直近1年)・当地の上ぶれ・モーターの成績の上ぶれと展示の速さ(直近60日。モーター評価と同じ数字)
  節の途中: 前検の見込み・今節の得点率・得点率の順位(予選の間)、準優の枠(準優の顔ぶれが決まったら)、優勝戦の枠(優勝戦の顔ぶれが決まったら)
"""
from __future__ import annotations

import collections
import datetime as dt
import html
import math
import re

from common import DATA, PROGRAM, RESULTS, VENUES, load_json, parse_ymd, save_json, today_jst
from stats import POINTS, races_of

SETSU = DATA / "setsu"
MODEL = DATA / "setsu_model.json"
KEEP_AFTER = 3                 # 最終日のあと、何日ページを残すか
MEAN_PTS = 5.17                # 着順点の全体の平均
R_K, LOC_K, M_RES_K, M_EX_K = 10, 8, 12, 8      # 走数が少ないものを平均に寄せる強さ(motor.py と同じ)
FORM_K = 3                     # 今節の得点率を、ふだんの着順点に寄せる強さ(走数)
CHG = 0.04                     # 展示の速さが「上向き・下向き」と言える変わり方(秒)。何もしていない艇でも13%はこのくらい動く
TEST_DAYS = 75                 # 優勝の見込みの確かめに使う、直近の日数
MAN = 10000                    # 万舟(3連単の払戻が1万円以上)
ACCIDENT = {"転": "転覆", "落": "落水", "沈": "沈没", "エ": "エンスト", "不": "不完走", "妨": "妨害失格", "失": "失格", "F": "フライング", "L": "出遅れ", "欠": "欠場"}
K_STATUS = {"S0": "失", "S1": "失", "S2": "失", "F": "F", "L0": "L", "L1": "L", "K0": "欠", "K1": "欠"}
DAY_NAMES = "月火水木金土日"


def e(s) -> str:
    return html.escape("" if s is None else str(s))


def key_of(code: str, first: dt.date) -> str:
    return f"{code}_{first:%Y%m%d}"


def is_final(nm) -> bool:
    nm = re.sub(r"\s+", "", nm or "")
    return "優勝戦" in nm and "準優" not in nm


def is_semi(nm) -> bool:
    """準優勝戦(「準優進出戦」は予選の最終日のレースなので除く)。"""
    nm = re.sub(r"\s+", "", nm or "")
    return "準優" in nm and "進出" not in nm


def pts_of(rank, status):
    """今節の得点(1着10点〜6着1点。F・出遅れ・失格は0点で1走、欠場は数えない)。数えないときは None。"""
    if rank in POINTS:
        return POINTS[rank]
    if status in ("F", "L", "失", "転", "落", "沈", "エ", "不", "妨", "S0", "S1", "S2", "L0", "L1"):
        return 0
    return None


# ---------------------------------------------------------------- 学習(過去1年の節)

def history() -> list:
    """過去の成績から節を切り出す。節ごとに: 場・日付・優勝者・前検の時点の選手の数字・日ごとの得点・準優と優勝戦の顔ぶれ。
    節は、その場でレースのあった日が続くところで、優勝戦のあった日で区切る。"""
    days = {}
    byv = collections.defaultdict(list)
    for p in sorted(RESULTS.glob("*.json")):
        d = parse_ymd(p.stem)
        days[d] = {}
        for code, v in ((load_json(p, {}) or {}).get("venues") or {}).items():
            rs = list(races_of(v))
            if rs:
                days[d][code] = rs
                byv[code].append(d)
    series = []
    for code, ds in byv.items():
        cur = []
        for d in sorted(ds):
            if cur and ((d - cur[-1]).days > 1 or any(is_final(r.get("name")) for r in days[cur[-1]][code])):
                series.append((code, cur))
                cur = []
            cur.append(d)
        if cur:
            series.append((code, cur))
    starts = collections.defaultdict(list)
    for code, ds in series:
        starts[ds[0]].append((code, ds))
    acc_r = collections.defaultdict(lambda: [0.0, 0])        # 選手の着順点(直近1年)
    acc_v = collections.defaultdict(lambda: [0.0, 0])        # 選手のその場での着順点(直近1年)
    acc_m = collections.defaultdict(lambda: [0.0, 0, 0.0, 0])  # モーターの成績の上ぶれ・展示の速さ(直近60日)
    acc_c = collections.defaultdict(lambda: [0.0, 0])        # 場のコースごとの着順点(直近60日)
    contrib = {}

    def rmean(t):
        s, n = acc_r.get(t, (0.0, 0))
        return (s + MEAN_PTS * R_K) / (n + R_K)

    def cmean(code, c):
        s, n = acc_c.get((code, c), (0.0, 0))
        return (s + MEAN_PTS * 20) / (n + 20)
    out = []
    for d in sorted(days):
        for code, ds in starts.get(d, []):
            fin = next((r for r in days[ds[-1]][code] if is_final(r.get("name"))), None)
            champ = next((x["toban"] for x in (fin or {}).get("entries", []) if x.get("rank") == 1), None)
            roster = {}
            for k, dd in enumerate(ds[:2]):
                for r in days[dd][code]:
                    for x in r["entries"]:
                        roster.setdefault(x["toban"], (x.get("motor"), k == 0))
            feats = {}
            for t, (motor, d1) in roster.items():
                s, n = acc_r.get(t, (0.0, 0))
                vs, vn = acc_v.get((t, code), (0.0, 0))
                rm = (s + MEAN_PTS * R_K) / (n + R_K)
                m = acc_m.get((code, motor), (0.0, 0, 0.0, 0))
                feats[t] = {"str": rm, "loc": (vs + rm * LOC_K) / (vn + LOC_K) - rm, "mres": m[0] / (m[1] + M_RES_K),
                            "mex": m[2] / (m[3] + M_EX_K), "d1": d1}
            daily = []
            for dd in ds:
                pt = collections.defaultdict(lambda: [0, 0])
                semi, finl = {}, {}
                for r in days[dd][code]:
                    for x in r["entries"]:
                        q = pts_of(x.get("rank"), x.get("status"))
                        if q is not None:
                            pt[x["toban"]][0] += q
                            pt[x["toban"]][1] += 1
                        if is_semi(r.get("name")):
                            semi[x["toban"]] = x["waku"]
                        if is_final(r.get("name")):
                            finl[x["toban"]] = x["waku"]
                daily.append({"pt": dict(pt), "semi": semi, "final": finl})
            out.append({"code": code, "days": ds, "champ": champ, "feats": feats, "daily": daily})
        cday = {"r": collections.defaultdict(lambda: [0.0, 0]), "v": collections.defaultdict(lambda: [0.0, 0]),
                "m": collections.defaultdict(lambda: [0.0, 0, 0.0, 0]), "c": collections.defaultdict(lambda: [0.0, 0])}
        for code, rs in days[d].items():
            for r in rs:
                exs = [x["ex"] for x in r["entries"] if x.get("ex")]
                exm = sum(exs) / len(exs) if len(exs) >= 5 else None
                for x in r["entries"]:
                    q = pts_of(x.get("rank"), x.get("status"))
                    if q is not None:
                        cday["r"][x["toban"]][0] += q
                        cday["r"][x["toban"]][1] += 1
                        cday["v"][(x["toban"], code)][0] += q
                        cday["v"][(x["toban"], code)][1] += 1
                    if x.get("motor") is not None:
                        a = cday["m"][(code, x["motor"])]
                        if x.get("rank") and x.get("course"):
                            a[0] += POINTS[x["rank"]] - cmean(code, x["course"]) - 0.9 * (rmean(x["toban"]) - MEAN_PTS)
                            a[1] += 1
                        if exm and x.get("ex"):
                            a[2] += exm - x["ex"]
                            a[3] += 1
                    if x.get("rank") and x.get("course"):
                        cday["c"][(code, x["course"])][0] += POINTS[x["rank"]]
                        cday["c"][(code, x["course"])][1] += 1
        contrib[d] = cday
        for k, acc in (("r", acc_r), ("v", acc_v), ("m", acc_m), ("c", acc_c)):
            for key, val in cday[k].items():
                a = acc[key]
                for i, x in enumerate(val):
                    a[i] += x
        for k, acc, win in (("r", acc_r, 365), ("v", acc_v, 365), ("m", acc_m, 60), ("c", acc_c, 60)):
            old = contrib.get(d - dt.timedelta(days=win))
            if old:
                for key, val in old[k].items():
                    a = acc[key]
                    for i, x in enumerate(val):
                        a[i] -= x
        for old in [x for x in contrib if x <= d - dt.timedelta(days=366)]:
            del contrib[old]
    return out


def pre_x(f: dict) -> list:
    return [f["str"], (f["str"] - 5.5) ** 2, f["loc"], f["mres"], f["mex"] * 10]


def stage_x(stage: str, u0: float, strength: float, p: float, n: int, rank: int | None, waku: int | None) -> list:
    """節の途中の優勝の見込みの特徴: 前検の見込み・今節の得点率の上ぶれ・得点率 と、段階ごとの印(予選の順位・準優/優勝戦の枠)。"""
    form = (p + strength * FORM_K) / (n + FORM_K) - strength
    avg = (p / n if n else 0.0) - MEAN_PTS
    x = [u0, form, avg]
    if stage == "final":
        x += [1.0 if waku == i else 0.0 for i in (1, 2, 3, 4, 5)]
    elif stage == "semi":
        x += [1.0 if waku == i else 0.0 for i in (1, 2, 3)]
    else:
        x += [1.0 if rank is not None and rank <= 6 else 0.0, 1.0 if rank is not None and rank <= 18 else 0.0]
    return x


def y_stage(days_left: int) -> str:
    """予選の間の段階(最終日まで、あと何日あるか)。"""
    return "y4" if days_left >= 4 else "y3"


def _rows_of(s: dict, b_pre) -> list:
    """学習用: 1つの節の、日が終わるごとの (段階, 特徴の行列, 優勝者の位置)。"""
    import numpy as np
    F = s["feats"]
    N = len(s["days"])
    cum = collections.defaultdict(lambda: [0, 0])
    out = []
    for k in range(N - 1):
        for t, (p, n) in s["daily"][k]["pt"].items():
            cum[t][0] += p
            cum[t][1] += n
        nxt = s["daily"][k + 1]
        if nxt["final"] and s["champ"] in nxt["final"]:
            ts, stage, wk = list(nxt["final"]), "final", nxt["final"]
        elif nxt["semi"] and s["champ"] in nxt["semi"]:
            ts, stage, wk = list(nxt["semi"]), "semi", nxt["semi"]
        elif not nxt["semi"] and not nxt["final"]:
            ts, stage, wk = [t for t, f in F.items() if f["d1"] or t == s["champ"]], y_stage(N - 1 - k), {}
        else:
            continue
        avg = {t: (cum[t][0] / cum[t][1] if cum[t][1] else 0.0) for t in ts}
        order = sorted(ts, key=lambda t: -avg[t])
        X = []
        for t in ts:
            f = F.get(t) or {"str": MEAN_PTS, "loc": 0.0, "mres": 0.0, "mex": 0.0}
            u0 = float(np.dot(pre_x(f), b_pre))
            X.append(stage_x(stage, u0, f["str"], cum[t][0], cum[t][1], order.index(t) + 1, wk.get(t)))
        out.append((stage, np.array(X), ts.index(s["champ"])))
    return out


def _clogit(D: list, k: int, l2: float = 0.01):
    import numpy as np
    from scipy.optimize import minimize

    def f(b):
        nll, g = 0.0, np.zeros(k)
        for X, y in D:
            u = X @ b
            u = u - u.max()
            p = np.exp(u)
            p /= p.sum()
            nll -= math.log(max(float(p[y]), 1e-300))
            g -= X[y] - p @ X
        return nll + l2 * float(b @ b), g + 2 * l2 * b
    return minimize(f, np.zeros(k), jac=True, method="L-BFGS-B").x


def _score(D: list, b) -> dict:
    import numpy as np
    ll = t1 = t3 = 0
    for X, y in D:
        u = X @ b
        u = u - u.max()
        p = np.exp(u)
        p /= p.sum()
        o = list(np.argsort(-p))
        ll += math.log(max(float(p[y]), 1e-300))
        t1 += o[0] == y
        t3 += y in o[:3]
    n = len(D) or 1
    return {"n": len(D), "ll": round(ll / n, 3), "top1": round(t1 / n * 100, 1), "top3": round(t3 / n * 100, 1)}


def fit_model(today: dt.date | None = None) -> dict | None:
    """優勝の見込みの式を学ぶ。直近 TEST_DAYS 日に始まった節で確かめてから、全部の節で学び直したものを残す。"""
    import numpy as np
    today = today or today_jst()
    S = [s for s in history() if s["champ"] and len(s["days"]) >= 4 and s["champ"] in s["feats"]]
    if len(S) < 200:
        return None
    first0 = min(s["days"][0] for s in S)
    S = [s for s in S if s["days"][0] >= first0 + dt.timedelta(days=90)]        # 1年分の成績がたまる前の節は、数字が薄いので除く
    cut = today - dt.timedelta(days=TEST_DAYS)
    tr = [s for s in S if s["days"][0] < cut]
    te = [s for s in S if s["days"][0] >= cut]

    def pre_rows(data):
        out = []
        for s in data:
            ts = [t for t, f in s["feats"].items() if f["d1"] or t == s["champ"]]
            out.append((np.array([pre_x(s["feats"][t]) for t in ts]), ts.index(s["champ"])))
        return out

    def stage_rows(data, b):
        out = collections.defaultdict(list)
        for s in data:
            for st, X, y in _rows_of(s, b):
                out[st].append((X, y))
        return out
    ev = {}
    if len(tr) >= 150 and len(te) >= 30:
        b_tr = _clogit(pre_rows(tr), 5)
        ev["pre"] = _score(pre_rows(te), b_tr)
        R_tr, R_te = stage_rows(tr, b_tr), stage_rows(te, b_tr)
        for st, D in R_tr.items():
            if len(D) >= 60 and len(R_te.get(st, [])) >= 20:
                ev[st] = _score(R_te[st], _clogit(D, D[0][0].shape[1]))
    b = _clogit(pre_rows(S), 5)
    stages = {st: [round(float(x), 4) for x in _clogit(D, D[0][0].shape[1])] for st, D in stage_rows(S, b).items() if len(D) >= 60}
    m = {"fitted": today.isoformat(), "pre": [round(float(x), 4) for x in b], "stages": stages, "eval": ev,
         "n_series": len(S), "n_test": len(te), "test_from": cut.isoformat()}
    save_json(MODEL, m)
    return m


def fit_due() -> bool:
    return (load_json(MODEL, None) or {}).get("fitted") != today_jst().isoformat()


def softmax(us: dict) -> dict:
    if not us:
        return {}
    mx = max(us.values())
    ex = {k: math.exp(v - mx) for k, v in us.items()}
    s = sum(ex.values())
    return {k: v / s for k, v in ex.items()}


# ---------------------------------------------------------------- 前検の時点の数字

def period_start(d: dt.date) -> dt.date:
    """今期の初め(5〜10月・11〜4月)。フライングの回数を数える区切り。"""
    if 5 <= d.month <= 10:
        return dt.date(d.year, 5, 1)
    return dt.date(d.year if d.month >= 11 else d.year - 1, 11, 1)


def recent_form(first: dt.date, days: int = 30) -> dict:
    """前検の前 days 日の着順点 {登番: [合計, 走数]}(近況)。"""
    out = collections.defaultdict(lambda: [0, 0])
    for i in range(1, days + 1):
        res = load_json(RESULTS / f"{first - dt.timedelta(days=i):%Y%m%d}.json", None)
        for v in ((res or {}).get("venues") or {}).values():
            for race in races_of(v):
                for x in race["entries"]:
                    q = pts_of(x.get("rank"), x.get("status"))
                    if q is not None:
                        out[x["toban"]][0] += q
                        out[x["toban"]][1] += 1
    return dict(out)


def make_racer(x: dict, code: str, first: dt.date, racers: dict, raw: dict, grades: dict, rec: dict) -> dict:
    r = racers.get(x["toban"]) or {}
    s, n = (r.get("pts") or [0, 0])[:2]
    rm = (s + MEAN_PTS * R_K) / (n + R_K)
    vs, vn = (r.get("v") or {}).get(code, [0, 0])
    m = (raw.get(code) or {}).get(str(x.get("motor")), [0.0, 0, 0.0, 0])
    ps = period_start(first).isoformat()
    rs, rn = rec.get(x["toban"], [0, 0])
    out = {k: x.get(k) for k in ("name", "cls", "age", "branch", "weight", "rate", "rate2", "local", "local2", "motor", "motor2", "boat", "boat2")}
    if r.get("name"):
        out["name"] = r["name"]                     # 番組表の名前は4文字で切れることがある
    g = grades.get(str(x.get("motor"))) or {}
    out.update({"str": round(rm, 3), "n": n, "loc": round((vs + rm * LOC_K) / (vn + LOC_K) - rm, 3), "vn": vn,
                "mres": round(m[0] / (m[1] + M_RES_K), 3), "mex": round(m[2] / (m[3] + M_EX_K), 4), "mn": m[1],
                "mg": g.get("grade"), "mz": g.get("z"), "sp": g.get("sp"),
                "stx": list(r.get("stx") or [0, 0, 0]), "nf": sum(1 for f in r.get("f", []) if f >= ps),
                "rec": [rs, rn]})
    return out


def zenken(sf: dict, model: dict | None, fem: set, pref: str) -> dict:
    """前検の時点の、優勝候補・注目モーター・注目選手。"""
    R = sf["roster"]
    b = (model or {}).get("pre")
    us = {}
    for t, x in R.items():
        f = {"str": x["str"], "loc": x["loc"], "mres": x["mres"], "mex": x["mex"]}
        x["u0"] = round(sum(w * v for w, v in zip(b, pre_x(f))), 4) if b else round(x["str"], 4)
        us[t] = x["u0"]
    p0 = softmax(us)
    for t, p in p0.items():
        R[t]["p0"] = round(p, 4)
    cands = sorted(R, key=lambda t: -R[t]["p0"])
    fav = set(cands[:3])
    # 注目モーター: 前検の時点のモーター評価の高い順(S+・S・A)と、低いもの
    motors = sorted(R, key=lambda t: -(R[t].get("mz") if R[t].get("mz") is not None else -9))
    top_m = [t for t in motors if R[t].get("mg") in ("S+", "S", "A")][:5]
    low_m = [t for t in reversed(motors) if R[t].get("mg") in ("D", "E")][:3]
    # 注目選手: 当地巧者・近況好調・好モーターを引いた選手・地元・F持ち(優勝候補の上位3人は除く)
    players = []
    for t, x in R.items():
        tags, score = [], 0.0
        if x["vn"] >= 12 and x["loc"] >= 0.5:
            tags.append(f"当地巧者(この場の着順点が平均より{x['loc'] + 0.0:+.1f})")
            score += x["loc"]
        rs, rn = x.get("rec") or [0, 0]
        if rn >= 10 and rs / rn - x["str"] >= 1.2:
            tags.append(f"近況好調(直近30日の着順点{rs / rn:.2f}、ふだん{x['str']:.2f})")
            score += rs / rn - x["str"]
        if x.get("mg") in ("S+", "S") or (x.get("mg") == "A" and x["str"] < 5.8):
            tags.append(f"好モーター(評価{x['mg']})を引いた")
            score += 0.8 if x.get("mg") in ("S+", "S") else 0.5
        if pref and x.get("branch") and x["branch"] == pref:
            tags.append("地元")
            score += 0.3
        if x.get("nf"):
            tags.append(f"F{x['nf']}持ち(スタートを控えやすい)")
            score += 0.2
        if t in fem and tags:
            tags.append("女子選手")
        if tags and t not in fav and score >= 0.5:
            players.append((score, t, tags))
    players.sort(key=lambda z: -z[0])
    return {"cands": cands[:8], "motors": top_m, "low": low_m, "players": [{"t": t, "tags": tags} for _, t, tags in players[:8]]}


def venue_pref(code: str, stadiums: dict) -> str:
    return re.sub(r"[都府県]$", "", ((stadiums or {}).get(code) or {}).get("pref") or "")


def find_series(code: str, d: dt.date, day_no) -> dict | None:
    """その場・その日を含む節のファイル(初日が d の9日前までのもの)。"""
    best = None
    for p in SETSU.glob(f"{code}_*.json"):
        try:
            first = dt.datetime.strptime(p.stem.split("_")[1], "%Y%m%d").date()
        except (IndexError, ValueError):
            continue
        if first <= d <= first + dt.timedelta(days=9):
            sf = load_json(p, None)
            if sf and (not sf.get("last") or d <= parse_ymd(sf["last"].replace("-", ""))) and (best is None or first > parse_ymd(best["first"].replace("-", ""))):
                best = sf
    if best and day_no and day_no == 1 and best["first"] != d.isoformat():
        return None                                  # 初日の番組表なのに、前の節のファイル: 新しい節
    return best


def refresh(today: dt.date, progs: dict, stadiums: dict, log: list | None = None) -> list:
    """新しく始まる節(前検が終わって初日の番組表が出た節)と、もう始まっている節のファイルを作る。途中から来た選手も足す。
    progs: {日付: 番組表}(今日・明日)。作った・足したファイルのキーを返す。"""
    from motor import raw_scores, venue_grades
    from stats import collect
    log = log if log is not None else []
    SETSU.mkdir(parents=True, exist_ok=True)
    model = load_json(MODEL, None)
    fem = set((load_json(DATA / "fem.json", {}) or {}).get("fem", []))
    G = load_json(DATA / "grades.json", {}) or {}
    cache, by_first, done = {}, {}, []
    for d in sorted(progs):
        for code, vp in (progs[d].get("venues") or {}).items():
            if not vp.get("races"):
                continue
            day_no = vp.get("day")
            sf = find_series(code, d, day_no)
            if sf is None:
                lv = load_json(DATA / "live" / f"{d:%Y%m%d}" / f"{code}.json", {}) or {}
                sp = lv.get("span") or {}
                first = parse_ymd(sp["first"].replace("-", "")) if sp.get("first") else d - dt.timedelta(days=max(0, (day_no or 1) - 1))
                if first not in by_first:
                    racers, _, _ = collect(first, cache)
                    by_first[first] = (racers, raw_scores(first, racers), recent_form(first))
                racers, raw, rec = by_first[first]
                grades = venue_grades(code, vp, raw)
                g = (G.get(f"{first:%Y%m%d}") or G.get(f"{d:%Y%m%d}") or {}).get(code)
                sf = {"code": code, "first": first.isoformat(), "last": sp.get("last"), "title": vp.get("title", ""),
                      "grade": ("女子戦" if g and ("lady" in g or "venus" in g) else g[0]) if g else None,
                      "created": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
                      "late": first < d, "roster": {}, "model": (model or {}).get("fitted")}
                for race in vp["races"]:
                    for x in race["entries"]:
                        if x["toban"] not in sf["roster"]:
                            sf["roster"][x["toban"]] = make_racer(x, code, first, racers, raw, grades, rec)
                dd = first                                  # もう始まっている節: それまでの日に走った選手も(帰郷などで今日の番組表にいない選手)
                while dd < d:
                    res = load_json(RESULTS / f"{dd:%Y%m%d}.json", None)
                    races = list(races_of(((res or {}).get("venues") or {}).get(code) or {}))
                    if not races:
                        races = ((((load_json(PROGRAM / f"{dd:%Y%m%d}.json", None) or {}).get("venues") or {}).get(code)) or {}).get("races") or []
                    for race in races:
                        for x in race["entries"]:
                            if x["toban"] not in sf["roster"]:
                                sf["roster"][x["toban"]] = make_racer(x, code, first, racers, raw, grades, rec)
                    dd += dt.timedelta(days=1)
                sf["zenken"] = zenken(sf, model, fem, venue_pref(code, stadiums))
                save_json(SETSU / f"{key_of(code, first)}.json", sf)
                done.append(key_of(code, first))
                log.append(f"一節まとめ: {VENUES.get(code, code)} {first:%m/%d}〜 のファイルを作りました({len(sf['roster'])}人)")
                continue
            changed = False
            first = parse_ymd(sf["first"].replace("-", ""))
            lv = load_json(DATA / "live" / f"{d:%Y%m%d}" / f"{code}.json", {}) or {}
            if not sf.get("last") and (lv.get("span") or {}).get("last"):
                sf["last"] = lv["span"]["last"]
                changed = True
            new = [x for race in vp["races"] for x in race["entries"] if x["toban"] not in sf["roster"]]
            if new:                                         # 途中から来た選手(追加のあっせん): 今の時点の数字で足す
                if d not in by_first:
                    racers, _, _ = collect(d, cache)
                    by_first[d] = (racers, raw_scores(d, racers), recent_form(d))
                racers, raw, rec = by_first[d]
                grades = venue_grades(code, vp, raw)
                b = (model or {}).get("pre")
                for x in new:
                    if x["toban"] in sf["roster"]:
                        continue
                    y = make_racer(x, code, first, racers, raw, grades, rec)
                    y["late"] = d.isoformat()
                    y["u0"] = round(sum(w * v for w, v in zip(b, pre_x(y))), 4) if b else y["str"]
                    sf["roster"][x["toban"]] = y
                changed = True
            if changed:
                save_json(SETSU / f"{key_of(code, first)}.json", sf)
                done.append(key_of(code, first))
    # 古いファイル(最終日から60日より前)は消す
    for p in SETSU.glob("*.json"):
        try:
            first = dt.datetime.strptime(p.stem.split("_")[1], "%Y%m%d").date()
        except (IndexError, ValueError):
            continue
        if (today - first).days > 70:
            p.unlink()
    return done




# ---------------------------------------------------------------- 節の日ごとのデータ

def load_prog(d: dt.date, progs: dict):
    return progs.get(d) or load_json(PROGRAM / f"{d:%Y%m%d}.json", None)


def gather(sf: dict, today: dt.date, progs: dict) -> dict:
    """節の日ごとのレースと艇(競走成績があればそれ、なければ番組表とレース直後の結果)と直前情報。明日の番組表があれば、それも(終わっていない日)。"""
    code = sf["code"]
    first = parse_ymd(sf["first"].replace("-", ""))
    last = parse_ymd(sf["last"].replace("-", "")) if sf.get("last") else None
    days = []
    d = first
    end = min(today + dt.timedelta(days=1), (last or first + dt.timedelta(days=9)) + dt.timedelta(days=2))
    while d <= end:
        prog = load_prog(d, progs)
        vp = ((prog or {}).get("venues") or {}).get(code)
        if vp and vp.get("day") == 1 and d != first:
            break                                          # 次の節
        res = load_json(RESULTS / f"{d:%Y%m%d}.json", None)
        vr = ((res or {}).get("venues") or {}).get(code)
        lv = load_json(DATA / "live" / f"{d:%Y%m%d}" / f"{code}.json", None) or {}
        if vp or vr or lv.get("before") or lv.get("result"):
            pays = ((load_json(DATA / "pays" / f"{d:%Y%m%d}.json", None) or {}).get("venues") or {}).get(code) or {}
            day = build_day(d, vp, vr, lv, pays)
            if day["races"]:
                days.append(day)
                if any(is_final(r["name"]) and r["done"] for r in day["races"]):
                    break
        d += dt.timedelta(days=1)
    for i, day in enumerate(days):
        day["k"] = i + 1
    return {"days": days}


def build_day(d: dt.date, vp, vr, lv: dict, pays: dict) -> dict:
    B = lv.get("before") or {}
    LR = lv.get("result") or {}
    kr = {r["no"]: r for r in races_of(vr)} if vr else {}
    prog_races = {r["no"]: r for r in (vp or {}).get("races", [])}
    races = []
    for no in sorted(set(kr) | set(prog_races)):
        k = kr.get(no)
        pr = prog_races.get(no) or {}
        b = B.get(str(no)) or {}
        lr = LR.get(str(no)) or {}
        lstat = {o["toban"]: o.get("status") for o in lr.get("order", [])}
        lrank = {o["toban"]: o.get("rank") for o in lr.get("order", [])}
        lcourse = {w: i + 1 for i, w in enumerate(lr.get("course") or b.get("course") or [])}
        ents = (k or {}).get("entries") or pr.get("entries") or []
        exs, boats = [], []
        for x in ents:
            w = str(x["waku"])
            ex = x.get("ex") if k else (b.get("ex") or {}).get(w)
            st = x.get("st") if k else (lr.get("st") or {}).get(w)
            status = lstat.get(x["toban"]) or (K_STATUS.get(x.get("status")) if k else None)
            if k and x.get("flying"):
                status = status or "F"
            boats.append({"waku": x["waku"], "toban": x["toban"], "name": x.get("name"), "motor": x.get("motor"), "boat": x.get("boat"),
                          "course": (x.get("course") if k else None) or lcourse.get(x["waku"]), "ex": ex, "st": st,
                          "rank": x.get("rank") if k else lrank.get(x["toban"]), "status": status,
                          "est": (b.get("est") or {}).get(w), "tilt": (b.get("tilt") or {}).get(w), "parts": (b.get("parts") or {}).get(w) or [],
                          "prop": (b.get("prop") or {}).get(w) or ""})
            if ex:
                exs.append(ex)
        exm = sum(exs) / len(exs) if len(exs) >= 5 else None
        for y in boats:
            y["exd"] = round(exm - y["ex"], 3) if exm and y["ex"] else None
            y["pts"] = pts_of(y["rank"], y["status"])
        p3 = (pays.get(str(no)) or {}).get("3t") or []
        if p3:
            pay, pop = p3[0][1], (p3[0][2] if len(p3[0]) > 2 else None)
        else:
            pay, pop = lr.get("pay"), lr.get("pop")
        fin = sorted([y for y in boats if y["rank"]], key=lambda y: y["rank"])
        w = b.get("weather") or {}
        races.append({"no": no, "name": (k or {}).get("name") or pr.get("name") or "", "done": bool(k) or bool(lr.get("order")),
                      "kim": (k or {}).get("kimarite") or lr.get("kimarite"), "pay": pay, "pop": pop,
                      "tri": [y["waku"] for y in fin[:3]] if len(fin) >= 3 else (lr.get("tri") or None),
                      "wind": k.get("wind") if k else w.get("wind"), "wave": k.get("wave") if k else w.get("wave"), "boats": boats})
    return {"d": d, "races": races, "complete": bool(races) and all(r["done"] for r in races)}


# ---------------------------------------------------------------- 集計

def standings(days: list, upto: int) -> dict:
    """upto 日目まで(終わった日)の得点率 {登番: {pts, n, avg, marks: {日: 着順の文字}, rank, name}}。"""
    S = {}
    for day in days[:upto]:
        for race in day["races"]:
            if not race["done"]:
                continue
            for y in race["boats"]:
                s = S.setdefault(y["toban"], {"pts": 0, "n": 0, "marks": {}, "name": y["name"]})
                ch = str(y["rank"]) if y["rank"] else (y["status"] or "")
                if ch:
                    s["marks"][day["k"]] = s["marks"].get(day["k"], "") + ch[0]
                if y["pts"] is not None:
                    s["pts"] += y["pts"]
                    s["n"] += 1
    avgs = [s["pts"] / s["n"] for s in S.values() if s["n"]]
    for s in S.values():
        s["avg"] = s["pts"] / s["n"] if s["n"] else None
        s["rank"] = (1 + sum(1 for a in avgs if a > s["avg"] + 1e-9)) if s["n"] else None
    return S


def motor_change(rows: list) -> dict:
    """1艇(この節のモーター)の、日ごとの展示の速さと、部品交換・プロペラ・事故のあとの変わり方。rows はレース順。"""
    byd = collections.defaultdict(list)
    for r in rows:
        if r["exd"] is not None:
            byd[r["k"]].append(r["exd"])
    ev = []
    for i, r in enumerate(rows):
        if r["parts"]:
            ev.append((i, f"{r['k']}日目{r['no']}R 部品交換(" + "・".join(r["parts"]) + ")"))
        if r["prop"] == "新":
            ev.append((i, f"{r['k']}日目{r['no']}R 新しいプロペラ"))
        if r["status"] in ("転", "落", "沈", "エ", "不"):          # 事故は、その次のレースからを「あと」にする
            ev.append((i + 1, f"{r['k']}日目{r['no']}R {ACCIDENT[r['status']]}"))
    exs = [r["exd"] for r in rows if r["exd"] is not None]
    out = {"days": {k: sum(v) / len(v) for k, v in byd.items()}, "n": len(exs), "avg": sum(exs) / len(exs) if exs else None,
           "events": [x[1] for x in ev], "delta": None, "label": "", "why": ""}
    if ev:                                             # 一番最近の出来事の前と後
        i, txt = ev[-1]
        a = [r["exd"] for r in rows[:i] if r["exd"] is not None]
        b = [r["exd"] for r in rows[i:] if r["exd"] is not None]
        if len(a) >= 2 and len(b) >= 2:
            out["delta"] = sum(b) / len(b) - sum(a) / len(a)
            out["why"] = "前後"
        else:
            out["why"] = "まだ展示が少ない"
    else:                                              # 出来事がなければ、節の前半と後半
        ks = sorted(byd)
        if len(ks) >= 2:
            h = (len(ks) + 1) // 2
            a = [x for k in ks[:h] for x in byd[k]]
            b = [x for k in ks[h:] for x in byd[k]]
            if len(a) >= 2 and len(b) >= 2:
                out["delta"] = sum(b) / len(b) - sum(a) / len(a)
                out["why"] = "前半→後半"
    if out["delta"] is not None:
        out["label"] = "上向き" if out["delta"] >= CHG else "下向き" if out["delta"] <= -CHG else "変わらず"
    return out


_CM: dict = {}


def course_means(code: str, until: dt.date, cache: dict | None = None) -> dict:
    """場のコースごとの着順点の平均(until の前の60日。motor.py の「成績の上ぶれ」と同じ数え方)。"""
    key = (code, until)
    if key in _CM:
        return _CM[key]
    acc = collections.defaultdict(lambda: [0.0, 0])
    for i in range(1, 61):
        ymd = f"{until - dt.timedelta(days=i):%Y%m%d}"
        res = cache.get(ymd) if cache is not None else None
        if res is None:
            res = load_json(RESULTS / f"{ymd}.json", {}) or {}
            if cache is not None:
                cache[ymd] = res
        for race in races_of(((res.get("venues") or {}).get(code)) or {}):
            for x in race["entries"]:
                if x.get("rank") and x.get("course"):
                    acc[x["course"]][0] += POINTS[x["rank"]]
                    acc[x["course"]][1] += 1
    _CM[key] = {c: (acc[c][0] + MEAN_PTS * 20) / (acc[c][1] + 20) for c in range(1, 7)}
    return _CM[key]


def residual(y: dict, cm: dict, strength: float):
    """その走りが、コースと選手の腕前から見込むより何点良かったか(モーター評価の「成績の上ぶれ」と同じ数え方)。"""
    if not y["rank"] or not y["course"]:
        return None
    return POINTS[y["rank"]] - cm.get(y["course"], MEAN_PTS) - 0.9 * (strength - MEAN_PTS)


def analyze(sf: dict, G: dict, cm: dict, model: dict | None, nxt: dict | None) -> dict:
    """節のまとめの数字。G は gather の戻り値、cm は場のコースごとの着順点の平均、nxt はまだ終わっていない最初の日の番組表(場の分)。"""
    R = sf["roster"]
    days = G["days"]
    comp = [d for d in days if d["complete"]]
    kdone = len(comp)
    rows = collections.defaultdict(list)
    for day in comp:
        for race in day["races"]:
            for y in race["boats"]:
                rows[y["toban"]].append(dict(y, k=day["k"], no=race["no"], rn=race["name"]))
    S = standings(days, kdone)
    per = {}
    for t, rs in rows.items():
        x = R.get(t) or {}
        strength = x.get("str", MEAN_PTS)
        res = [v for v in (residual(y, cm, strength) for y in rs) if v is not None]
        sts = [y["st"] for y in rs if isinstance(y["st"], (int, float)) and 0 <= y["st"] < 1 and y["status"] not in ("F", "L", "欠")]
        ests = [y["est"] for y in rs if isinstance(y["est"], (int, float))]
        mc = motor_change(rs)
        nres = len(res)
        res_now = sum(res) / nres if nres else None
        stx = x.get("stx") or [0, 0, 0]
        p = {"mc": mc, "res": res_now, "nres": nres, "st": sum(sts) / len(sts) if sts else None, "nst": len(sts),
             "st0": stx[1] / stx[0] if stx and stx[0] else None, "est": sum(ests) / len(ests) if ests else None,
             "f": sum(1 for y in rs if y["status"] == "F"), "l": sum(1 for y in rs if y["status"] == "L"),
             "acc": [f"{y['k']}日目{y['no']}R {ACCIDENT[y['status']]}" for y in rs if y["status"] in ACCIDENT and y["status"] != "欠"],
             "motor": rs[0]["motor"] if rs else x.get("motor"), "name": rs[0]["name"] if rs else x.get("name")}
        # 相性: この節の展示の速さ・成績の上ぶれと、このモーターのこれまで(前の選手たち。直近60日)との差。少ない走数は0に寄せる
        if mc["avg"] is not None and x:
            dex = (mc["avg"] - x.get("mex", 0.0)) * mc["n"] / (mc["n"] + 3)
            dres = ((res_now - x.get("mres", 0.0)) * nres / (nres + 6)) if res_now is not None else 0.0
            p.update({"fit": dex / 0.03 + dres / 1.5, "dex": dex, "dres": dres})
        per[t] = p
    ranked = sorted([t for t in per if per[t]["mc"]["avg"] is not None and per[t]["mc"]["n"] >= 3], key=lambda t: -per[t]["mc"]["avg"])
    for i, t in enumerate(ranked):
        per[t]["exrank"] = i + 1
    return {"S": S, "per": per, "kdone": kdone, "nmot": len(ranked), "win": win_now(sf, days, kdone, S, model, nxt)}


def win_now(sf: dict, days: list, kdone: int, S: dict, model: dict | None, nxt: dict | None) -> dict:
    """今の優勝の見込み。段階: before(初日の前)/ y4・y3(予選)/ semi(準優の顔ぶれが分かった)/ final(優勝戦の顔ぶれ)/ done(優勝が決まった)。"""
    R = sf["roster"]
    for day in days:
        for race in day["races"]:
            if is_final(race["name"]) and race["done"]:
                w = next((y for y in race["boats"] if y["rank"] == 1), None)
                if w:
                    return {"stage": "done", "champ": w["toban"], "race": race, "k": day["k"], "p": {}}
    if kdone == 0:
        return {"stage": "before", "p": {t: x.get("p0", 0.0) for t, x in R.items()}}
    nraces = (nxt or {}).get("races") or []
    fin = next((r for r in nraces if is_final(r.get("name"))), None)
    semis = [r for r in nraces if is_semi(r.get("name"))]
    last_semis = [r for r in (days[kdone - 1]["races"] if kdone else []) if is_semi(r["name"]) and r["done"]]
    if fin:
        stage, wk = "final", {x["toban"]: x["waku"] for x in fin["entries"]}
    elif semis:
        stage, wk = "semi", {x["toban"]: x["waku"] for r in semis for x in r["entries"]}
    elif last_semis and not nraces:                 # 準優が終わって、優勝戦の番組表がまだ: 準優の2着までを候補に(枠は分からない)
        stage = "semi"
        wk = {y["toban"]: None for r in last_semis for y in r["boats"] if y["rank"] in (1, 2)}
    else:
        first = parse_ymd(sf["first"].replace("-", ""))
        last = parse_ymd(sf["last"].replace("-", "")) if sf.get("last") else first + dt.timedelta(days=5)
        stage, wk = y_stage((last - first).days + 1 - kdone), {}      # 最終日まで、あと何日(学習の _rows_of と同じ数え方)
    cands = list(wk) if wk else list(dict.fromkeys([x["toban"] for r in nraces for x in r["entries"]] or [t for t in S if S[t]["n"]] or list(R)))
    w = ((model or {}).get("stages") or {}).get(stage)
    avg = {t: (S[t]["pts"] / S[t]["n"] if t in S and S[t]["n"] else 0.0) for t in cands}
    order = sorted(cands, key=lambda t: -avg[t])
    us = {}
    for t in cands:
        x = R.get(t) or {"str": MEAN_PTS}
        s = S.get(t) or {"pts": 0, "n": 0}
        xv = stage_x(stage, x.get("u0", x["str"]), x["str"], s["pts"], s["n"], order.index(t) + 1, wk.get(t))
        us[t] = sum(a * b for a, b in zip(w, xv)) if w else xv[0]
    return {"stage": stage, "p": softmax(us), "wk": wk}


def water(days: list) -> list:
    """節の水面の傾向: 日ごとの1コースの1着・決まり手・万舟・風と波。"""
    out = []
    for day in days:
        rs = [r for r in day["races"] if r["done"]]
        if not rs or not day["complete"]:
            continue
        winds = [r["wind"] for r in rs if isinstance(r["wind"], (int, float))]
        waves = [r["wave"] for r in rs if isinstance(r["wave"], (int, float))]
        pays = sorted(r["pay"] for r in rs if r["pay"])
        out.append({"k": day["k"], "d": day["d"], "n": len(rs),
                    "c1": sum(1 for r in rs for y in r["boats"] if y["rank"] == 1 and y["course"] == 1),
                    "km": collections.Counter(r["kim"] for r in rs if r["kim"]), "man": [r for r in rs if r["pay"] and r["pay"] >= MAN],
                    "wind": (min(winds), max(winds)) if winds else None, "wave": (min(waves), max(waves)) if waves else None,
                    "med": pays[len(pays) // 2] if pays else None})
    return out
