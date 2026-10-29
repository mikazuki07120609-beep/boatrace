"""裏水面ノートの計算(学習と答え合わせで使う部分。ページでは site/assets/ura.js が同じ式で計算する)。

見立て(fit.py・model.js の「1着のコース×決まり手」22通りと、2着〜6着の並び)から、3連単120通りの起こりやすさを出し、
  - 万舟(3連単の払戻金が1万円以上)になる見込み
  - 決着ごとの「その決着になったときに万舟になる見込み」と、裏本線(荒れるとしたら一番ありそうな決着)
を計算する。オッズが分からないときの配当は、学習した「見立ての起こりやすさ → 配当」の関係(市場の目安)で見積もる。
"""
from __future__ import annotations

import math

import numpy as np

import fit

CLASSES = fit.CLASSES
NC = fit.NC
KG = fit.KG
MAN = 10000                 # 万舟(3連単の払戻金。100円あたり)


def order_params(M: dict):
    O = M.get("order")
    if not O:
        return None
    beta = np.array([O["beta"].get(n, 0.0) for n in fit.ORDER_FEATS])
    alpha = {k: np.array(v) for k, v in O["alpha"].items()}
    return {"alpha": alpha, "beta": beta, "lam": O["lam"], "base": {"b2": O["base2"], "b3": O["base3"]}}


def _soft(u: np.ndarray, lam: float) -> np.ndarray:
    z = lam * u
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


def race_probs(rec: dict, th: np.ndarray, sm: dict, OP: dict, rng, S: int = 200):
    """1レースの見立て。戻り値: (p22[NC], tri[6,6,6] 1・2・3着のコース(0始まり)の起こりやすさ, mus)
    model.js の predict → order(postST) と同じ考え方(1着の決着ごとに、その決着が起きやすいSTの組み合わせで2・3着を見る)。"""
    lp, terms = fit.static_terms(rec)
    u0 = lp.copy()
    for (j, k, v) in terms:
        u0[k] += th[j] * v
    t, mus = fit.sample_st(sm, rec, S, rng)
    U_ = np.tile(u0, (S, 1))
    for (j, k, v) in fit.st_terms(t, rec["wind"]):
        U_[:, k] += th[j] * v
    U_ -= U_.max(axis=1, keepdims=True)
    P = np.exp(U_)
    P /= P.sum(axis=1, keepdims=True)
    p22 = P.mean(axis=0)
    w = P.sum(axis=0)
    post = (P.T @ t) / np.where(w > 0, w, 1)[:, None]          # 決着ごとの、よくあるSTの組み合わせ
    tri = np.zeros((6, 6, 6))
    if OP is None:
        return p22, tri, mus
    lam0, lam1 = OP["lam"][0], OP["lam"][1]
    for i, (cw, k) in enumerate(CLASSES):
        if p22[i] < 1e-7:
            continue
        f = fit.order_feats(rec, OP["base"], list(post[i]), k, cw)
        rest = [c for c in range(1, 7) if c != cw]
        al = OP["alpha"][k]
        u = np.array([al[fit.rel_idx(c - cw)] + float(np.dot(f[c - 1], OP["beta"])) for c in rest])
        p2 = _soft(u, lam0)
        for ai, a in enumerate(rest):
            others = [j for j in range(5) if j != ai]
            q = _soft(u[others], lam1)
            for qi, bj in enumerate(others):
                tri[cw - 1, a - 1, rest[bj] - 1] += p22[i] * p2[ai] * q[qi]
    return p22, tri, mus


def class_tri(rec, th, sm, OP, rng, S=200):
    """決着(22通り)ごとの、2・3着の起こりやすさも返す版。戻り値: (p22, cond[NC, 6, 6])(cond は決着ごとに合計1)"""
    lp, terms = fit.static_terms(rec)
    u0 = lp.copy()
    for (j, k, v) in terms:
        u0[k] += th[j] * v
    t, _ = fit.sample_st(sm, rec, S, rng)
    U_ = np.tile(u0, (S, 1))
    for (j, k, v) in fit.st_terms(t, rec["wind"]):
        U_[:, k] += th[j] * v
    U_ -= U_.max(axis=1, keepdims=True)
    P = np.exp(U_)
    P /= P.sum(axis=1, keepdims=True)
    p22 = P.mean(axis=0)
    w = P.sum(axis=0)
    post = (P.T @ t) / np.where(w > 0, w, 1)[:, None]
    cond = np.zeros((NC, 6, 6))
    if OP is None:
        return p22, cond
    lam0, lam1 = OP["lam"][0], OP["lam"][1]
    for i, (cw, k) in enumerate(CLASSES):
        f = fit.order_feats(rec, OP["base"], list(post[i]), k, cw)
        rest = [c for c in range(1, 7) if c != cw]
        al = OP["alpha"][k]
        u = np.array([al[fit.rel_idx(c - cw)] + float(np.dot(f[c - 1], OP["beta"])) for c in rest])
        p2 = _soft(u, lam0)
        for ai, a in enumerate(rest):
            others = [j for j in range(5) if j != ai]
            q = _soft(u[others], lam1)
            for qi, bj in enumerate(others):
                cond[i, a - 1, rest[bj] - 1] += p2[ai] * q[qi]
    return p22, cond


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
