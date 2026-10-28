"""イン飛び警戒アラートと、カドまくり警戒アラート(どちらも3段階: 特別警報・警報・注意報)。

イン飛び: 1コースの選手の1コース1着率と、2コースの選手の逃がし率(2コースのときに1コースが逃げた割合)が、
          どちらも低いとき。2つの高い方が 40%以下で注意報、33%以下で警報、25%以下で特別警報(どちらも3走以上のとき)。
カドまくり: 4コース(カド)の選手が、4コースでよく捲って勝っていて(捲り1着が走数の8%以上。走数が少ないうちは平均に寄せる)、
          予想STが1〜3コースのどの艇よりも早いとき。差が0.00秒以上で注意報、0.01秒以上で警報、0.02秒以上で特別警報。
過去45日の約6800レースで確かめると、1コースの1着率はふだん56%のところ、イン飛びの注意報42%・警報39%・特別警報28%、
4コースの捲りはふだん5%のところ、カドまくりの注意報11%・警報11%・特別警報15%だった。
予想STは site/assets/model.js の startMeans と同じ式(展示の前なので、展示STは使わない)。
レースのページでは、スタート展示のあとに、展示の進入と展示STで計算し直す(race.js)。
"""
from __future__ import annotations

IN_LEVELS = ((0.25, 3), (0.33, 2), (0.40, 1))
IN_MIN_N = 3
KADO_LEVELS = ((0.02, 3), (0.01, 2), (0.0, 1))
KADO_MK_MIN, KADO_MK_PRIOR, KADO_MK_K = 0.08, 0.046, 3
NAME = {"in": "イン飛び", "kado": "カドまくり"}
LEVEL = {3: "特別警報", 2: "警報", 1: "注意報"}


def in_alert(cs1: dict | None, cs2: dict | None) -> int:
    if not cs1 or not cs2 or cs1.get("n", 0) < IN_MIN_N or cs2.get("n", 0) < IN_MIN_N:
        return 0
    m = max(cs1.get("w1", 0) / cs1["n"], cs2.get("ng", 0) / cs2["n"])
    for t, lv in IN_LEVELS:
        if m <= t + 1e-9:
            return lv
    return 0


def makuri_tendency(cs4: dict | None) -> float:
    cs4 = cs4 or {}
    km = cs4.get("km") or {}
    return (km.get("捲り", 0) + 0.5 * km.get("捲り差し", 0) + KADO_MK_K * KADO_MK_PRIOR) / (cs4.get("n", 0) + KADO_MK_K)


def start_means(sm: dict, boats: list, venue: str, date: str, wind: float | None = None) -> list:
    """6艇(1〜6コースの順)の予想ST。boats: [{stx, r8, f}]。model.js の startParts と同じ式。"""
    co, K, RK = sm["coef"], sm["K"], sm.get("REC_K", 4)
    y, m = int(date[:4]), int(date[5:7])
    ps = f"{y}-11-01" if m >= 11 else (f"{y}-05-01" if m >= 5 else f"{y - 1}-11-01")

    def mr_of(stx):
        return (stx[1] + K * sm["m_pop"]) / (stx[0] + K)

    out = []
    for i, b in enumerate(boats):
        stx = b.get("stx") or [0, 0, 0]
        mr = mr_of(stx)
        r8 = b.get("r8") or []
        rec = (sum(r8) + RK * mr) / (len(r8) + RK) - mr if r8 else 0.0
        nbs = [mr_of(boats[j].get("stx") or [0, 0, 0]) for j in (i - 1, i + 1) if 0 <= j < len(boats)]
        nb = sum(nbs) / len(nbs) - sm["m_pop"] if nbs else 0.0
        fp = sum(1 for x in b.get("f") or [] if ps <= x < date)
        c = i + 1
        cs = (b.get("cs") or {}).get(str(c)) or {}
        st_c, sn, KC = cs.get("st"), cs.get("sn") or 0, sm.get("CST_K", 10)
        cdev = (st_c * sn + KC * mr) / (sn + KC) - mr if st_c is not None and sn > 0 else 0.0     # このコースでのSTのくせ
        mu = (co["a"] + co["b"] * mr + (co.get(f"c{c}", 0) if c >= 2 else 0) + (co["f"] if fp > 0 else 0)
              + (co.get("f2", 0) if fp >= 2 else 0) + co["wind"] * max(0, (wind or 0) - 3)
              + co.get("rec", 0) * rec + co.get("nb", 0) * nb + co.get("cdev", 0) * cdev + (sm.get("ven") or {}).get(venue, 0))
        out.append(mu)
    return out


def kado_alert(sm: dict | None, boats: list, venue: str, date: str) -> int:
    """boats: 1〜6コースの順の [{stx, r8, f, cs}]。"""
    if not sm or len(boats) != 6:
        return 0
    if makuri_tendency((boats[3].get("cs") or {}).get("4")) < KADO_MK_MIN:
        return 0
    mus = start_means(sm, boats, venue, date)
    dk = min(mus[:3]) - mus[3]
    for t, lv in KADO_LEVELS:
        if dk >= t - 1e-9:
            return lv
    return 0


def race_alerts(ents: list, sm: dict | None, venue: str, date: str) -> dict:
    """枠なりの進入として、そのレースのアラート {"in": 0〜3, "kado": 0〜3}。ents は racer_view の形(枠番の順)。"""
    by = {x["waku"]: x for x in ents}
    if sorted(by) != [1, 2, 3, 4, 5, 6]:
        return {"in": 0, "kado": 0}
    boats = [by[c] for c in range(1, 7)]
    return {"in": in_alert(by[1]["cs"].get("1"), by[2]["cs"].get("2")),
            "kado": kado_alert(sm, boats, venue, date)}


def badges(al: dict, small: bool = False) -> str:
    out = []
    for k in ("in", "kado"):
        lv = (al or {}).get(k) or 0
        if lv:
            out.append(f'<span class="al al-{k}{lv}{" sm" if small else ""}">{NAME[k]} {LEVEL[lv]}</span>')
    return "".join(out)
