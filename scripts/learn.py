#!/usr/bin/env python3
"""前の日の見立て(スタート展示のあとに出したもの)と結果を比べて、何が違ったかを記録する(学習の記録。サイトには出さない)。
  data/learn/YYYYMMDD.json  … 決着パターン・2着3着・スタートの当たり外れと、よくある外れ方
1周1マークの映像が実際の進入・ST・決まり手・着順をどこまで再現できたかは、scripts/learn_anim.js が同じファイルに足す。
見立ての式そのものは scripts/fit.py が毎晩、前の日の結果も入れて学習し直す。
  python3 scripts/learn.py [YYYYMMDD]
"""
import collections
import datetime as dt
import json
import math
import statistics
import subprocess
import sys

from common import DATA, RESULTS, ROOT, load_json, parse_ymd, save_json, today_jst
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
    lead = [0, 0, 0, 0, 0, 0]                              # 本線(1着の見込みが一番高い艇)の [レース, 艇が1着, 決着パターンも同じ, 1号艇以外が本線, そのとき本線の艇が1着, そのとき1コースが1着]
    lx = [0, 0, 0, 0]                                      # [1コースが1着(毎回1号艇と言った場合), 本線の並びで1-2着そのまま, 1-2-3着そのまま, 上位3艇(順不同)]
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
            pc = [0.0] * 6
            for i, (c, _) in enumerate(CLASSES):
                pc[c - 1] += p[i]
            lc = max(range(6), key=lambda c: pc[c]) + 1
            li = max((i for i, (c, k) in enumerate(CLASSES) if c == lc), key=lambda i: (CLASSES[i][1] != "抜き", p[i]))
            lead[0] += 1
            lead[1] += int(lc == win["course"])
            lead[2] += int(li == y)
            if lc != 1:
                lead[3] += 1
                lead[4] += int(lc == win["course"])
                lead[5] += int(win["course"] == 1)
            by_kind[k][0] += 1
            by_kind[k][1] += int(order[0] == y)
            # 2着・3着(実際の決着パターンのときに予想していた並びと比べる)
            act = [e["course"] for e in sorted([e for e in ents if e.get("rank")], key=lambda e: e["rank"])]
            lx[0] += int(win["course"] == 1)
            lo = (lg.get("ord") or {}).get(str(li))              # 本線の決着パターンのときの並び
            if lo and len(act) >= 3:
                lx[1] += int(lo[:2] == act[:2])
                lx[2] += int(lo[:3] == act[:3])
                lx[3] += int(sorted(lo[:3]) == sorted(act[:3]))
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
            "lead": {"races": lead[0], "boat": round(lead[1] / lead[0] * 100, 1), "pattern": round(lead[2] / lead[0] * 100, 1),
                     "one": round(lx[0] / lead[0] * 100, 1), "ex2": round(lx[1] / lead[0] * 100, 1), "ex3": round(lx[2] / lead[0] * 100, 1),
                     "in3": round(lx[3] / lead[0] * 100, 1), "non1_n": lead[3],
                     "non1": lead[3], "non1_boat": round(lead[4] / lead[3] * 100, 1) if lead[3] else None,
                     "non1_one": round(lead[5] / lead[3] * 100, 1) if lead[3] else None},
            "common_misses": miss, "detail": races}


def final_odds(ymd: str) -> dict:
    """締切時オッズ(odds ブランチの data/odds_final)。読めなければ空。"""
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "+refs/heads/odds:refs/remotes/origin/odds"], cwd=ROOT, capture_output=True, timeout=120)
        r = subprocess.run(["git", "show", f"refs/remotes/origin/odds:data/odds_final/{ymd}.json"], cwd=ROOT, capture_output=True, timeout=60)
        return json.loads(r.stdout.decode("utf-8")) if r.returncode == 0 and r.stdout else {}
    except Exception:  # noqa: BLE001
        return {}


def ura_compare(day: dt.date) -> dict | None:
    """裏の見立て(締切前に記録した pred.json の u)の答え合わせ。払戻金(data/pays)と締切時オッズ(odds ブランチ)で数える。
       races: レース / man: 万舟率 / top_man: 万舟の見込みが高い2割の万舟率 / hit: 裏本線の艇が1着 / pay: そのときの3連単(平均) /
       tan: 裏本線の艇の単勝の回収率(参考) / val_n, val_tan: 人気より見立てが上の艇(締切時の単勝オッズで)の数と単勝の回収率(参考)"""
    ymd = f"{day:%Y%m%d}"
    pred = load_json(DATA / "live" / ymd / "pred.json", None)
    res = load_json(RESULTS / f"{ymd}.json", None)
    pays = (load_json(DATA / "pays" / f"{ymd}.json", None) or {}).get("venues") or {}
    if not pred or not res or not pays:
        return None
    finals = final_odds(ymd)
    rows = []
    val_n = val_ret = 0
    val_have = False
    for code, v in res.get("venues", {}).items():
        for race in races_of(v):
            u = ((pred.get(code) or {}).get(str(race["no"])) or {}).get("u")
            pv = (pays.get(code) or {}).get(str(race["no"]))
            if not u or not pv or not pv.get("3t"):
                continue
            win = next((e for e in race["entries"] if e.get("rank") == 1), None)
            if not win:
                continue
            t3 = max(x[1] for x in pv["3t"])
            tan = {int(x[0]): x[1] for x in pv.get("tan") or []}
            uw = (u.get("ul") or [None, None])[1]
            rows.append({"pm": u["pm"], "man": t3 >= 10000, "t3": t3, "hit": uw == win["waku"], "uw": uw, "ow": u.get("ow"),
                         "tan_u": tan.get(uw, 0) if uw else 0, "tan_o": tan.get(u.get("ow"), 0) if u.get("ow") else 0,
                         "ohit": u.get("ow") == win["waku"]})
            # 人気より見立てが上の艇(表の本線の艇を除く。見立ての1着の見込み5%以上・人気からの見込みの1.3倍以上)
            fo = ((finals.get(code) or {}).get(str(race["no"])) or {}).get("tan")
            pw = u.get("pw")
            if fo and pw and sum(1 for x in fo if x and x > 0) >= 5:
                val_have = True
                inv = [1 / x if x and x > 0 else 0 for x in fo]
                sm = sum(inv)
                for w in range(1, 7):
                    pmk = inv[w - 1] / sm
                    if w != u.get("ow") and pw[w - 1] >= 0.05 and pmk > 0 and pw[w - 1] / pmk >= 1.3:
                        val_n += 1
                        val_ret += tan.get(w, 0)
    n = len(rows)
    if n < 10:
        return None
    rs = sorted(rows, key=lambda r: -r["pm"])
    top = rs[:max(1, round(n * 0.2))]
    hits = [r for r in rows if r["hit"]]
    nu = sum(1 for r in rows if r["uw"])
    no = sum(1 for r in rows if r["ow"])
    pays_hit = [r["t3"] for r in hits]
    pos = [r["pm"] for r in rows if r["man"]]
    neg = [r["pm"] for r in rows if not r["man"]]
    auc = None
    if pos and neg:
        allv = sorted([(x, 1) for x in pos] + [(x, 0) for x in neg])
        i = 0
        ranks = [0.0] * len(allv)
        while i < len(allv):                               # 同じ値は平均の順位
            j = i
            while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
                j += 1
            for k in range(i, j + 1):
                ranks[k] = (i + j) / 2 + 1
            i = j + 1
        rp = sum(r for r, (_, y) in zip(ranks, allv) if y)
        auc = round((rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)), 3)
    return {"races": n, "man": round(sum(r["man"] for r in rows) / n * 100, 1), "top_man": round(sum(r["man"] for r in top) / len(top) * 100, 1),
            "pm": round(sum(r["pm"] for r in rows) / n * 100, 1), "auc": auc,
            "hit": round(len(hits) / nu * 100, 1) if nu else None, "hit_man": round(sum(r["man"] for r in hits) / len(hits) * 100, 1) if hits else None,
            "pay": round(sum(pays_hit) / len(pays_hit)) if pays_hit else None, "pay_med": round(statistics.median(pays_hit)) if pays_hit else None,
            "tan": round(sum(r["tan_u"] for r in rows) / (100 * nu) * 100, 1) if nu else None,
            "omote_hit": round(sum(r["ohit"] for r in rows) / no * 100, 1) if no else None,
            "omote_tan": round(sum(r["tan_o"] for r in rows) / (100 * no) * 100, 1) if no else None,
            "val_n": val_n if val_have else None, "val_tan": round(val_ret / (100 * val_n) * 100, 1) if val_n else None}


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
    try:
        u = ura_compare(day)
    except Exception as ex:  # noqa: BLE001
        print("裏の答え合わせができませんでした:", ex)
        u = None
    if u or old.get("ura"):
        r["ura"] = u or old["ura"]
    save_json(path, r)
    if u:
        print(f"{day}: 裏 {u['races']}レース 万舟{u['man']}%(見込み上位2割 {u['top_man']}%) 裏本線の艇{u['hit']}% そのときの3連単 平均{u['pay']}円"
              f" 単勝回収{u['tan']}% 人気より上の艇 {u['val_n']}頭・単勝回収{u['val_tan']}%")
    L = r["lead"]
    print(f"{day}: {r['races']}レース 本命{r['top1']}% 上位3つ{r['top3']}% 2着{r['order']['hit2']}% ST誤差{r['st']['rmse']}"
          f" 本線の艇{L['boat']}% 1号艇以外の本線{L['non1']}レース(その艇{L['non1_boat']}%・1コース{L['non1_one']}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
