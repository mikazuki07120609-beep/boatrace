#!/usr/bin/env python3
"""前の日の見立て(スタート展示のあとに出したもの)と結果を比べて、何が違ったかを記録する(学習の記録。サイトには出さない)。
  data/learn/YYYYMMDD.json  … 決着パターン・2着3着・スタートの当たり外れと、よくある外れ方
1周1マークの映像が実際の進入・ST・決まり手・着順をどこまで再現できたかは、scripts/learn_anim.js が同じファイルに足す。
見立ての式そのものは scripts/fit.py が毎晩、前の日の結果も入れて学習し直す。
  python3 scripts/learn.py [YYYYMMDD]
"""
import collections
import datetime as dt
import math
import sys

from common import DATA, RESULTS, load_json, parse_ymd, save_json, today_jst
from stats import races_of

CLASSES = [(1, "逃げ"), (1, "抜き")] + [(c, k) for c in range(2, 7) for k in ("捲り", "差し", "捲り差し", "抜き")]
CI = {ck: i for i, ck in enumerate(CLASSES)}
LEARN = DATA / "learn"


def compare(day: dt.date) -> dict | None:
    ymd = f"{day:%Y%m%d}"
    pred = load_json(DATA / "live" / ymd / "pred.json", None)
    res = load_json(RESULTS / f"{ymd}.json", None)
    if not pred or not res:
        return None
    n = top1 = top3 = 0
    py = 0.0
    nll = 0.0
    o_n = o2 = o3 = o23 = 0
    st_err, st_n, st_bias = 0.0, 0, 0.0
    pair = collections.Counter()
    by_kind = collections.defaultdict(lambda: [0, 0])     # 実際の決まり手ごとの [レース, 本命が当たった]
    races = []
    for code, v in res.get("venues", {}).items():
        for race in races_of(v):
            lg = (pred.get(code) or {}).get(str(race["no"]))
            if not lg:
                continue
            ents = [e for e in race["entries"] if e.get("course")]
            win = next((e for e in ents if e.get("rank") == 1), None)
            k = race.get("kimarite")
            k = "抜き" if k in ("抜き", "恵まれ") else k
            y = CI.get((win["course"], k)) if win else None
            if y is None:
                continue
            p = lg["p"]
            order = sorted(range(len(p)), key=lambda i: -p[i])
            n += 1
            top1 += int(order[0] == y)
            top3 += int(y in order[:3])
            py += p[y]
            nll -= math.log(max(1e-6, p[y]))
            pair[(order[0], y)] += 1
            by_kind[k][0] += 1
            by_kind[k][1] += int(order[0] == y)
            # 2着・3着(実際の決着パターンのときに予想していた並びと比べる)
            act = [e["course"] for e in sorted([e for e in ents if e.get("rank")], key=lambda e: e["rank"])]
            po = (lg.get("ord") or {}).get(str(y))
            if po and len(act) >= 3:
                o_n += 1
                o2 += int(po[1] == act[1])
                o3 += int(po[2] == act[2])
                o23 += int(po[1] == act[1] and po[2] == act[2])
            # スタート(枠番の順に記録している)
            for e in ents:
                st = e.get("st")
                if isinstance(st, (int, float)) and 0 <= st < 1 and not e.get("flying") and 1 <= e["waku"] <= 6:
                    d = lg["st"][e["waku"] - 1][0] - st
                    st_err += d * d
                    st_bias += d
                    st_n += 1
            races.append({"v": code, "no": race["no"], "pred": "%d%s" % CLASSES[order[0]], "act": "%d%s" % CLASSES[y],
                          "p_act": round(p[y] * 100, 1), "ord": po, "act_ord": act})
    if not n:
        return None
    miss = [{"pred": "%d%s" % CLASSES[a], "act": "%d%s" % CLASSES[b], "n": c} for (a, b), c in pair.most_common(12) if a != b]
    return {"date": day.isoformat(), "races": n, "top1": round(top1 / n * 100, 1), "top3": round(top3 / n * 100, 1),
            "p_actual": round(py / n * 100, 1), "nll": round(nll / n, 4),
            "order": {"races": o_n, "hit2": round(o2 / o_n * 100, 1) if o_n else None, "hit3": round(o3 / o_n * 100, 1) if o_n else None,
                      "hit23": round(o23 / o_n * 100, 1) if o_n else None},
            "st": {"rmse": round(math.sqrt(st_err / st_n), 4) if st_n else None, "bias": round(st_bias / st_n, 4) if st_n else None, "n": st_n},
            "by_kimarite": {k: {"races": a, "top1": round(b / a * 100, 1)} for k, (a, b) in by_kind.items()},
            "common_misses": miss, "detail": races}


def main() -> int:
    day = parse_ymd(sys.argv[1]) if len(sys.argv) > 1 else today_jst() - dt.timedelta(days=1)
    r = compare(day)
    if not r:
        print("比べられる見立てと結果がありません:", day)
        return 0
    path = LEARN / f"{day:%Y%m%d}.json"
    old = load_json(path, {}) or {}
    if old.get("anim"):
        r["anim"] = old["anim"]
    save_json(path, r)
    print(f"{day}: {r['races']}レース 本命{r['top1']}% 上位3つ{r['top3']}% 2着{r['order']['hit2']}% ST誤差{r['st']['rmse']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
