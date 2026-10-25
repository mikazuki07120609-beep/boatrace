"""競走成績のJSONから、選手のコース別成績・スタートの傾向と、レース場のコース別成績を集計する。

選手: 直近 RACER_DAYS 日、レース場: 直近 VENUE_DAYS 日(どちらも対象日の前日まで)。
古い成績は集計に使う項目だけに縮めた形式(compact)で保存されているので、両方を読めるようにする。

集計は日ごとに足し引きできる形(回数と合計)にしてあり、Acc に1日分ずつ足したり引いたりできる。
サイトを作るとき(collect)と、過去の各日の時点の集計で見立てを作り直して結果と比べるとき(fit.py)で、同じ集計を使う。
"""
import datetime as dt

from common import DATA, RESULTS, KIMARITE, load_json, parse_ymd

RACER_DAYS = 365
VENUE_DAYS = 365      # 1年分そろってから、場の傾向も1年で見る方が当たる(直近30日の答え合わせで確かめた)
POINTS = {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1}   # 勝率の計算と同じ着順点
RECENT_N = 8          # スタートの見立てで「最近の調子」に使う直近の走数
RECENT_KEEP = 12


def _result_files(start: dt.date, until: dt.date):
    for p in sorted(RESULTS.glob("*.json")):
        d = parse_ymd(p.stem)
        if start <= d < until:
            yield d, p


def races_of(v: dict):
    """場ごとのレースを、縮めた形式でも元の形式でも同じ形で返す。"""
    for race in v.get("races", []):
        if "e" in race:
            ents = []
            for a in race["e"]:
                ents.append({"rank": a[0] if isinstance(a[0], int) else None, "status": None if isinstance(a[0], int) else a[0],
                             "waku": a[1], "toban": a[2], "name": a[3], "course": a[4], "st": a[5], "flying": bool(a[6]),
                             "ex": a[7] if len(a) > 7 else None, "motor": a[8] if len(a) > 8 else None,
                             "time": a[9] if len(a) > 9 else None})
            w = race.get("w") or [None, None, None, None]
            yield {"no": race["no"], "kimarite": race.get("k"), "name": race.get("nm"), "entries": ents,
                   "weather": w[0], "wind_dir": w[1], "wind": w[2], "wave": w[3]}
        else:
            yield race


def race_time(t):
    """レースタイム "1.48.7" を秒に。読めなければ None。"""
    if not isinstance(t, str):
        return None
    try:
        m, sec = t.split(".", 1)
        return int(m) * 60 + float(sec)
    except ValueError:
        return None


CLOSE_SEC = 0.6       # ゴールでこの差以内なら、道中で競り合っていたとみなす


def second_kind(c: int, ctx: dict, kim) -> str:
    """2着になったレースで、その艇がどう動いて2着になったか(推定)。
    公式の記録は1着の決まり手だけなので、1着の艇のコース・決まり手と、自分と間の艇のスタートから推定する。
      1コース: 差され・捲られ・捲り差され・抜かれ(どう負けて2着になったか)
      2〜6コース: 差し(勝った艇の内の筋を回った)、捲り(スタートで内より先に出て外から攻めた)、
                  捲り差し(間の艇の前を横切って内へ切り込んだ)、残し(外の艇に先に回られたが残した)、道中(道中の抜き合いで決まった)"""
    w = ctx.get("w")
    if not w:
        return "その他"
    if c == 1:
        return {"差し": "差され", "捲り": "捲られ", "捲り差し": "捲り差され", "抜き": "抜かれ"}.get(kim, "その他")
    if kim in ("抜き", "恵まれ"):
        return "道中"
    if w > c:
        return "残し"
    st = ctx.get("st", {})
    mine, inner = st.get(c), [st[k] for k in st if k < c]
    if mine is not None and inner and mine <= min(inner) - 0.03:
        return "捲り"
    if c == w + 1:
        return "差し"
    between = [st[k] for k in st if w < k < c]
    if mine is not None and between and min(between) <= mine - 0.02:
        return "差し"                                            # 間の艇が先に出て外へ攻め、空いた内を回った
    return "捲り差し"


def valid_st(e) -> bool:
    """普通にスタートした艇か(フライング・出遅れ・欠場を除く。レース中の失格はスタートは普通なので含める)。"""
    st = e.get("st")
    return (isinstance(st, (int, float)) and 0 <= st < 1 and not e.get("flying")
            and e.get("status") in (None, "S0", "S1", "S2"))


CATS = ("女子戦", "SG", "G1", "G2", "G3", "一般")   # レースの区分(開催のグレードと女子戦)


def category_resolver():
    """レースの区分を返す関数 f(日付, 場コード, 出走表の艇) -> 区分 or None を作る。
    開催のグレード(data/grades.json)と女子レーサー(data/fem.json)から。オールレディース・ヴィーナスシリーズと、
    6艇とも女子レーサーのレースは「女子戦」。グレードが分からない日は None(集計に入れない)。"""
    G = load_json(DATA / "grades.json", {}) or {}
    fem = set((load_json(DATA / "fem.json", {}) or {}).get("fem", []))

    def cat(d: dt.date, vcode: str, ents: list):
        g = (G.get(f"{d:%Y%m%d}") or {}).get(vcode)
        if not g:
            return None
        if "lady" in g or "venus" in g or (fem and len(ents) >= 6 and all(e.get("toban") in fem for e in ents)):
            return "女子戦"
        return g[0]
    cat.fem = fem
    cat.grades = G
    return cat


class Acc:
    """選手・場・全国の集計。add(日付, その日の成績, +1/-1) で1日分を足し引きする。
    cat_of(レースの区分を返す関数)を渡すと、区分ごとの全国のコース成績と、選手の区分ごとのコース成績も数える。"""

    def __init__(self, cat_of=None):
        self.racers: dict = {}
        self.venues: dict = {}
        self.nat = {"races": 0, "c": {}}          # 全国(選手の集計と同じ期間)
        self.cat_of = cat_of
        self.cats: dict = {}                       # 区分ごとの全国(女子戦・SG・G1・G2・G3・一般)

    def add(self, d: dt.date, day: dict, sign: int = 1, racers: bool = True, venues: bool = True):
        for vcode, v in day.get("venues", {}).items():
            for race in races_of(v):
                ents = [e for e in race.get("entries", []) if e.get("course")]
                if len(ents) < 5:
                    continue  # 進入が分からないレースは使わない
                kim = race.get("kimarite")
                sts = [e["st"] for e in ents if valid_st(e)]
                rmean = sum(sts) / len(sts) if len(sts) >= 4 else None
                if venues:
                    vs = self.venues.setdefault(vcode, {"races": 0, "c": {}})
                    vs["races"] += sign
                    _course_table(vs, ents, kim, sign)
                if racers:
                    self.nat["races"] += sign
                    _course_table(self.nat, ents, kim, sign)
                    win = next((e for e in ents if e.get("rank") == 1), None)
                    ctx = {"w": win["course"] if win else None,
                           "st": {e["course"]: e["st"] for e in ents if valid_st(e)},
                           "fin": [(e, race_time(e.get("time"))) for e in ents if e.get("rank") and race_time(e.get("time"))]}
                    for e in ents:
                        _racer(self.racers, e, kim, rmean, d, sign, ctx, vcode)
                    cat = self.cat_of(d, vcode, race.get("entries", [])) if self.cat_of else None
                    if cat:
                        cs = self.cats.setdefault(cat, {"races": 0, "c": {}})
                        cs["races"] += sign
                        _course_table(cs, ents, kim, sign)
                        for e in ents:                    # 選手の区分ごとのコース成績(走数・着順・ST・勝ち方・2着の時・逃がし。コース成績と同じ形)
                            gc = self.racers[e["toban"]].setdefault("g", {}).setdefault(cat, {})
                            _cs_add(gc.setdefault(str(e["course"]), _cs_new()), e, kim, sign, ctx)

    def racer(self, toban: str) -> dict:
        return self.racers.get(toban, {})


def _course_table(vs: dict, ents, kim, sign):
    for e in ents:
        c = str(e["course"])
        rank = e.get("rank")
        vc = vs["c"].setdefault(c, {"n": 0, "w1": 0, "w2": 0, "w3": 0, "km": {}})
        vc["n"] += sign
        if rank in (1, 2, 3):
            vc[f"w{rank}"] += sign
        if rank == 1 and kim in KIMARITE:
            vc["km"][kim] = vc["km"].get(kim, 0) + sign


def _cs_new() -> dict:
    return {"n": 0, "w1": 0, "w2": 0, "w3": 0, "st_sum": 0.0, "st_n": 0, "km": {}}


def _cs_add(cs: dict, e: dict, kim, sign: int, ctx: dict) -> None:
    """コースごとの成績(走数・1〜3着・勝ったときの決まり手・1コースで負けたときの決まり手・2着の時・逃がし・ST)に1走分を足し引きする。"""
    c, rank = str(e["course"]), e.get("rank")
    if c == "2" and ctx.get("w") == 1 and kim == "逃げ":                  # 2コースのときに1コースを逃がした回数
        cs["ng"] = cs.get("ng", 0) + sign
    if rank == 2 and ctx.get("w"):                                        # 2着になったときの展開
        s2 = cs.setdefault("s2", {})
        k2 = second_kind(e["course"], ctx, kim)
        s2[k2] = s2.get(k2, 0) + sign
    cs["n"] += sign
    if rank in (1, 2, 3):
        cs[f"w{rank}"] += sign
    if rank == 1 and kim in KIMARITE:
        cs["km"][kim] = cs["km"].get(kim, 0) + sign                       # このコースで勝ったときの決まり手
    elif c == "1" and kim in KIMARITE:
        ls = cs.setdefault("ls", {})                                      # 1コースで負けたときの決まり手(差され・捲られなど)
        ls[kim] = ls.get(kim, 0) + sign
    if valid_st(e):
        cs["st_sum"] += sign * e["st"]
        cs["st_n"] += sign


def _racer(racers: dict, e: dict, kim, rmean, d: dt.date, sign: int, ctx: dict | None = None, vcode: str | None = None):
    c = str(e["course"])
    rank = e.get("rank")
    r = racers.setdefault(e["toban"], {"name": e.get("name", ""), "c": {}, "pts": [0, 0], "stx": [0, 0.0, 0.0],
                                       "rst": [0, 0.0, 0.0], "f": [], "rs": [], "cb": [0, 0], "nk": [0, 0]})
    ctx = ctx or {}
    _cs_add(r["c"].setdefault(c, _cs_new()), e, kim, sign, ctx)
    # 道中: ゴールで僅差だった相手との勝ち負け(競り合い)、抜きで勝った・抜かれて2着
    t_me = race_time(e.get("time")) if rank else None
    if t_me is not None:
        for o, t_o in ctx.get("fin", []):
            if o is e or abs(t_o - t_me) > CLOSE_SEC + 1e-9:
                continue
            r.setdefault("cb", [0, 0])
            r["cb"][0] += sign * (1 if rank < o["rank"] else 0)
            r["cb"][1] += sign
    if kim == "抜き" and rank in (1, 2):
        r.setdefault("nk", [0, 0])[rank - 1] += sign
    if e.get("name"):
        r["name"] = e["name"]
    # 着順点(勝率と同じ数え方。失格・フライングなどは0点で1走)
    if rank in POINTS or e.get("status") in ("F", "L0", "L1", "S0", "S1", "S2", "K1"):
        r["pts"][0] += sign * POINTS.get(rank, 0)
        r["pts"][1] += sign
        if vcode:                                                # 場ごとの着順点(当地の相性)
            lv = r.setdefault("v", {}).setdefault(vcode, [0, 0])
            lv[0] += sign * POINTS.get(rank, 0)
            lv[1] += sign
    if valid_st(e):
        st = e["st"]
        r["stx"][0] += sign; r["stx"][1] += sign * st; r["stx"][2] += sign * st * st
        if sign > 0:                                             # 直近のST(今節の調子を見る。古い日を引くときは触らない)
            rs = r.setdefault("rs", [])
            rs.append(st)
            if len(rs) > RECENT_KEEP:
                del rs[:-RECENT_KEEP]
        if rmean is not None:
            x = st - rmean                                       # そのレースの平均より早いか遅いか
            r["rst"][0] += sign; r["rst"][1] += sign * x; r["rst"][2] += sign * x * x
    if e.get("flying"):
        iso = d.isoformat()
        if sign > 0:
            r["f"].append(iso)
        elif iso in r["f"]:
            r["f"].remove(iso)


def finish(racers: dict) -> dict:
    """平均STなどの読みやすい値を足した、表示用の選手集計を返す(元の集計は変えない)。"""
    out = {}
    for t, r in racers.items():
        if not any(cs["n"] for cs in r["c"].values()):
            continue
        cc = _cs_out(r["c"])
        out[t] = {"name": r["name"], "c": cc, "pts": list(r["pts"]), "stx": [r["stx"][0], round(r["stx"][1], 4), round(r["stx"][2], 5)],
                  "rst": [r["rst"][0], round(r["rst"][1], 4), round(r["rst"][2], 5)], "f": sorted(r["f"]),
                  "r8": [round(x, 2) for x in r.get("rs", [])[-RECENT_N:]],
                  "cb": list(r.get("cb", [0, 0])), "nk": list(r.get("nk", [0, 0])),
                  "v": {k: list(a) for k, a in r.get("v", {}).items() if a[1] > 0},
                  "g": {k: g for k, g in ((k, _cs_out(v)) for k, v in r.get("g", {}).items()) if g}}
    return out


def _cs_out(cmap: dict) -> dict:
    """コースごとの成績を、表示用の形(率は出さず回数のまま。平均STだけ計算)にする。"""
    cc = {}
    for c, cs in cmap.items():
        if cs["n"] <= 0:
            continue
        x = {k: cs[k] for k in ("n", "w1", "w2", "w3")}
        x["km"] = {k: v for k, v in cs["km"].items() if v > 0}
        if cs.get("ls"):
            x["ls"] = {k: v for k, v in cs["ls"].items() if v > 0}
        if cs.get("s2"):
            x["s2"] = {k: v for k, v in cs["s2"].items() if v > 0}
        if cs.get("ng"):
            x["ng"] = cs["ng"]
        x["st"] = round(cs["st_sum"] / cs["st_n"], 2) if cs["st_n"] > 0 else None
        cc[c] = x
    return cc


def collect(until: dt.date, cache: dict | None = None, cats=None, out_cats: dict | None = None):
    """until(その日を含まない)までの成績から、選手別・場別の集計を返す。戻り値: (選手, 場, 全国)
    cats(category_resolver の関数)を渡すと、区分ごとの全国の集計を out_cats に入れる。"""
    acc = Acc(cats)
    rstart = until - dt.timedelta(days=RACER_DAYS)
    vstart = until - dt.timedelta(days=VENUE_DAYS)
    for d, p in _result_files(rstart, until):
        day = cache.get(p.stem) if cache is not None else None
        if day is None:
            day = load_json(p, {})
            if cache is not None:
                cache[p.stem] = day
        acc.add(d, day, 1, racers=True, venues=d >= vstart)
    if out_cats is not None:
        out_cats.clear()
        out_cats.update(acc.cats)
    return finish(acc.racers), acc.venues, acc.nat


def venue_table(vs: dict | None, min_races: int = 150):
    """場の集計を [1着,2着,3着]・決まり手(%) の表にする。データが少なければ None。"""
    if not vs or vs.get("races", 0) < min_races:
        return None
    place, kim = [], []
    for c in range(1, 7):
        vc = vs["c"].get(str(c), {"n": 0, "w1": 0, "w2": 0, "w3": 0, "km": {}})
        n = vc["n"] or 1
        place.append([round(vc["w1"] / n * 100, 1), round(vc["w2"] / n * 100, 1), round(vc["w3"] / n * 100, 1)])
        wins = sum(vc["km"].values()) or 1
        kim.append([round(vc["km"].get(k, 0) / wins * 100, 1) for k in KIMARITE])
    return {"place": place, "kimarite": kim, "races": vs["races"]}
