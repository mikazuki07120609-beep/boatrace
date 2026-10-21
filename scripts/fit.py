#!/usr/bin/env python3
"""見立ての学習と答え合わせ。

過去の各日について「その日の朝の時点で分かっていたデータ」だけで見立てを作り直し、実際の結果と比べる。
  1) スタートの見立て: 選手ごとの予想STとばらつき(フライング持ち・コース・風の影響を含む)
  2) 展開の見立て: どのコースがどの決まり手で1着になるか。STの組み合わせで起こりやすさが変わる形にしてあり、
     スタートが分からない本番前は、スタートの見立てから作った多数のSTの組み合わせで平均する。
直近 EVAL_DAYS 日は学習に使わずに答え合わせだけを行い、その成績を data/eval.json に残す。
最後に全期間で学習し直した重みを data/model.json に保存する(サイトの見立てと1周1マークの映像が使う)。

数式は site/assets/model.js と同じ。どちらかを変えたら、もう一方も合わせること(tests/model_check.js で確かめる)。

  python3 scripts/fit.py
"""
import datetime as dt
import json
import math
import sys

import numpy as np
from scipy.optimize import minimize

from common import DATA, RESULTS, load_json, parse_ymd, save_json, today_jst
from stats import RACER_DAYS, RECENT_N, VENUE_DAYS, Acc, races_of, valid_st

WARMUP_DAYS = 20          # これより前のデータしかない日は、集計が薄いので学習に使わない
EVAL_DAYS = 30            # 学習に使わずに答え合わせする直近の日数
N_SAMPLES = 300           # 本番前の見立てで平均するSTの組み合わせの数
MOTOR_DAYS = 180

# ---- 見立ての式の定数(model.js と同じ)
PTS_MEAN, PTS_K = 31 / 6, 10       # 着順点の平均(1レース31点を6艇で分ける)と、走数が少ない選手を平均に寄せる強さ
REC_K, TAC_K, LS_K = 10, 3, 2
VEN_M, VEN_KM = 300, 40            # 場の傾向を全国の傾向で補う強さ(レース数・勝ち数)
U = 0.05                           # STの差の単位(秒)
KIMS = ["逃げ", "捲り", "差し", "捲り差し", "抜き"]
CLASSES = [(1, "逃げ"), (1, "抜き")] + [(c, k) for c in range(2, 7) for k in ("捲り", "差し", "捲り差し", "抜き")]
CI = {ck: i for i, ck in enumerate(CLASSES)}
NC = len(CLASSES)


def group(c: int) -> int:
    return {2: 0, 3: 1, 4: 2}.get(c, 3)


# ---- 重みの名前(順番が重みの並び)
PARAMS = ([f"d_{c}{k}" for c, k in CLASSES] + [f"str_{k}" for k in KIMS] + ["rec", "tac", "ls", "mot", "ex", "ex_mk"]
          + ["n1_lag", "n1_big"]
          + [f"mk{j}_{g}" for g in range(4) for j in (1, 2)]
          + [f"sa{j}_{g}" for g in range(4) for j in (1, 2, 3)]
          + [f"ms{j}_{g}" for g in range(4) for j in (1, 2, 3)]
          + ["w_nige", "w_mk", "w_sa", "w_ms"])
PI = {n: i for i, n in enumerate(PARAMS)}
NP = len(PARAMS)
REG = np.array([2.0 if n.startswith("d_") else 0.5 for n in PARAMS])


def kim_class(k):
    return "抜き" if k in ("抜き", "恵まれ") else k


# ======================================================================
# 過去の各日の時点の集計を作りながら、レースごとの記録を作る
# ======================================================================
def period_start(d: dt.date) -> dt.date:
    """フライングの回数を数える期の始まり(5月1日・11月1日)。"""
    if d.month >= 11:
        return dt.date(d.year, 11, 1)
    if d.month >= 5:
        return dt.date(d.year, 5, 1)
    return dt.date(d.year - 1, 11, 1)


def snapshot_racer(r: dict, d: dt.date, course: int) -> dict:
    cs = r.get("c", {}).get(str(course), {})
    ps = period_start(d).isoformat()
    return {"pts": list(r.get("pts", [0, 0])), "stx": list(r.get("stx", [0, 0.0, 0.0])),
            "r8": list(r.get("rs", []))[-RECENT_N:],
            "fp": sum(1 for x in r.get("f", []) if x >= ps),
            "cb": list(r.get("cb", [0, 0])),
            "cs": {"n": cs.get("n", 0), "w1": cs.get("w1", 0), "w2": cs.get("w2", 0),
                   "km": {k: v for k, v in cs.get("km", {}).items() if v > 0},
                   "ls": {k: v for k, v in cs.get("ls", {}).items() if v > 0} if course == 1 else {}}}


def table_copy(vs: dict | None) -> dict:
    out = {}
    for c in range(1, 7):
        vc = (vs or {}).get("c", {}).get(str(c), {"n": 0, "w1": 0, "km": {}})
        out[c] = {"n": vc["n"], "w1": vc["w1"], "km": {k: v for k, v in vc["km"].items() if v > 0}}
    return out


def build_records():
    paths = sorted(RESULTS.glob("*.json"))
    if not paths:
        return [], []
    days = [(parse_ymd(p.stem), p) for p in paths]
    first = days[0][0]
    acc = Acc()
    loaded = {}
    motor: dict = {}           # (場, モーター番号) -> {日付: [走数, 2着以内]}
    recs, sts = [], []
    for d, p in days:
        day = load_json(p, {})
        loaded[d] = day
        if (d - first).days >= WARMUP_DAYS:
            for vcode, v in day.get("venues", {}).items():
                vt = table_copy(acc.venues.get(vcode))
                nt = table_copy(acc.nat)
                for race in races_of(v):
                    rec = make_record(d, vcode, race, acc, vt, nt, motor)
                    if rec:
                        recs.append(rec)
                        sts.extend(rec.pop("_sts"))
        acc.add(d, day, 1)
        for vcode, v in day.get("venues", {}).items():
            for race in races_of(v):
                for e in race.get("entries", []):
                    if e.get("motor") is None or not (e.get("rank") or e.get("status")):
                        continue
                    m = motor.setdefault((vcode, e["motor"]), {})
                    x = m.setdefault(d, [0, 0])
                    x[0] += 1
                    x[1] += 1 if e.get("rank") in (1, 2) else 0
        old = d - dt.timedelta(days=RACER_DAYS)
        if old in loaded:
            acc.add(old, loaded.pop(old), -1, racers=True, venues=False)
        oldv = d - dt.timedelta(days=VENUE_DAYS)
        if oldv in loaded:
            acc.add(oldv, loaded[oldv], -1, racers=False, venues=True)
    return recs, sts


def motor_rate(motor, vcode, no, d):
    m = motor.get((vcode, no))
    if not m:
        return None
    lo = d - dt.timedelta(days=MOTOR_DAYS)
    n = top = 0
    for day, (a, b) in m.items():
        if lo <= day < d:
            n += a
            top += b
    return (top + 10 / 3) / (n + 10) * 100 if n else None     # 2連率(%)。走数が少ないうちは33%に寄せる(motor.py の motor_rates と同じ式)


def make_record(d, vcode, race, acc, vt, nt, motor):
    ents = [e for e in race.get("entries", []) if e.get("course")]
    by = {}
    for e in ents:
        by[e["course"]] = e
    if sorted(by) != [1, 2, 3, 4, 5, 6]:
        return None
    sts = []
    st_ok = all(valid_st(by[c]) for c in range(1, 7))
    # スタートの見立ての学習用(普通にスタートした艇は全部使う)
    vals = [by[c]["st"] for c in range(1, 7) if valid_st(by[c])]
    six = [acc.racer(by[c]["toban"]) for c in range(1, 7)]
    for c in range(1, 7):
        e = by[c]
        if valid_st(e):
            r = six[c - 1]
            nbs = [list(six[j - 1].get("stx", [0, 0.0, 0.0])) for j in (c - 1, c + 1) if 1 <= j <= 6]
            sts.append({"d": d, "v": vcode, "no": race["no"], "c": c, "waku": e.get("waku"), "st": e["st"], "stx": list(r.get("stx", [0, 0.0, 0.0])),
                        "toban": e["toban"], "rname": race.get("name"), "r8": list(r.get("rs", []))[-RECENT_N:], "nb": nbs,
                        "fp": sum(1 for x in r.get("f", []) if x >= period_start(d).isoformat()),
                        "wind": race.get("wind"), "n6": len(vals)})
    win = next((e for e in ents if e.get("rank") == 1), None)
    kim = kim_class(race.get("kimarite"))
    y = None
    if win and kim in KIMS:
        ck = (win["course"], kim)
        if ck in CI:
            y = CI[ck]
    clean = st_ok and not any(e.get("flying") or (e.get("status") or "").startswith(("L", "K")) for e in ents)
    rec = {"d": d, "v": vcode, "no": race["no"], "y": y, "clean": clean, "wind": race.get("wind"),
           "vt": vt, "nt": nt, "b": [], "_sts": sts}
    for c in range(1, 7):
        e = by[c]
        r = acc.racer(e["toban"])
        b = snapshot_racer(r, d, c)
        b.update({"c": c, "toban": e["toban"], "st": e["st"] if valid_st(e) else None, "rank": e.get("rank"),
                  "ex": e.get("ex"), "motor": motor_rate(motor, vcode, e.get("motor"), d)})
        rec["b"].append(b)
    return rec


# ======================================================================
# 見立ての式(model.js と同じ)
# ======================================================================
def prior(vt, nt):
    """場の傾向(全国の傾向で補ったもの)から、コース×決まり手の起こりやすさ p0 を作る。"""
    pc = []
    for c in range(1, 7):
        nn = nt[c]["n"] or 1
        nat_rate = nt[c]["w1"] / nn if nt[c]["n"] else [0.55, 0.14, 0.13, 0.1, 0.06, 0.02][c - 1]
        pc.append((vt[c]["w1"] + VEN_M * nat_rate) / (vt[c]["n"] + VEN_M))
    s = sum(pc) or 1
    pc = [x / s for x in pc]
    q = {}
    for c in range(1, 7):
        ks = ["逃げ", "抜き"] if c == 1 else ["捲り", "差し", "捲り差し", "抜き"]
        def cnt(tbl, k):
            km = tbl[c]["km"]
            return km.get(k, 0) + (km.get("恵まれ", 0) if k == "抜き" else 0)
        ntot = sum(cnt(nt, k) for k in ks)
        vtot = sum(cnt(vt, k) for k in ks)
        for k in ks:
            nq = (cnt(nt, k) + 0.5) / (ntot + 0.5 * len(ks))
            q[(c, k)] = (cnt(vt, k) + VEN_KM * nq) / (vtot + VEN_KM)
        qs = sum(q[(c, k)] for k in ks) or 1
        for k in ks:
            q[(c, k)] /= qs
    return pc, q


def loss_share(nt):
    """1コースが負けるときの決まり手の全国の割合(捲り・差し・捲り差し)。"""
    tot = {k: sum(nt[c]["km"].get(k, 0) for c in range(2, 7)) for k in ("捲り", "差し", "捲り差し")}
    s = sum(tot.values())
    return {k: (tot[k] / s if s else 1 / 3) for k in tot}


def static_terms(rec):
    """STに関係しない項(クラスごとの点数)と、事前の起こりやすさ。戻り値: (log p0[NC], terms[(param, class, value)])"""
    pc, q = prior(rec["vt"], rec["nt"])
    lp = np.full(NC, -30.0)
    for i, (c, k) in enumerate(CLASSES):
        lp[i] = math.log(max(1e-6, pc[c - 1] * q[(c, k)]))
    B = rec["b"]
    pts = [(b["pts"][0] + PTS_K * PTS_MEAN) / (b["pts"][1] + PTS_K) for b in B]
    mp = sum(pts) / 6
    mots = [b.get("motor") for b in B]
    mm = [m for m in mots if m is not None]
    mmean = sum(mm) / len(mm) if mm else None
    exs = [b.get("ex") for b in B]
    ex_ok = all(isinstance(x, (int, float)) and 6.0 <= x <= 7.6 for x in exs)
    ex_mean = sum(exs) / 6 if ex_ok else None
    ls1 = B[0]["cs"].get("ls", {})
    lsh = loss_share(rec["nt"])
    lsw = sum(ls1.get(k, 0) for k in lsh)
    terms = []
    for i, (c, k) in enumerate(CLASSES):
        b = B[c - 1]
        terms.append((PI[f"d_{c}{k}"], i, 1.0))
        terms.append((PI[f"str_{k}"], i, pts[c - 1] - mp))
        base = pc[c - 1]
        rate = (b["cs"]["w1"] + REC_K * base) / (b["cs"]["n"] + REC_K)
        terms.append((PI["rec"], i, math.log(rate / base)))
        if mmean is not None and mots[c - 1] is not None:
            terms.append((PI["mot"], i, (mots[c - 1] - mmean) / 10))
        if ex_ok:                                         # 展示タイム(6艇の平均より速いほど、そのコースの決着が起きやすい。捲りは別に上乗せ)
            dx = (ex_mean - exs[c - 1]) / 0.05
            terms.append((PI["ex"], i, dx))
            if k in ("捲り", "捲り差し"):
                terms.append((PI["ex_mk"], i, dx))
        if c >= 2 and k in ("捲り", "差し", "捲り差し"):
            km = b["cs"]["km"]
            W = sum(km.get(x, 0) for x in ("捲り", "差し", "捲り差し"))
            q3 = q[(c, "捲り")] + q[(c, "差し")] + q[(c, "捲り差し")]
            qk = q[(c, k)] / q3
            terms.append((PI["tac"], i, math.log(((km.get(k, 0) + TAC_K * qk) / (W + TAC_K)) / qk)))
            terms.append((PI["ls"], i, math.log(((ls1.get(k, 0) + LS_K * lsh[k]) / (lsw + LS_K)) / lsh[k])))
    return lp, terms


def st_terms(t, wind):
    """STの組み合わせ t[0..5](1〜6コース)で変わる項。t は (S, 6) の配列。戻り値: [(param, class, values[S])]"""
    out = []
    t = np.asarray(t, dtype=float)
    lag = (t[:, 0] - np.minimum(t[:, 1], t[:, 2])) / U
    big = np.maximum(0, t[:, 0] - t[:, 1:].min(axis=1) - 0.04) / U
    out.append((PI["n1_lag"], CI[(1, "逃げ")], lag))
    out.append((PI["n1_big"], CI[(1, "逃げ")], big))
    for c in range(2, 7):
        g = group(c)
        inner = t[:, :c - 1].min(axis=1)
        L = (inner - t[:, c - 1]) / U
        N = (t[:, c - 2] - t[:, c - 1]) / U
        A = (t[:, :c - 2].min(axis=1) - t[:, c - 2]) / U if c >= 3 else np.zeros(len(t))
        O = (t[:, :c].min(axis=1) - t[:, c]) / U if c <= 5 else np.zeros(len(t))
        H = (t[:, c - 2] - np.minimum(t[:, c - 3], t[:, c - 1])) / U if c >= 3 else np.zeros(len(t))
        out.append((PI[f"mk1_{g}"], CI[(c, "捲り")], L))
        out.append((PI[f"mk2_{g}"], CI[(c, "捲り")], np.maximum(0, L - 0.8)))
        out.append((PI[f"sa1_{g}"], CI[(c, "差し")], N))
        out.append((PI[f"sa2_{g}"], CI[(c, "差し")], np.maximum(0, A)))
        out.append((PI[f"sa3_{g}"], CI[(c, "差し")], np.maximum(0, O)))
        out.append((PI[f"ms1_{g}"], CI[(c, "捲り差し")], N))
        out.append((PI[f"ms2_{g}"], CI[(c, "捲り差し")], np.maximum(0, H)))
        out.append((PI[f"ms3_{g}"], CI[(c, "捲り差し")], np.maximum(0, A)))
    if wind is not None:
        w = max(0, wind - 3)
        if w:
            one = np.full(len(t), float(w))
            out.append((PI["w_nige"], CI[(1, "逃げ")], one))
            for c in range(2, 7):
                out.append((PI["w_mk"], CI[(c, "捲り")], one))
                out.append((PI["w_sa"], CI[(c, "差し")], one))
                out.append((PI["w_ms"], CI[(c, "捲り差し")], one))
    return out


# ======================================================================
# 展開の見立ての学習(実際のSTを使う)
# ======================================================================
class DevData:
    def __init__(self, recs):
        rs = [r for r in recs if r["clean"] and r["y"] is not None]
        self.n = len(rs)
        self.lp = np.zeros((self.n, NC))
        self.y = np.array([r["y"] for r in rs], dtype=int)
        rows, cls, prm, val = [], [], [], []
        t = np.array([[b["st"] for b in r["b"]] for r in rs], dtype=float) if rs else np.zeros((0, 6))
        for i, r in enumerate(rs):
            lp, terms = static_terms(r)
            self.lp[i] = lp
            for (j, k, v) in terms:
                rows.append(i); cls.append(k); prm.append(j); val.append(v)
        # STの項(全レースまとめて)
        winds = [r["wind"] for r in rs]
        if self.n:
            base = st_terms(t, None)
            for (j, k, v) in base:
                rows.extend(range(self.n)); cls.extend([k] * self.n); prm.extend([j] * self.n); val.extend(v.tolist())
            for i, w in enumerate(winds):
                if w is not None and w > 3:
                    for (j, k, v) in st_terms(t[i:i + 1], w)[len(base):]:
                        rows.append(i); cls.append(k); prm.append(j); val.append(float(v[0]))
        self.rows = np.array(rows, dtype=np.int64)
        self.cls = np.array(cls, dtype=np.int64)
        self.prm = np.array(prm, dtype=np.int64)
        self.val = np.array(val, dtype=float)
        self.recs = rs

    def util(self, th):
        u = self.lp.copy()
        np.add.at(u, (self.rows, self.cls), th[self.prm] * self.val)
        return u

    def nll_grad(self, th):
        u = self.util(th)
        u -= u.max(axis=1, keepdims=True)
        p = np.exp(u)
        p /= p.sum(axis=1, keepdims=True)
        ll = np.log(p[np.arange(self.n), self.y] + 1e-300).sum()
        r = p
        r[np.arange(self.n), self.y] -= 1                      # p - y
        g = np.zeros(NP)
        np.add.at(g, self.prm, r[self.rows, self.cls] * self.val)
        f = -ll + (REG * th * th).sum()
        return f, g + 2 * REG * th


def fit_dev(recs, th0=None):
    D = DevData(recs)
    if D.n < 500:
        return None, D
    th = np.zeros(NP) if th0 is None else th0.copy()
    res = minimize(lambda x: D.nll_grad(x), th, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return res.x, D


# ======================================================================
# スタートの見立て
# ======================================================================
def start_row(s, K, m_pop, vens):
    """予想STの式の説明変数(model.js の startMeans と同じ並び)。"""
    n, sm, _ = s["stx"]
    mr = (sm + K * m_pop) / (n + K)
    r8 = s.get("r8") or []
    rec = (sum(r8) + REC_ST_K * mr) / (len(r8) + REC_ST_K) - mr if r8 else 0.0
    nbm = [(x[1] + K * m_pop) / (x[0] + K) for x in s.get("nb") or []]
    nb = sum(nbm) / len(nbm) - m_pop if nbm else 0.0
    return ([1.0, mr] + [1.0 if s["c"] == c else 0.0 for c in range(2, 7)]
            + [1.0 if s["fp"] > 0 else 0.0, max(0, (s["wind"] or 0) - 3), 1.0 if s["fp"] >= 2 else 0.0, rec, nb]
            + [1.0 if s["v"] == v else 0.0 for v in vens[1:]])


REC_ST_K = 4              # 直近の平均STを、1年の平均に寄せる強さ(走数)
START_NAMES = ["a", "b"] + [f"c{c}" for c in range(2, 7)] + ["f", "wind", "f2", "rec", "nb"]


def fit_start(sts):
    """予想ST = a + b*選手の平均ST(走数で平均に寄せる) + コースの補正 + フライング持ち(F1・F2)の補正 + 風の補正
               + 直近の調子(直近8走の平均と1年の平均の差) + 隣の艇のスタートの傾向 + 場の補正。
    残りのばらつきを、レース全体でそろってずれる分・スロー/ダッシュの組でそろってずれる分・艇ごとの分に分ける。"""
    if len(sts) < 2000:
        return None
    allst = np.array([s["st"] for s in sts])
    m_pop = float(allst.mean())
    vens = sorted({s["v"] for s in sts})
    yv = allst
    best = None
    for K in (3, 6, 10, 15, 25):
        X = np.array([start_row(s, K, m_pop, vens) for s in sts])
        coef, *_ = np.linalg.lstsq(X, yv, rcond=None)
        rmse = float(np.sqrt(((X @ coef - yv) ** 2).mean()))
        if best is None or rmse < best[0]:
            best = (rmse, K, coef, X)
    rmse, K, coef, X = best
    nb_ = len(START_NAMES)
    ven = {v: round(float(x), 4) for v, x in zip(vens[1:], coef[nb_:])}
    ven[vens[0]] = 0.0
    sd_pop = float(np.sqrt(np.mean([((s["stx"][2] - s["stx"][1] ** 2 / s["stx"][0]) / s["stx"][0]) for s in sts if s["stx"][0] >= 10])))
    sm = {"K": K, "m_pop": round(m_pop, 4), "coef": {n: round(float(v), 5) for n, v in zip(START_NAMES, coef[:nb_])},
          "ven": ven, "REC_K": REC_ST_K, "sd_pop": round(sd_pop, 4), "rmse": round(rmse, 4), "n": len(sts)}
    # 予想からのずれ(実際のST − 予想ST)を、選手のばらつきの大きさで割って、レースごとに6艇分まとめて残す。
    # 本番前の見立てでは、過去のレースのずれ方をそのまま今日の6艇に当てはめる
    # (全員そろって遅れる日、スロー勢・ダッシュ勢でそろってずれる日、たまに大きく出遅れる艇がいる、といった形をそのまま使える)。
    resid = yv - X @ coef
    by = {}
    for s, e in zip(sts, resid):
        sc = racer_scale(sm, {"stx": s["stx"]})
        by.setdefault((s["d"], s["v"], s["no"]), {})[s["c"]] = e / sc
    full = [v for v in by.values() if len(v) == 6]
    rng = np.random.default_rng(11)
    pick = rng.choice(len(full), size=min(POOL, len(full)), replace=False)
    sm["pool"] = [[round(float(full[i][c]), 3) for c in range(1, 7)] for i in sorted(pick)]
    E = np.array([[v[c] for c in range(1, 7)] for v in full])
    sm["resid_sd"] = [round(float(x), 4) for x in E.std(axis=0)]
    return sm


POOL = 1200
EST_PRIOR, EST_PRIOR_N = 0.35, 200      # 展示STの効き方の初期値と、その重み(走数)


def live_est() -> dict:
    """取り込んだ直前情報の展示ST {(日付, 場, レース, 枠): 展示ST}。フライングだった展示は除く。"""
    out = {}
    for folder in sorted((DATA / "live").glob("[0-9]" * 8)):
        try:
            d = parse_ymd(folder.name)
        except ValueError:
            continue
        for f in folder.glob("[0-9][0-9].json"):
            v = load_json(f, {}) or {}
            for no, b in (v.get("before") or {}).items():
                if not b.get("ready"):
                    continue
                for w, x in (b.get("est") or {}).items():
                    if isinstance(x, (int, float)) and 0 <= x < 0.5:
                        out[(d, f.stem, int(no), int(w))] = x
    return out


def fit_est(sm, sts) -> None:
    """展示STの効き方。展示は本番より全体に早く出るので、6艇の中での差(レースの平均からのずれ)どうしで比べる:
    本番のSTの、予想STからのずれ(レースの平均を引いたもの) = est ×(展示STの、予想STからのずれ(同じく平均を引いたもの)) + 残り。
    展示STがあるとき、残りのばらつきが何倍になるか(est_scale)も求める。データが少ないうちは初期値(0.35)に寄せる。model.js と同じ式。"""
    ex = live_est()
    by = {}
    K, m_pop = sm["K"], sm["m_pop"]
    for s in sts:
        k = (s["d"], s["v"], s["no"], s.get("waku"))
        if k in ex:
            row = start_row(s, K, m_pop, [None])
            mu = sum(sm["coef"][n] * x for n, x in zip(START_NAMES, row)) + sm.get("ven", {}).get(s["v"], 0.0)
            by.setdefault((s["d"], s["v"], s["no"]), []).append((max(-0.02, min(0.35, ex[k])), s["st"], mu))
    xs, ys = [], []
    for rows in by.values():
        if len(rows) < 4:
            continue
        mE = sum(r[0] for r in rows) / len(rows)
        mY = sum(r[1] - r[2] for r in rows) / len(rows)
        mM = sum(r[2] for r in rows) / len(rows)
        for e, st, mu in rows:
            xs.append((e - mE) - (mu - mM))
            ys.append((st - mu) - mY)
    n = len(xs)
    sm["est_n"] = n
    if not n:
        return
    xs, ys = np.array(xs), np.array(ys)
    sxx = float((xs * xs).mean())
    coef = (float((xs * ys).sum()) + EST_PRIOR * EST_PRIOR_N * sxx) / (float((xs * xs).sum()) + EST_PRIOR_N * sxx)
    res0, res1 = float(np.var(ys)), float(np.var(ys - coef * xs))
    sm["coef"]["est"] = round(coef, 4)
    sm["est_scale"] = round(math.sqrt(max(0.5, min(1.0, res1 / res0))) if res0 > 0 and n >= 200 else 0.95, 3)


def racer_scale(sm, b):
    """この選手のSTのばらつきが、全体の平均的な選手の何倍か(走数が少ないほど1に寄せる)。model.js と同じ式。"""
    n, s1, s2 = b["stx"]
    sp2 = sm["sd_pop"] ** 2
    var_r = ((s2 - s1 * s1 / n) / n) if n >= 2 else sp2
    KS = 10
    var_r = (n * max(var_r, 0) + KS * sp2) / (n + KS)
    return math.sqrt(var_r / sp2)


def start_means(sm, rec):
    """6艇の予想ST。model.js の startMeans と同じ式。"""
    B = rec["b"]
    out = []
    for i, b in enumerate(B):
        s = {"stx": b["stx"], "r8": b.get("r8") or [], "fp": b["fp"], "c": b["c"], "wind": rec["wind"], "v": rec["v"],
             "nb": [B[j]["stx"] for j in (i - 1, i + 1) if 0 <= j < 6]}
        row = start_row(s, sm["K"], sm["m_pop"], [None])
        co = sm["coef"]
        out.append(sum(co[n] * x for n, x in zip(START_NAMES, row)) + sm.get("ven", {}).get(rec["v"], 0.0))
    return out


def sample_st(sm, rec, S, rng):
    mus = np.array(start_means(sm, rec))
    scs = np.array([racer_scale(sm, b) for b in rec["b"]])
    pool = np.array(sm["pool"])
    idx = rng.integers(0, len(pool), size=S)
    t = mus + scs * pool[idx]
    return np.clip(t, 0.0, 0.45), mus


def predict(th, sm, rec, S, rng):
    """本番前の見立て(STを多数作って平均)と、実際のSTでの見立て。戻り値: (p_pre[NC], p_st[NC] or None, mus)"""
    lp, terms = static_terms(rec)
    u0 = lp.copy()
    for (j, k, v) in terms:
        u0[k] += th[j] * v
    t, mus = sample_st(sm, rec, S, rng)
    U_ = np.tile(u0, (S, 1))
    for (j, k, v) in st_terms(t, rec["wind"]):
        U_[:, k] += th[j] * v
    U_ -= U_.max(axis=1, keepdims=True)
    P = np.exp(U_)
    P /= P.sum(axis=1, keepdims=True)
    p_pre = P.mean(axis=0)
    p_st = None
    if all(b["st"] is not None for b in rec["b"]):
        tt = np.array([[b["st"] for b in rec["b"]]])
        u1 = u0.copy()
        for (j, k, v) in st_terms(tt, rec["wind"]):
            u1[k] += th[j] * v[0]
        u1 -= u1.max()
        p_st = np.exp(u1) / np.exp(u1).sum()
    return p_pre, p_st, mus


# ======================================================================
# 2着〜6着の並び(1着の艇と決まり手ごと)。model.js の orderFor と同じ式
#   1着以外の5艇の点数 u = α[決まり手][1着の艇から見た位置] + β・(勝率・ST・展示・モーター・そのコースの2着率・競り合いの強さ)
#   2着から順に「残った艇の中で、点数に応じた割合で選ばれる」として学習する(5着まで。段ごとに点数の効き方 λ を変える)
# ======================================================================
KG = {"逃げ": 0, "捲り": 1, "差し": 2, "捲り差し": 3, "抜き": 4}
ORDER_FEATS = ["str", "st", "ex", "mot", "c2", "cb"]
ORD_K2 = 8
NF_ORD = len(ORDER_FEATS)


def rel_idx(d: int) -> int:
    """1着の艇から見た位置(-5〜-1, 1〜5)を 0〜9 に。"""
    return d + 5 if d < 0 else d + 4


def order_feats(r: dict, base2: list, t=None) -> list:
    """6艇(コース順)の特徴。t はST(なければ実際のST)。"""
    B = r["b"]
    pts = [(b["pts"][0] + PTS_K * PTS_MEAN) / (b["pts"][1] + PTS_K) for b in B]
    mp = sum(pts) / 6
    sts = list(t) if t is not None else [b.get("st") for b in B]
    ok = [x for x in sts if x is not None]
    sm = sum(ok) / len(ok) if ok else 0.15
    exs = [b.get("ex") for b in B]
    ex_ok = all(isinstance(x, (int, float)) and 6.0 <= x <= 7.6 for x in exs)
    exm = sum(exs) / 6 if ex_ok else None
    mots = [b.get("motor") for b in B]
    mm = [m for m in mots if m is not None]
    mmean = sum(mm) / len(mm) if mm else None
    out = []
    for i, b in enumerate(B):
        cs = b["cs"]
        bc = base2[i]
        c2 = math.log(((cs.get("w2", 0) + ORD_K2 * bc) / (cs.get("n", 0) + ORD_K2)) / bc)
        cb = b.get("cb") or [0, 0]
        out.append([pts[i] - mp,
                    (sm - sts[i]) / U if sts[i] is not None else 0.0,
                    (exm - exs[i]) / 0.05 if ex_ok else 0.0,
                    (mots[i] - mmean) / 10 if mmean is not None and mots[i] is not None else 0.0,
                    c2,
                    ((cb[0] + 2.5) / (cb[1] + 5) - 0.5) * 4])
    return out


def order_data(recs, base2):
    G, IDX, X, RK = [], [], [], []
    for r in recs:
        if not r["clean"] or r["y"] is None:
            continue
        ranks = [b.get("rank") for b in r["b"]]
        if sorted(x for x in ranks if x) != [1, 2, 3, 4, 5, 6]:
            continue
        cw, k = CLASSES[r["y"]]
        f = order_feats(r, base2)
        others = [c for c in range(1, 7) if c != cw]
        G.append(KG[k])
        IDX.append([rel_idx(c - cw) for c in others])
        X.append([f[c - 1] for c in others])
        RK.append([ranks[c - 1] for c in others])
    return np.array(G, dtype=int), np.array(IDX, dtype=int), np.array(X, dtype=float).reshape(-1, 5, NF_ORD), np.array(RK, dtype=int)


def order_unpack(th):
    a = th[:50].reshape(5, 10)
    b = th[50:50 + NF_ORD]
    lam = np.concatenate([[1.0], th[50 + NF_ORD:50 + NF_ORD + 3]])
    return a, b, lam


def order_nll(th, data):
    G, IDX, X, RK = data
    a, b, lam = order_unpack(th)
    Uu = a[G[:, None], IDX] + X @ b
    n = len(G)
    dU = np.zeros_like(Uu)
    ll = 0.0
    glam = np.zeros(4)
    for m in range(4):
        rem = RK >= m + 2
        ch = RK == m + 2
        z = np.where(rem, lam[m] * Uu, -np.inf)
        zmax = z.max(axis=1, keepdims=True)
        e = np.where(rem, np.exp(z - zmax), 0.0)
        ssum = e.sum(axis=1, keepdims=True)
        p = e / ssum
        ll += (lam[m] * (Uu * ch).sum(axis=1) - (np.log(ssum[:, 0]) + zmax[:, 0])).sum()
        dU += lam[m] * (ch - p)
        glam[m] = ((Uu * ch).sum(axis=1) - (p * np.where(rem, Uu, 0)).sum(axis=1)).sum()
    ga = np.zeros((5, 10))
    np.add.at(ga, (np.repeat(G, 5), IDX.ravel()), dU.ravel())
    gb = np.einsum("ij,ijk->k", dU, X)
    reg_a, reg_b, reg_l = 0.01, 0.5, 2.0
    f = -ll + reg_a * (a ** 2).sum() + reg_b * (b ** 2).sum() + reg_l * ((lam[1:] - 1) ** 2).sum()
    g = np.concatenate([-ga.ravel() + 2 * reg_a * a.ravel(), -gb + 2 * reg_b * b, -glam[1:] + 2 * reg_l * (lam[1:] - 1)])
    return f / max(1, n), g / max(1, n)


def base2_of(recs) -> list:
    """コースごとの2着の割合(全レース)。"""
    n = [0] * 6
    w = [0] * 6
    for r in recs:
        for i, b in enumerate(r["b"]):
            if b.get("rank"):
                n[i] += 1
                w[i] += 1 if b["rank"] == 2 else 0
    return [max(0.02, w[i] / n[i]) if n[i] else 1 / 6 for i in range(6)]


def fit_order(recs, base2):
    data = order_data(recs, base2)
    if len(data[0]) < 500:
        return None, data
    th0 = np.zeros(50 + NF_ORD + 3)
    th0[50 + NF_ORD:] = 1.0
    res = minimize(lambda x: order_nll(x, data), th0, jac=True, method="L-BFGS-B", options={"maxiter": 800})
    return res.x, data


def order_eval(th, data):
    """2着の艇を当てた割合と、2着・3着の対数尤度(1レースあたり)。"""
    G, IDX, X, RK = data
    a, b, lam = order_unpack(th)
    Uu = a[G[:, None], IDX] + X @ b
    hit2 = float(np.mean(np.argmax(Uu, axis=1) == np.argmax(RK == 2, axis=1)))
    p = np.exp(Uu - Uu.max(axis=1, keepdims=True))
    p /= p.sum(axis=1, keepdims=True)
    ll2 = float(np.mean(np.log(p[RK == 2])))
    o3 = np.argsort(-Uu, axis=1)[:, :2]
    hit23 = float(np.mean((np.take_along_axis(RK, o3, axis=1) == np.array([2, 3])).all(axis=1)))
    return {"races": int(len(G)), "hit2": round(hit2 * 100, 1), "hit23": round(hit23 * 100, 1), "ll2": round(ll2, 4)}


def order_model(th, base2):
    a, b, lam = order_unpack(th)
    return {"alpha": {k: [round(float(x), 4) for x in a[g]] for k, g in KG.items()},
            "beta": {n: round(float(v), 4) for n, v in zip(ORDER_FEATS, b)},
            "lam": [round(float(x), 4) for x in lam], "K2": ORD_K2, "base2": [round(x, 4) for x in base2]}


# ======================================================================
# 答え合わせ
# ======================================================================
def evaluate(th, sm, recs, label):
    rng = np.random.default_rng(7)
    rows = [r for r in recs if r["y"] is not None and r["clean"]]
    if not rows:
        return None
    nll = nll0 = nll_st = 0.0
    top1 = top3 = wc = top1_st = 0
    bins = [[0, 0.0, 0] for _ in range(10)]          # 予想の起こりやすさごとに、実際に起きた割合
    by_kim = {k: [0.0, 0] for k in ("逃げ", "捲り", "差し", "捲り差し", "抜き")}
    st_err, st_n = 0.0, 0
    deko = [[0.0, 0], [0.0, 0]]                       # [出る, 凹む] の予想の合計と、実際に起きた回数
    by_day: dict = {}
    misses = []
    for r in rows:
        p, pst, mus = predict(th, sm, r, N_SAMPLES, rng)
        lp, _ = static_terms(r)
        p0 = np.exp(lp); p0 /= p0.sum()
        y = r["y"]
        nll -= math.log(max(p[y], 1e-9)); nll0 -= math.log(max(p0[y], 1e-9))
        order = np.argsort(-p)
        top1 += int(order[0] == y); top3 += int(y in order[:3])
        pcourse = np.zeros(6)
        for i, (c, k) in enumerate(CLASSES):
            pcourse[c - 1] += p[i]
        wc += int(np.argmax(pcourse) + 1 == CLASSES[y][0])
        if pst is not None:
            nll_st -= math.log(max(pst[y], 1e-9)); top1_st += int(np.argmax(pst) == y)
        for i in range(NC):
            bi = min(9, int(p[i] * 10))
            bins[bi][0] += 1; bins[bi][1] += p[i]; bins[bi][2] += int(i == y)
        for k in by_kim:
            by_kim[k][0] += sum(p[i] for i, (c, kk) in enumerate(CLASSES) if kk == k)
        by_kim[CLASSES[y][1]][1] += 1
        sts = [b["st"] for b in r["b"]]
        for c in range(6):
            st_err += (mus[c] - sts[c]) ** 2; st_n += 1
        # 出る・凹むの予想(隣の艇との差0.05秒)
        tt, _ = sample_st(sm, r, 200, rng)
        for c in range(6):
            nb = [j for j in (c - 1, c + 1) if 0 <= j < 6]
            nbs = tt[:, nb]
            p_out = float(np.mean(tt[:, c] <= nbs.min(axis=1) - 0.05))
            p_dent = float(np.mean(tt[:, c] >= nbs.max(axis=1) + 0.05))
            a_out = sts[c] <= min(sts[j] for j in nb) - 0.05
            a_dent = sts[c] >= max(sts[j] for j in nb) + 0.05
            deko[0][0] += p_out; deko[0][1] += int(a_out)
            deko[1][0] += p_dent; deko[1][1] += int(a_dent)
        key = r["d"].isoformat()
        dd = by_day.setdefault(key, [0, 0, 0.0])
        dd[0] += 1; dd[1] += int(order[0] == y); dd[2] += p[y]
        if p[y] < 0.04 and pst is not None:
            misses.append({"d": key, "v": r["v"], "no": r["no"], "y": "%d%s" % CLASSES[y], "p": round(float(p[y]) * 100, 1),
                           "p_st": round(float(pst[y]) * 100, 1)})
    n = len(rows)
    misses.sort(key=lambda m: m["p_st"] - m["p"], reverse=True)
    return {"label": label, "races": n, "from": min(r["d"] for r in rows).isoformat(), "to": max(r["d"] for r in rows).isoformat(),
            "nll": round(nll / n, 4), "nll_prior": round(nll0 / n, 4), "nll_with_st": round(nll_st / n, 4),
            "top1": round(top1 / n * 100, 1), "top3": round(top3 / n * 100, 1), "winner_course": round(wc / n * 100, 1),
            "top1_with_st": round(top1_st / n * 100, 1),
            "calib": [[round(b[1] / b[0] * 100, 1), round(b[2] / b[0] * 100, 1), b[0]] for b in bins if b[0]],
            "kimarite": {k: [round(v[0] / n * 100, 1), round(v[1] / n * 100, 1)] for k, v in by_kim.items()},
            "st_rmse": round(math.sqrt(st_err / st_n), 4),
            "out": [round(deko[0][0] / st_n * 100, 1), round(deko[0][1] / st_n * 100, 1)],
            "dent": [round(deko[1][0] / st_n * 100, 1), round(deko[1][1] / st_n * 100, 1)],
            "by_day": [[k, v[0], round(v[1] / v[0] * 100, 1), round(v[2] / v[0] * 100, 1)] for k, v in sorted(by_day.items())],
            "misses": misses[:12]}


def conditional_st(th, sm, recs, S=120):
    """決着パターンごとに、STがふだんよりどれだけ早かった・遅かったか(実際の結果から)。映像のSTの参考に使う。"""
    acc = {}
    for r in recs:
        if r["y"] is None or not r["clean"]:
            continue
        devs = [b["st"] - mu for b, mu in zip(r["b"], start_means(sm, r))]
        m = sum(devs) / 6
        a = acc.setdefault(r["y"], [np.zeros(6), 0])
        a[0] += np.array(devs) - m
        a[1] += 1
    return {"%d%s" % CLASSES[y]: [round(float(x), 4) for x in (v[0] / v[1])] + [v[1]] for y, v in acc.items() if v[1] >= 30}


def main() -> int:
    recs, sts = build_records()
    if len(recs) < 1000:
        print("学習に使えるレースが少ないので、学習しません:", len(recs))
        return 0
    last = max(r["d"] for r in recs)
    span = (last - min(r["d"] for r in recs)).days + 1
    eval_days = min(EVAL_DAYS, max(7, span // 3))     # データが少ないうちは、答え合わせの期間を短くする
    cut = last - dt.timedelta(days=eval_days - 1)
    train = [r for r in recs if r["d"] < cut]
    test = [r for r in recs if r["d"] >= cut]
    sm_tr = fit_start([s for s in sts if s["d"] < cut])
    ev = None
    if sm_tr and len(train) >= 2000:
        th_tr, _ = fit_dev(train)
        if th_tr is not None:
            ev = evaluate(th_tr, sm_tr, test, f"学習に使っていない直近{eval_days}日")
    # 2着以下の並びの学習と答え合わせ(学習に使っていない直近の日で)
    base2 = base2_of(recs)
    ord_ev = None
    if len(train) >= 2000:
        th_o, _ = fit_order(train, base2)
        if th_o is not None:
            ord_ev = order_eval(th_o, order_data(test, base2))
    th_ord, _ = fit_order(recs, base2)
    # 全期間で学習し直す(翌日からの見立てに使う)
    sm = fit_start(sts)
    if sm:
        fit_est(sm, sts)
    th, D = fit_dev(recs)
    if th is None or sm is None:
        print("学習できませんでした")
        return 1
    model = {"version": 1, "fitted": today_jst().isoformat(), "train": {"from": min(r["d"] for r in recs).isoformat(),
                                                                       "to": last.isoformat(), "races": D.n},
             "const": {"PTS_MEAN": PTS_MEAN, "PTS_K": PTS_K, "REC_K": REC_K, "TAC_K": TAC_K, "LS_K": LS_K,
                       "VEN_M": VEN_M, "VEN_KM": VEN_KM, "U": U},
             "classes": ["%d%s" % ck for ck in CLASSES],
             "dev": {n: round(float(v), 4) for n, v in zip(PARAMS, th)},
             "start": sm, "cond_st": conditional_st(th, sm, recs)}
    if th_ord is not None:
        model["order"] = order_model(th_ord, base2)
    save_json(DATA / "model.json", model)
    if ev:
        hist = load_json(DATA / "eval.json", {}) or {}
        runs = [x for x in hist.get("runs", []) if x.get("fitted") != model["fitted"]][-29:]
        runs.append({"fitted": model["fitted"], "races": ev["races"], "nll": ev["nll"], "nll_prior": ev["nll_prior"],
                     "top1": ev["top1"], "top3": ev["top3"], "winner_course": ev["winner_course"], "order": ord_ev})
        save_json(DATA / "eval.json", {"latest": ev, "order": ord_ev, "runs": runs})
    print(json.dumps({"train_races": D.n, "start_rmse": sm["rmse"], "eval": {k: ev[k] for k in ("races", "nll", "nll_prior", "nll_with_st",
                                                                                               "top1", "top3", "winner_course", "top1_with_st",
                                                                                               "st_rmse", "out", "dent")} if ev else None},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
