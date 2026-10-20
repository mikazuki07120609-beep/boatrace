"""競走成績のJSONから、選手のコース別成績とレース場のコース別成績を集計する。

選手: 直近 RACER_DAYS 日、レース場: 直近 VENUE_DAYS 日(どちらも対象日の前日まで)。
"""
import datetime as dt

from common import RESULTS, KIMARITE, load_json, parse_ymd

RACER_DAYS = 180
VENUE_DAYS = 90


def _result_files(until: dt.date, days: int):
    start = until - dt.timedelta(days=days)
    for p in sorted(RESULTS.glob("*.json")):
        d = parse_ymd(p.stem)
        if start <= d < until:
            yield d, p


def collect(until: dt.date, cache: dict | None = None):
    """until(その日を含まない)までの成績から、選手別・場別の集計を返す。"""
    racers: dict = {}
    venues: dict = {}
    vstart = until - dt.timedelta(days=VENUE_DAYS)
    for d, p in _result_files(until, RACER_DAYS):
        day = cache.get(p.stem) if cache is not None else None
        if day is None:
            day = load_json(p, {})
            if cache is not None:
                cache[p.stem] = day
        for vcode, v in day.get("venues", {}).items():
            use_venue = d >= vstart
            vs = venues.setdefault(vcode, {"races": 0, "c": {}}) if use_venue else None
            for race in v.get("races", []):
                ents = [e for e in race.get("entries", []) if e.get("course")]
                if len(ents) < 5:
                    continue  # 進入が分からないレースは使わない
                if vs is not None:
                    vs["races"] += 1
                for e in ents:
                    c = str(e["course"])
                    rank = e.get("rank")
                    # 選手
                    r = racers.setdefault(e["toban"], {"name": e.get("name", ""), "c": {}})
                    cs = r["c"].setdefault(c, {"n": 0, "w1": 0, "w2": 0, "w3": 0, "st_sum": 0.0, "st_n": 0, "km": {}})
                    cs["n"] += 1
                    if rank in (1, 2, 3):
                        cs[f"w{rank}"] += 1
                    if rank == 1 and race.get("kimarite") in KIMARITE:
                        cs["km"][race["kimarite"]] = cs["km"].get(race["kimarite"], 0) + 1
                    st = e.get("st")
                    if isinstance(st, (int, float)) and 0 <= st < 1 and not e.get("flying"):
                        cs["st_sum"] += st
                        cs["st_n"] += 1
                    # レース場
                    if vs is not None:
                        vc = vs["c"].setdefault(c, {"n": 0, "w1": 0, "w2": 0, "w3": 0, "km": {}})
                        vc["n"] += 1
                        if rank in (1, 2, 3):
                            vc[f"w{rank}"] += 1
                        if rank == 1 and race.get("kimarite") in KIMARITE:
                            vc["km"][race["kimarite"]] = vc["km"].get(race["kimarite"], 0) + 1
    for r in racers.values():
        for cs in r["c"].values():
            cs["st"] = round(cs["st_sum"] / cs["st_n"], 2) if cs["st_n"] else None
            del cs["st_sum"], cs["st_n"]
    return racers, venues


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
