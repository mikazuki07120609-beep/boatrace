#!/usr/bin/env python3
"""裏水面ノートの学習(1日1回)。結果は data/ura.json(ページの ura.js と、答え合わせが使う)。

過去のレースの見立て(fit.py と同じ。展示タイム・進入は実際のもの)から3連単120通りの起こりやすさを出し、
実際の払戻金(data/pays。公式の競走成績ファイルから)と比べて、次の3つを学ぶ。
  1) 市場の目安: 見立ての起こりやすさ q の組み合わせが、だいたい何倍で売れるか(log 倍 = a + b·log q、ばらつき s)
     オッズが出る前の「この組み合わせが万舟(100倍以上)になる見込み」に使う
  2) 万舟の見込みの補正: 見立てから出した万舟の見込み m を、風・波・場・レースの種類・前づけで補正する(ロジスティック回帰)
  3) 荒れの集計(理由の説明に使う): 場ごとの万舟率と、風・波・時間帯・風向きごとの万舟率、最近の万舟 など
直近 EVAL_DAYS 日は学習に使わずに答え合わせし、裏本線(表の本線の艇以外で、その決着になって万舟になる見込みが一番高い決着)の
当たり方と、当たったときの配当も残す(成績のページに出す)。

  python3 scripts/ura_fit.py            # 毎晩(scripts/update.py から。その日にまだ学習していなければ)
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sys

import numpy as np
from scipy.optimize import minimize

import fit
import ura
from common import DATA, RESULTS, load_json, parse_ymd, save_json, today_jst
from stats import races_of

PAYS = DATA / "pays"
OUT = DATA / "ura.json"
MAN = 10000
EVAL_DAYS = 30
FIT_DAYS = 240                 # 見立てを計算して学習に使う日数(古すぎる日は使わない。毎晩の計算時間のため)
WIND_B = [(0, 2, "0-2"), (3, 4, "3-4"), (5, 6, "5-6"), (7, 99, "7+")]
WAVE_B = [(0, 2, "0-2"), (3, 5, "3-5"), (6, 9, "6-9"), (10, 999, "10+")]
TIME_B = [(1, 4, "1-4"), (5, 8, "5-8"), (9, 12, "9-12")]
KINDS = ["final", "semi", "dream", "select", "special", "yosen", "ippan"]   # その他(冠のレース)が基準
DIR8 = {"北": "北", "北北東": "北", "北東": "北東", "東北東": "北東", "東": "東", "東南東": "東", "南東": "南東", "南南東": "南東",
        "南": "南", "南南西": "南", "南西": "南西", "西南西": "南西", "西": "西", "西北西": "西", "北西": "北西", "北北西": "北西"}
K_SHRINK = 60                  # 場ごと・条件ごとの万舟率を、上の段の率に寄せる強さ(レース数)


def bucket(x, bs):
    if x is None:
        return None
    for lo, hi, name in bs:
        if lo <= x <= hi:
            return name
    return None


def load_pays() -> dict:
    out = {}
    for p in sorted(PAYS.glob("*.json")):
        d = load_json(p, {}) or {}
        for v, races in (d.get("venues") or {}).items():
            for no, pay in races.items():
                t3 = pay.get("3t") or []
                if len(t3) == 1 and t3[0][1]:
                    out[(p.stem, v, int(no))] = {"c": t3[0][0], "y": t3[0][1], "pop": t3[0][2],
                                                  "tan": {w: y for w, y in pay.get("tan", [])}}
    return out


def load_meta() -> dict:
    """成績から、レースごとの コース→枠・風向・波・決まり手・1着のコース。"""
    out = {}
    for p in sorted(RESULTS.glob("*.json")):
        day = load_json(p, {}) or {}
        for v, vv in day.get("venues", {}).items():
            for r in races_of(vv):
                ents = r.get("entries", [])
                c2w = {e["course"]: e["waku"] for e in ents if e.get("course")}
                win = next((e for e in ents if e.get("rank") == 1), None)
                out[(p.stem, v, r["no"])] = {"c2w": c2w, "dir": r.get("wind_dir"), "wave": r.get("wave"), "wind": r.get("wind"),
                                             "kim": fit.kim_class(r.get("kimarite")) if r.get("kimarite") else None,
                                             "wc": win.get("course") if win else None}
    return out


def combo_courses(combo: str, c2w: dict):
    w2c = {w: c for c, w in c2w.items()}
    try:
        cs = [w2c[int(x)] for x in combo.split("-")]
    except (KeyError, ValueError):
        return None
    return cs if len(set(cs)) == 3 else None


def phi(z):
    return 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))


def man_given(T: np.ndarray, px: dict) -> np.ndarray:
    """組み合わせ(コース)ごとの、万舟になる見込み(市場の目安から)。"""
    q = np.maximum(T, 1e-7)
    return phi((px["a"] + px["b"] * np.log(q) - math.log(100)) / px["s"])


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def feat(m, x, vens) -> list:
    """補正の特徴(ura.js の calib と同じ並び)。"""
    f = [1.0, logit(m)]
    wb = bucket(x.get("wind"), WIND_B)
    f += [1.0 if wb == n else 0.0 for _, _, n in WIND_B[1:]]
    vb = bucket(x.get("wave"), WAVE_B)
    f += [1.0 if vb == n else 0.0 for _, _, n in WAVE_B[1:]]
    f += [1.0 if x.get("kind") == k else 0.0 for k in KINDS]
    f.append(1.0 if x.get("mz") else 0.0)
    f += [1.0 if x["v"] == v else 0.0 for v in vens]
    return f


def fit_logit(X, y, reg):
    X = np.asarray(X, float)
    y = np.asarray(y, float)

    def nll(w):
        z = X @ w
        p = 1 / (1 + np.exp(-z))
        ll = -(y * np.log(np.maximum(p, 1e-9)) + (1 - y) * np.log(np.maximum(1 - p, 1e-9))).sum()
        g = X.T @ (p - y)
        return ll + (reg * w * w).sum(), g + 2 * reg * w
    w0 = np.zeros(X.shape[1])
    res = minimize(nll, w0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return res.x


def auc(s, y):
    s = np.asarray(s)
    y = np.asarray(y, bool)
    o = np.argsort(s)
    r = np.empty(len(s))
    r[o] = np.arange(1, len(s) + 1)
    n1 = y.sum()
    n0 = len(y) - n1
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else None


def shrink(k, n, base, K=K_SHRINK):
    return (k + K * base) / (n + K)


def main(recs=None) -> int:
    pays = load_pays()
    if len(pays) < 3000:
        print("払戻金のデータがまだ少ないので、裏の学習をしません:", len(pays))
        return 0
    meta = load_meta()
    M = load_json(DATA / "model.json", None)
    if not M:
        return 0
    if recs is None:
        recs, _ = fit.build_records()
    th = np.array([M["dev"].get(n, 0.0) for n in fit.PARAMS])
    sm = M["start"]
    OP = ura.order_params(M)
    last = max(r["d"] for r in recs)
    lo = last - dt.timedelta(days=FIT_DAYS - 1)
    cut = last - dt.timedelta(days=EVAL_DAYS - 1)
    rng = np.random.default_rng(5)
    rows = []
    for r in recs:
        if r["d"] < lo:
            continue
        key = (r["d"].strftime("%Y%m%d"), r["v"], r["no"])
        pv, mt = pays.get(key), meta.get(key)
        if not pv or not mt or sorted(mt["c2w"]) != [1, 2, 3, 4, 5, 6]:
            continue
        cs = combo_courses(pv["c"], mt["c2w"])
        if not cs:
            continue
        p22, cond = ura.class_tri(r, th, sm, OP, rng, S=150)
        T = np.zeros((6, 6, 6))
        for i, (cw, _) in enumerate(ura.CLASSES):
            T[cw - 1] += p22[i] * cond[i]
        rows.append({"d": r["d"], "v": r["v"], "no": r["no"], "y": r["y"], "kind": r["kind"], "mz": r["mz"],
                     "wind": mt["wind"], "wave": mt["wave"], "dir": mt["dir"], "c2w": mt["c2w"], "cs": cs, "yen": pv["y"], "pop": pv["pop"],
                     "tan": pv["tan"], "p22": p22, "cond": cond.astype(np.float32), "T": T})
    if len(rows) < 3000:
        print("学習に使えるレースが少ないので、裏の学習をしません:", len(rows))
        return 0
    tr = [x for x in rows if x["d"] < cut]
    te = [x for x in rows if x["d"] >= cut]
    vens = sorted({x["v"] for x in rows})

    def fit_all(sub):
        # 1) 市場の目安(実際に来た組み合わせの、見立ての起こりやすさと配当)
        q = np.array([max(x["T"][x["cs"][0] - 1, x["cs"][1] - 1, x["cs"][2] - 1], 1e-7) for x in sub])
        Y = np.log(np.array([x["yen"] for x in sub]) / 100)
        A = np.vstack([np.ones(len(q)), np.log(q)]).T
        coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
        s = float((Y - A @ coef).std())
        px = {"a": float(coef[0]), "b": float(coef[1]), "s": s}
        # 2) 見立ての万舟の見込みの補正
        ms = [float((x["T"] * man_given(x["T"], px)).sum()) for x in sub]
        X = [feat(m, x, vens) for m, x in zip(ms, sub)]
        yy = [x["yen"] >= MAN for x in sub]
        reg = np.array([0.0, 0.0] + [1.0] * (len(WIND_B) - 1 + len(WAVE_B) - 1 + len(KINDS) + 1) + [3.0] * len(vens))
        w = fit_logit(X, yy, reg)
        return px, w

    def score(sub, px, w):
        out = []
        for x in sub:
            G = man_given(x["T"], px)
            m = float((x["T"] * G).sum())
            pm = 1 / (1 + math.exp(-float(np.dot(feat(m, x, vens), w))))
            # 表の本線: 1着になる見込み(勝ち方を全部足したもの)が一番高い艇
            pc = np.zeros(6)
            for i, (cw, _) in enumerate(ura.CLASSES):
                pc[cw - 1] += x["p22"][i]
            oc = int(np.argmax(pc)) + 1
            # 裏本線: 表の本線の艇以外で、その決着になって万舟になる見込み(補正したもの)が一番高い決着
            best, bs, bk = None, -1.0, 0.0
            fx = feat(m, x, vens)
            for i, (cw, k) in enumerate(ura.CLASSES):
                if cw == oc or k == "抜き":
                    continue
                mk = float((x["cond"][i] * G[cw - 1]).sum())
                fk = list(fx)
                fk[1] = logit(mk)
                pk = 1 / (1 + math.exp(-float(np.dot(fk, w))))
                sc = x["p22"][i] * pk
                if sc > bs:
                    best, bs, bk = i, sc, pk
            out.append({"x": x, "m": m, "pm": pm, "oc": oc, "u": best, "uk": bk})
        return out

    def summarize(sc):
        y = np.array([s["x"]["yen"] >= MAN for s in sc])
        pm = np.array([s["pm"] for s in sc])
        base = {}
        for s in sc:
            b = base.setdefault(s["x"]["v"], [0, 0])
            b[0] += s["x"]["yen"] >= MAN
            b[1] += 1
        n = len(sc)
        ll = float(-np.mean(np.where(y, np.log(pm), np.log(1 - pm))))
        hit = [s for s in sc if s["x"]["y"] is not None and ura.CLASSES[s["u"]][0] == ura.CLASSES[s["x"]["y"]][0]]
        hitk = [s for s in hit if ura.CLASSES[s["u"]][1] == ura.CLASSES[s["x"]["y"]][1]]
        ohit = [s for s in sc if s["x"]["y"] is not None and s["oc"] == ura.CLASSES[s["x"]["y"]][0]]

        def tan_roi(lst, pick):
            ret = 0
            for s in sc:
                c = pick(s)
                wk = s["x"]["c2w"].get(c)
                ret += s["x"]["tan"].get(wk, 0) if wk else 0
            return round(ret / n, 1)
        order = np.argsort(-pm)
        top = order[: max(1, n // 5)]
        bins = []
        for lo_, hi_ in ((0, .1), (.1, .15), (.15, .2), (.2, .25), (.25, .3), (.3, .4), (.4, 1.01)):
            sel = (pm >= lo_) & (pm < hi_)
            if sel.sum() >= 30:
                bins.append([round(float(pm[sel].mean()) * 100, 1), round(float(y[sel].mean()) * 100, 1), int(sel.sum())])
        return {"races": n, "from": min(s["x"]["d"] for s in sc).isoformat(), "to": max(s["x"]["d"] for s in sc).isoformat(),
                "man": round(float(y.mean()) * 100, 1), "pm": round(float(pm.mean()) * 100, 1), "auc": round(auc(pm, y), 3), "ll": round(ll, 4),
                "top20_man": round(float(y[top].mean()) * 100, 1), "calib": bins,
                "ura_hit": round(len(hit) / n * 100, 1), "ura_hitk": round(len(hitk) / n * 100, 1),
                "ura_pay": round(float(np.mean([s["x"]["yen"] for s in hit]))) if hit else None,
                "ura_pay_med": round(float(np.median([s["x"]["yen"] for s in hit]))) if hit else None,
                "ura_man": round(float(np.mean([s["x"]["yen"] >= MAN for s in hit])) * 100, 1) if hit else None,
                "ura_tan": tan_roi(hit, lambda s: ura.CLASSES[s["u"]][0]),
                "omote_hit": round(len(ohit) / n * 100, 1),
                "omote_pay": round(float(np.mean([s["x"]["yen"] for s in ohit]))) if ohit else None,
                "omote_tan": tan_roi(ohit, lambda s: s["oc"])}

    ev = None
    if len(tr) >= 3000 and len(te) >= 500:
        px_tr, w_tr = fit_all(tr)
        ev = summarize(score(te, px_tr, w_tr))
    px, w = fit_all(rows)
    back = summarize(score(rows, px, w))
    # 3) 荒れの集計(理由の説明に使う。払戻金がある日の全部)
    allr = []
    for key, pv in pays.items():
        mt = meta.get(key)
        if mt:
            allr.append((key, pv, mt))
    nat_n = len(allr)
    nat_k = sum(1 for _, pv, _ in allr if pv["y"] >= MAN)
    nat = nat_k / nat_n
    st = {"nat": round(nat * 100, 1), "n": nat_n, "ven": {}, "wind": {}, "wave": {}, "time": {}, "dir": {}, "recent": {}, "kim": {}, "pop": {}}
    by_v: dict = {}
    for key, pv, mt in allr:
        by_v.setdefault(key[1], []).append((key, pv, mt))
    for v, lst in by_v.items():
        k = sum(1 for _, pv, _ in lst if pv["y"] >= MAN)
        vr = shrink(k, len(lst), nat, 30)
        st["ven"][v] = [round(vr * 100, 1), len(lst)]
        for name, bs, getter in (("wind", WIND_B, lambda mt, key: mt.get("wind")), ("wave", WAVE_B, lambda mt, key: mt.get("wave")),
                                 ("time", TIME_B, lambda mt, key: key[2])):
            acc = {}
            for key, pv, mt in lst:
                b = bucket(getter(mt, key), bs)
                if b:
                    a = acc.setdefault(b, [0, 0])
                    a[0] += pv["y"] >= MAN
                    a[1] += 1
            st[name][v] = {b: [round(shrink(a[0], a[1], vr) * 100, 1), a[1]] for b, a in acc.items()}
        acc = {}
        for key, pv, mt in lst:
            d8 = DIR8.get(mt.get("dir") or "")
            if d8 and (mt.get("wind") or 0) >= 3:
                a = acc.setdefault(d8, [0, 0])
                a[0] += pv["y"] >= MAN
                a[1] += 1
        st["dir"][v] = {b: [round(shrink(a[0], a[1], vr) * 100, 1), a[1]] for b, a in acc.items() if a[1] >= 15}
        rec = sorted((x for x in lst if x[1]["y"] >= MAN), key=lambda x: (x[0][0], x[0][2]), reverse=True)[:8]
        st["recent"][v] = [[f"{key[0][4:6]}/{key[0][6:]}", key[2], pv["c"], pv["y"], pv["pop"], mt.get("wc"), mt.get("kim")] for key, pv, mt in rec]
    # 1着のコース・決まり手ごとの万舟の割合(全国)と、3連単の人気(何番人気の組が来たか)
    acc = {}
    for key, pv, mt in allr:
        if mt.get("wc") and mt.get("kim"):
            a = acc.setdefault(f'{mt["wc"]}{mt["kim"]}', [0, 0, 0])
            a[0] += pv["y"] >= MAN
            a[1] += 1
            a[2] += pv["y"]
    st["kim"] = {k: [round(a[0] / a[1] * 100, 1), a[1], round(a[2] / a[1])] for k, a in acc.items() if a[1] >= 30}
    pops = [pv["pop"] for _, pv, _ in allr if pv.get("pop")]
    st["pop"] = {"median": int(np.median(pops)) if pops else None, "man_pop": int(np.median([pv["pop"] for _, pv, _ in allr if pv["y"] >= MAN and pv.get("pop")])) if pops else None}
    # 前づけ・1コースの1着の見込み・6艇の力の差ごとの万舟率(見立てを計算したレースから)
    def rate(sel):
        y = [s["x"]["yen"] >= MAN for s in sel]
        return [round(float(np.mean(y)) * 100, 1), len(y)] if y else None
    sc_all = score(rows, px, w)
    st["mz"] = [rate([s for s in sc_all if s["x"]["mz"]]), rate([s for s in sc_all if not s["x"]["mz"]])]
    p1b = []
    for lo_, hi_ in ((0, .35), (.35, .45), (.45, .55), (.55, .65), (.65, 1.01)):
        sel = [s for s in sc_all if lo_ <= s["x"]["p22"][0] + s["x"]["p22"][1] < hi_]
        r_ = rate(sel)
        if r_:
            p1b.append([round(lo_ * 100), round(min(hi_, 1) * 100)] + r_)
    st["p1"] = p1b
    out = {"version": 1, "fitted": today_jst().isoformat(), "data_to": last.isoformat(), "man": MAN,
           "proxy": {k: round(v, 4) for k, v in px.items()},
           "cal": {"w": [round(float(x), 4) for x in w], "vens": vens, "wind": [b[2] for b in WIND_B], "wave": [b[2] for b in WAVE_B], "kinds": KINDS},
           "eval": ev, "back": back, "stats": st}
    save_json(OUT, out)
    print(json.dumps({"rows": len(rows), "proxy": out["proxy"], "eval": ev, "back": {k: back[k] for k in ("races", "man", "auc", "ura_hit", "ura_pay", "ura_tan", "omote_tan")}},
                     ensure_ascii=False))
    return 0


def due() -> bool:
    """今日まだ学習していないか。"""
    x = load_json(OUT, None) or {}
    return x.get("fitted") != today_jst().isoformat()


if __name__ == "__main__":
    sys.exit(main())
