#!/usr/bin/env python3
"""その日のレースの直前情報と結果を、締切の前後に公式サイトから読み取る(GitHub Actions で開催中ずっと動かす)。

公式の配布ファイル(番組表・競走成績)には、直前情報(展示タイム・スタート展示など)と、
レース直後の結果(払戻金)がないので、BOAT RACE オフィシャルウェブサイトの各レースのページを読む。
サーバーに負担をかけないよう、
  - 直前情報: 締切の20分前から締切の3分後までのレースだけ、出るまで2分おきに読む(1レース多くても十数回)
  - 結果: 締切の3分後から、出るまで2分おきに読む(1レース1回で取れることが多い)
  - 読むたびに数秒あける
読み取った内容は data/live/YYYYMMDD/{場コード}.json に入れ、すぐにリポジトリへ送る。
レースのページは、このファイルを開くたびに読みに来る(サイトを作り直さなくても、展示と結果が出る)。

  python3 scripts/live.py --loop 350          # 350分まで(その日の最終レースの結果が出たら終わる)
  python3 scripts/live.py --once              # 1回だけ
  python3 scripts/live.py --parse before FILE # 保存したページを読み取って表示(確認用)
"""
import argparse
import datetime as dt
import html as htmlmod
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

from common import DATA, JST, PROGRAM, ROOT, load_json, save_json, zen2han

LIVE = DATA / "live"
URL = "https://www.boatrace.jp/owpc/pc/race/{page}?rno={no}&jcd={jcd}&hd={ymd}"
UA = "suimen-note/1.0 (+https://mikazuki07120609-beep.github.io/boatrace/)"
WAIT_SEC = 2              # 読むたびにあける秒数
CYCLE_SEC = 60            # 一回りの間隔(出たらすぐ取り込めるよう、1分ごと)
BEFORE_FROM = 25          # 締切の何分前から直前情報を読みに行くか(展示はおおむね締切の10〜18分前に出る)
BEFORE_UNTIL = -3         # 締切の何分後まで直前情報を待つか
RESULT_AFTER = 3          # 締切の何分後から結果を読みに行くか
RESULT_GIVEUP = 120       # 締切の何分後まで結果を待つか
MAX_TRIES = {"b": 32, "r": 90, "l": 2, "o": 15}
# 場が自分のサイトで出している、展示航走の計測タイム(オリジナル展示データ: 一周・半周・まわり足・直線)。場ごとに測り方が違うので、6艇の中で比べる
ORIG_URL = {
    "01": "http://www.kiryu-kyotei.com/modules/yosou/cyokuzen.php?day={ymd}&race={no}",
    "06": "https://www.boatrace-hamanako.jp/modules/yosou/group-cyokuzen.php?day={ymd}&race={no}&kind=2",
    "10": "https://www.boatrace-mikuni.jp/modules/yosou/group-cyokuzen.php?day={ymd}&race={no}&kind=2",
    "11": "https://www.boatrace-biwako.jp/modules/yosou/group-cyokuzen.php?day={ymd}&race={no}&kind=2",
    "13": "https://boatrace-amagasaki.jp/modules/yosou/group-cyokuzen.php?day={ymd}&race={no}&kind=2",
    "14": "https://www.n14.jp/modules/yosou/group-cyokuzen.php?day={ymd}&race={no}&kind=2",
    "18": "https://www.boatrace-tokuyama.jp/modules/yosou/tenji.php?day={ymd}&race={no}&kind=2",
    "20": "https://www.wmb.jp/modules/yosou/group-cyokuzen.php?day={ymd}&race={no}&kind=2",
}
LIST_AHEAD = 240          # 締切の何分前から出走表(F・Lの回数)を読みに行くか
LIST_PER_CYCLE = 3        # 出走表は急がないので、1回りに読む数を絞る
KIM = {"逃げ": "逃げ", "まくり": "捲り", "差し": "差し", "まくり差し": "捲り差し", "抜き": "抜き", "恵まれ": "恵まれ"}


# ---------------------------------------------------------------- 読み取り
def _text(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return htmlmod.unescape(s).replace("　", " ").replace("\xa0", " ").strip()


def _num(s: str):
    try:
        return float(_text(s).replace("kg", "").strip())
    except ValueError:
        return None


def _st(s: str):
    """スタートのタイミング(".09"、フライングは "F.03" → -0.03)。読めなければ None。"""
    t = _text(s).replace(" ", "")
    m = re.match(r"(F)?(\d?)\.(\d{2})", t)
    if not m:
        return None
    v = float(f"{m.group(2) or 0}.{m.group(3)}")
    return -v if m.group(1) else v


def parse_before(page: str) -> dict | None:
    """直前情報のページ。展示がまだなら ready=False(展示タイムもスタート展示も空)。"""
    if "is-boatColor1" not in page:
        return None
    out = {"ex": {}, "tilt": {}, "prop": {}, "parts": {}, "weight": {}, "adj": {}, "course": [], "est": {}, "weather": {}}
    for tb in re.findall(r'<tbody class="is-fs12[^"]*">(.*?)</tbody>', page, re.S):
        m = re.search(r"is-boatColor(\d)", tb)
        trs = re.findall(r"<tr>(.*?)</tr>", tb, re.S)
        if not m or not trs:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", trs[0], re.S)
        if len(tds) < 8:
            continue
        w = m.group(1)
        out["weight"][w] = _num(tds[3])
        out["ex"][w] = _num(tds[4])
        out["tilt"][w] = _num(tds[5])
        out["prop"][w] = _text(tds[6])
        out["parts"][w] = [_text(x) for x in re.findall(r'<span class="label4[^"]*">(.*?)</span>', tds[7], re.S)]
        if len(trs) >= 3:
            t3 = re.findall(r"<td[^>]*>(.*?)</td>", trs[2], re.S)
            if t3:
                out["adj"][w] = _num(t3[0])
    # スタート展示(上から1コース、2コース…の順)。フライングは F.01 のように出る
    for blk in re.findall(r'<div class="table1_boatImage1">(.*?)</div>', page, re.S):
        m = re.search(r'table1_boatImage1Number is-type\d">\s*(\d)\s*<', blk)
        if not m:
            continue
        t = re.search(r'table1_boatImage1Time[^"]*">(.*?)</span>', blk, re.S)
        out["course"].append(int(m.group(1)))
        out["est"][m.group(1)] = _st(t.group(1)) if t else None
    # 水面気象
    W = out["weather"]
    m = re.search(r"水面気象情報\s*(?:&nbsp;|\s|　)*(\d+R|\d{1,2}:\d{2})", page)
    W["at"] = m.group(1) if m else None
    for unit, key in (("is-direction", "temp"), ("is-wind", "wind"), ("is-waterTemperature", "water"), ("is-wave", "wave")):
        m = re.search(r'weather1_bodyUnit %s">.*?weather1_bodyUnitLabelData">(.*?)</span>' % unit, page, re.S)
        if m:
            v = re.sub(r"[^\d.\-]", "", _text(m.group(1)))
            W[key] = float(v) if v not in ("", ".", "-") else None
    m = re.search(r'weather1_bodyUnit is-weather">.*?weather1_bodyUnitLabelTitle">(.*?)</span>', page, re.S)
    W["weather"] = _text(m.group(1)) if m else None
    m = re.search(r'is-wind(\d+)"', page)
    W["wind_icon"] = int(m.group(1)) if m else None          # 風向の矢印(場の図に対する向き)
    m = re.search(r'is-direction(\d+)"', page)
    W["dir_icon"] = int(m.group(1)) if m else None
    n_ex = sum(1 for v in out["ex"].values() if v is not None)
    out["ready"] = n_ex >= 4 and len(out["course"]) >= n_ex
    return out


def parse_result(page: str) -> dict | None:
    """結果のページ。まだ出ていなければ None。"""
    rows = re.findall(r'<td class="is-fs14">([^<]*)</td>\s*<td class="is-fs14 is-fBold is-boatColor(\d)">\s*(\d)\s*</td>'
                      r'\s*<td class="is-p10-0">\s*<span class="is-fs12">\s*(\d+)\s*</span>.*?</td>\s*<td>([^<]*)</td>', page, re.S)
    if not rows:
        return None
    order = []
    for rk, _, waku, toban, tm in rows:
        r = zen2han(_text(rk))
        order.append({"rank": int(r) if r.isdigit() else None, "status": None if r.isdigit() else r,
                      "waku": int(waku), "toban": toban, "time": _text(tm) or None})
    out = {"order": order, "tri": None, "pay": None, "pop": None, "kimarite": None, "course": [], "st": {}}
    m = re.search(r'<td rowspan="2">3連単</td>(.*?)</tr>', page, re.S)
    if m:
        seg = m.group(1)
        nums = re.findall(r'numberSet1_number is-type\d">\s*(\d)', seg)
        pay = re.search(r'is-payout1">\s*&yen;([\d,]+)', seg)
        tds = re.findall(r"<td>\s*(\d+)\s*</td>", seg)
        if len(nums) == 3:
            out["tri"] = [int(x) for x in nums]
        if pay:
            out["pay"] = int(pay.group(1).replace(",", ""))
        if tds:
            out["pop"] = int(tds[-1])
    m = re.search(r"<th>決まり手</th>.*?<td[^>]*>(.*?)</td>", page, re.S)
    if m:
        k = _text(m.group(1))
        out["kimarite"] = KIM.get(k, k or None)
    for blk in re.findall(r'<div class="table1_boatImage1[^"]*">(.*?)</div>', page, re.S):
        m = re.search(r'table1_boatImage1Number is-type\d">\s*(\d)\s*<', blk)
        t = re.search(r'table1_boatImage1TimeInner[^"]*">(.*?)<', blk, re.S)
        if not m:
            continue
        out["course"].append(int(m.group(1)))
        out["st"][m.group(1)] = _st(t.group(1)) if t else None
    m = re.search(r"<th>備考</th>.*?<td[^>]*>(.*?)</td>", page, re.S)
    note = _text(m.group(1)) if m else ""
    if note:
        out["note"] = note
    return out


def parse_racelist(page: str) -> dict:
    """出走表のページから、選手ごとの今期のフライング・出遅れの回数と平均ST {登番: [F, L, 平均ST]}。"""
    out = {}
    for tb in re.findall(r'<tbody class="\s*is-fs12">(.*?)</tbody>', page, re.S):
        t = re.search(r"profile\?toban=(\d+)", tb)
        m = re.search(r'<td class="is-lineH2" rowspan="4">\s*F(\d+)\s*<br\s*/?>\s*L(\d+)\s*<br\s*/?>\s*([\d.\-]+)', tb)
        if t and m:
            try:
                st = float(m.group(3))
            except ValueError:
                st = None
            out[t.group(1)] = [int(m.group(1)), int(m.group(2)), st]
    return out


ORIG_LABELS = {"一周": "lap", "半周": "half", "まわり足": "turn", "直線": "line"}


def _cells(tr: str) -> list:
    return [" ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", c)).replace("\u3000", " ").split())
            for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S | re.I)]


def parse_orig(page: str) -> dict | None:
    """場のサイトの直前情報ページから、オリジナル展示データ {lap/half/turn/line: {枠: 秒}}。まだ出ていなければ None。
    見出しの並び(一周・半周・まわり足・直線)を読み、各艇の行の展示タイムのすぐ後ろから、その順に数字を取る。"""
    page = re.sub(r"<script.*?</script>", " ", page, flags=re.S | re.I)
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I)
    order = None
    for tr in trs:
        txt = " ".join(_cells(tr)).replace(" ", "")
        if "まわり足" not in txt:
            continue
        found = []
        for m in re.finditer(r"一周|半周|まわり足|直線", txt):
            k = ORIG_LABELS[m.group(0)]
            if k not in found:
                found.append(k)
        order = found
        break
    if not order:
        return None
    out = {k: {} for k in order}
    for tr in trs:
        cs = _cells(tr)
        if len(cs) < 4:
            continue
        waku = next((int(c) for c in cs[:2] if re.fullmatch(r"[1-6]", c)), None)
        if waku is None:
            continue
        nums = [float(c) if re.fullmatch(r"-?\d+\.\d{1,2}", c) else None for c in cs]
        ix = next((i for i, x in enumerate(nums) if x is not None and 6.0 <= x <= 7.6 and i >= 2), None)
        if ix is None:
            continue
        vals = nums[ix + 1:ix + 1 + len(order)]
        if len(vals) < len(order) or any(v is None or v <= 0 for v in vals):
            continue
        for k, v in zip(order, vals):
            out[k][str(waku)] = v
    if len(out[order[0]]) < 4:
        return None
    return out


def fetch(page: str, jcd: str, no: int, ymd: str) -> str | None:
    url = ORIG_URL[jcd].format(ymd=ymd, no=no) if page == "orig" else URL.format(page=page, no=no, jcd=jcd, ymd=ymd)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as ex:  # noqa: BLE001  通信の失敗は次の回にまわす
        print("読めませんでした:", page, jcd, no, ex, flush=True)
        return None


# ---------------------------------------------------------------- 保存
def day_dir(day: dt.date):
    return LIVE / f"{day:%Y%m%d}"


_TRIES: dict = {}          # 読みに行った回数(実行中はここに持つ。ファイルには、データが入ったときだけ書く)


def load_day(day: dt.date) -> tuple[dict, dict]:
    """場ごとの {before, result} と、読みに行った回数の記録。"""
    d = day_dir(day)
    venues = {}
    if d.exists():
        for p in sorted(d.glob("[0-9][0-9].json")):
            venues[p.stem] = load_json(p, {}) or {}
    state = load_json(d / "state.json", None) or {"tries": {}}
    tries = state.setdefault("tries", {})
    for k, n in _TRIES.get(day.isoformat(), {}).items():
        tries[k] = max(n, tries.get(k, 0))
    return venues, state


def save_day(day: dt.date, venues: dict, state: dict, changed: set) -> None:
    d = day_dir(day)
    for code in changed:
        v = venues[code]
        v["updated"] = dt.datetime.now(JST).strftime("%H:%M")
        save_json(d / f"{code}.json", v)
    _TRIES[day.isoformat()] = dict(state.get("tries", {}))
    if changed:
        save_json(d / "state.json", state)


# ---------------------------------------------------------------- 1回り
def tasks(prog: dict, venues: dict, state: dict, now: dt.datetime) -> list:
    out = []
    tries = state.setdefault("tries", {})
    for code, v in prog.get("venues", {}).items():
        lv = venues.get(code, {})
        for race in v.get("races", []):
            dl = race.get("deadline")
            if not dl:
                continue
            hh, mm = map(int, dl.split(":"))
            mins = (now.replace(hour=hh, minute=mm, second=0, microsecond=0) - now).total_seconds() / 60
            no = str(race["no"])
            b = (lv.get("before") or {}).get(no)
            if not (b and b.get("ready")) and BEFORE_UNTIL <= mins <= BEFORE_FROM and tries.get(f"b:{code}-{no}", 0) < MAX_TRIES["b"]:
                out.append((0, mins, "b", code, race["no"]))
            r = (lv.get("result") or {}).get(no)
            if not r and -RESULT_GIVEUP <= mins <= -RESULT_AFTER and tries.get(f"r:{code}-{no}", 0) < MAX_TRIES["r"]:
                out.append((1, -mins, "r", code, race["no"]))
            o = (lv.get("orig") or {}).get(no)
            if (code in ORIG_URL and b and b.get("ready") and not o and -10 <= mins <= BEFORE_FROM
                    and tries.get(f"o:{code}-{no}", 0) < MAX_TRIES["o"]):
                out.append((0, mins + 0.5, "o", code, race["no"]))
            fl = lv.get("fl") or {}
            if (BEFORE_FROM < mins <= LIST_AHEAD and any(x["toban"] not in fl for x in race.get("entries", []))
                    and tries.get(f"l:{code}-{no}", 0) < MAX_TRIES["l"]):
                out.append((2, mins, "l", code, race["no"]))
    out.sort()
    lists = [x for x in out if x[2] == "l"][:LIST_PER_CYCLE]
    return [x for x in out if x[2] != "l"] + lists


def cycle(day: dt.date, now: dt.datetime | None = None) -> set:
    """1回り。新しく取れた場のコードの集合を返す。"""
    prog = load_json(PROGRAM / f"{day:%Y%m%d}.json", None)
    if not prog:
        return set()
    now = now or dt.datetime.now(JST)
    venues, state = load_day(day)
    changed, n = set(), 0
    for _, _, kind, code, no in tasks(prog, venues, state, now):
        if n:
            time.sleep(WAIT_SEC)
        n += 1
        key = f"{kind}:{code}-{no}"
        state["tries"][key] = state["tries"].get(key, 0) + 1
        page = fetch({"b": "beforeinfo", "r": "raceresult", "l": "racelist", "o": "orig"}[kind], code, no, f"{day:%Y%m%d}")
        if not page:
            continue
        v = venues.setdefault(code, {"date": day.isoformat(), "code": code})
        if kind == "o":
            try:
                og = parse_orig(page)
            except Exception:  # noqa: BLE001
                og = None
            if og:
                og["fetched"] = dt.datetime.now(JST).strftime("%H:%M")
                v.setdefault("orig", {})[str(no)] = og
                changed.add(code)
            continue
        if kind == "l":
            try:
                fl = parse_racelist(page)
            except Exception:  # noqa: BLE001
                fl = {}
            if fl:
                v.setdefault("fl", {}).update(fl)
                changed.add(code)
            continue
        try:
            info = parse_before(page) if kind == "b" else parse_result(page)
        except Exception as ex:  # noqa: BLE001  見慣れない形のページは、とばして次へ
            print("読み取れませんでした:", kind, code, no, ex, flush=True)
            continue
        if not info:
            continue
        info["fetched"] = dt.datetime.now(JST).strftime("%H:%M")
        slot = v.setdefault("before" if kind == "b" else "result", {})
        old = slot.get(str(no))
        if kind == "b" and old and not info.get("ready") and old == {**info, "fetched": old.get("fetched")}:
            continue
        slot[str(no)] = info
        changed.add(code)
    if n:
        save_day(day, venues, state, changed)
    print(f"{now:%H:%M} {n}ページを読み、{len(changed)}場が更新", flush=True)
    return changed


def remaining(day: dt.date, now: dt.datetime) -> bool:
    """まだ読みに行くものがあるか(最終レースの結果まで)。"""
    prog = load_json(PROGRAM / f"{day:%Y%m%d}.json", None) or {}
    last = None
    for v in prog.get("venues", {}).values():
        for race in v.get("races", []):
            if race.get("deadline"):
                hh, mm = map(int, race["deadline"].split(":"))
                t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                last = t if last is None or t > last else last
    if last is None:
        return False
    venues, _ = load_day(day)
    done = all((venues.get(c, {}).get("result") or {}).get(str(r["no"]))
               for c, v in prog.get("venues", {}).items() for r in v.get("races", []))
    return not done and now <= last + dt.timedelta(minutes=RESULT_GIVEUP)


def _git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)


def _merge_live(theirs, ours, key=""):
    """同じファイルをほかの実行も書き換えていたときに、両方の取り込みを残す(どちらにもある所は、こちらを優先)。
    ただし直前情報は、展示が出そろった方(ready)を優先する。"""
    if not isinstance(theirs, dict) or not isinstance(ours, dict):
        return ours if ours is not None else theirs
    out = dict(theirs)
    for k, v in ours.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            if key == "before" and out[k].get("ready") and not v.get("ready"):
                continue
            out[k] = _merge_live(out[k], v, k)
        elif key == "tries" and isinstance(v, int) and isinstance(out.get(k), int):
            out[k] = max(v, out[k])
        else:
            out[k] = v
    return out


def _sync_with_remote(msg: str) -> None:
    """送れなかったとき: リポジトリの最新に合わせてから、こちらで取り込んだ分を足して送り直す。"""
    _git("rebase", "--abort")
    mine = {}
    for f in LIVE.rglob("*.json"):
        try:
            mine[f] = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            pass                                   # 壊れたファイル(衝突の印が入ったものなど)は捨てて、リポジトリの方を使う
    _git("fetch", "-q", "origin", "main")
    _git("reset", "-q", "--hard", "origin/main")
    for f, ours in mine.items():
        theirs = load_json(f, None) if f.exists() else None
        try:
            save_json(f, _merge_live(theirs, ours) if theirs is not None else ours)
        except Exception as ex:  # noqa: BLE001
            print("合わせられませんでした:", f, ex, flush=True)
    _git("add", "data/live")
    if _git("diff", "--cached", "--quiet").returncode != 0:
        _git("commit", "-q", "-m", msg)


def git_push(msg: str) -> None:
    """取り込んだものをリポジトリに送る(GitHub Actions の中で)。ほかの実行と同じファイルを書き換えていても、両方の分を残す。"""
    _git("add", "data/live")
    if _git("diff", "--cached", "--quiet").returncode == 0 and _git("status", "-sb").stdout.find("ahead") < 0:
        return
    if _git("diff", "--cached", "--quiet").returncode != 0:
        _git("commit", "-q", "-m", msg)
    for _ in range(4):
        if _git("pull", "--rebase", "--autostash", "-q", "origin", "main").returncode != 0:
            _sync_with_remote(msg)
        if _git("push", "-q").returncode == 0:
            return
        time.sleep(5)
    print("送れませんでした(次の回にまとめて送ります)", flush=True)


def git_sync() -> None:
    """読みに行く前に、リポジトリの最新(ほかの実行が送った分)を取り込む。"""
    if _git("pull", "--rebase", "--autostash", "-q", "origin", "main").returncode != 0:
        _sync_with_remote("直前情報・結果(合わせ直し) [skip ci]")


def after_change(day: dt.date, push: bool) -> None:
    """直前情報が新しく入ったら、締切前のレースの見立てを記録する(学習用。サイトには出さない)。
    取り込んだデータを送ったあとで作り、手元でまとめておいて次の回に一緒に送る。"""
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], cwd=ROOT, capture_output=True)
    subprocess.run(["node", str(ROOT / "scripts" / "predlog.js")], cwd=ROOT)
    if push:
        _git("add", "data/live")
        if _git("diff", "--cached", "--quiet").returncode != 0:
            _git("commit", "-q", "-m", f"見立ての記録 {dt.datetime.now(JST):%Y-%m-%d %H:%M} [skip ci]")


def dispatch(workflow: str) -> bool:
    """GitHub Actions の別の実行を起こす(GH_TOKEN があるときだけ)。"""
    if not os.environ.get("GH_TOKEN"):
        return False
    r = subprocess.run(["gh", "workflow", "run", workflow, "--ref", "main"], cwd=ROOT, capture_output=True, text=True)
    print(f"{workflow} を起こしました" if r.returncode == 0 else f"{workflow} を起こせませんでした: {r.stderr.strip()}", flush=True)
    return r.returncode == 0


def loop(minutes: float, push: bool) -> None:
    t0 = time.time()
    asked_update = False
    while True:
        now = dt.datetime.now(JST)
        day = now.date()
        if now.hour < 5:                     # 日付が変わったら終わる(朝の実行に任せる)
            print("今日の開催は終わりました", flush=True)
            return
        try:
            if push:
                git_sync()
            # 今日の番組表がまだないとき(毎日の更新の起動が遅れた・落ちた): 毎日の更新を起こす(1回だけ)
            if not (PROGRAM / f"{day:%Y%m%d}.json").exists():
                if push and not asked_update and now.hour >= 6:
                    asked_update = dispatch("update.yml")
            changed = cycle(day, now)
            if push:
                git_push(f"直前情報・結果 {now:%Y-%m-%d %H:%M} [skip ci]")
            if changed:
                after_change(day, push)
            if (PROGRAM / f"{day:%Y%m%d}.json").exists() and not remaining(day, now):
                print("今日の分は終わりました", flush=True)
                if push:
                    git_push(f"直前情報・結果 {now:%Y-%m-%d %H:%M} [skip ci]")
                return
        except Exception:  # noqa: BLE001  1回の失敗で止めず、次の回にやり直す
            import traceback
            traceback.print_exc()
            if push:
                _sync_with_remote(f"直前情報・結果 {now:%Y-%m-%d %H:%M} [skip ci]")
        left = minutes * 60 - (time.time() - t0)
        if left < CYCLE_SEC:
            return
        time.sleep(max(10, CYCLE_SEC - (time.time() - now.timestamp())))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=float, help="何分まで動かすか")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--push", action="store_true", help="取れたらリポジトリへ送る(GitHub Actions 用)")
    ap.add_argument("--parse", nargs=2, metavar=("KIND", "FILE"))
    ap.add_argument("--need-more", action="store_true", help="今日の分がまだ残っていれば 0 で終わる(次の実行を起こすかどうか)")
    a = ap.parse_args()
    if a.need_more:
        now = dt.datetime.now(JST)
        if now.hour < 5:
            return 1
        prog_exists = (PROGRAM / f"{now.date():%Y%m%d}.json").exists()
        return 0 if (not prog_exists or remaining(now.date(), now)) else 1
    if a.parse:
        kind, f = a.parse
        page = open(f, encoding="utf-8").read()
        fn = {"before": parse_before, "result": parse_result, "list": parse_racelist, "orig": parse_orig}[kind]
        print(json.dumps(fn(page), ensure_ascii=False, indent=1))
        return 0
    if a.loop:
        loop(a.loop, a.push)
    else:
        cycle(dt.datetime.now(JST).date())
    return 0


if __name__ == "__main__":
    sys.exit(main())
