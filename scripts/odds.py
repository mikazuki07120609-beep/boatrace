#!/usr/bin/env python3
"""オッズの取り込み(締切の直前のレースだけ)。

締切の15分前から締切までのレースは、1分ごとに公式サイトのオッズ(3連単・2連単・2連複・単勝・複勝)を読み、
最新の1回分だけを odds ブランチに上書きで置く(レースのページのオッズのタブが読みに来る)。
締切のあとは、締切時オッズ(確定)を1回だけ読み、日ごとのファイルに残す(期待値の確かめに使う)。

odds ブランチは、いつもコミット1つだけにして上書きで送る(古いオッズが履歴にたまらない)。
直前情報・結果の取り込み(live.py)とは別の実行で動かすので、こちらで何かあっても、あちらは止まらない。

  python3 scripts/odds.py --loop 345 --push     # 開催中ずっと(Actions)
  python3 scripts/odds.py --need-more           # 今日の分が残っているか(終了コード 0 = 残っている)
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as htmlmod
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from common import JST, PROGRAM, ROOT, load_json

URL = "https://www.boatrace.jp/owpc/pc/race/{page}?rno={no}&jcd={jcd}&hd={ymd}"
UA = "boatrace-site/0.1 (+https://github.com/mikazuki07120609-beep/boatrace)"
WAIT_SEC = 2                 # 公式サイトへのアクセスの間隔
CYCLE_SEC = 60
WINDOW_MIN = 15              # 締切の何分前から読むか
PAGES_PER_CYCLE = 27         # 1回り(1分)に読むページの上限。超える分は次の回り(古いものから)
FINAL_UNTIL = 40             # 締切の何分後まで、締切時オッズを読みに行くか
FINAL_TRIES = 6
KEEP_FINAL_DAYS = 120
PAGES = ("odds3t", "odds2tf", "oddstf")
WT = Path("/tmp/odds-worktree")          # odds ブランチの作業場所(Actions の中)
BRANCH = "odds"


# ---------------------------------------------------------------- 読み取り
def _text(s: str) -> str:
    return htmlmod.unescape(re.sub(r"<[^>]+>", "", s)).replace("　", " ").replace("\xa0", " ").strip()


def _num(s: str):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _range(s: str):
    m = re.match(r"\s*([\d.]+)\s*-\s*([\d.]+)", s)
    return [float(m.group(1)), float(m.group(2))] if m else None


def _tbody(page: str, title: str) -> str:
    """見出し(例: 3連単オッズ)のすぐ後ろの表の tbody。見つからなければ空。"""
    i = page.find(title)
    if i < 0:
        return ""
    j = page.find("<tbody", i)
    k = page.find("</table>", j)
    return page[j:k] if j >= 0 and k > j else ""


def _rows(tb: str) -> list:
    return [re.findall(r"<td([^>]*)>(.*?)</td>", r, re.S) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)]


def parse_stamp(page: str) -> tuple:
    """(オッズ更新時間 'HH:MM' か None, 締切時オッズか)"""
    if "tab4_time" in page and "締切時オッズ" in page:
        return None, True
    m = re.search(r"オッズ更新時間\s*(\d{1,2}:\d{2})", page)
    return (m.group(1) if m else None), False


def parse_3(page: str, title: str) -> dict:
    """3連単・3連複: 6つの列(1着・1つめの艇)ごとに、[2着の艇(4行ぶん)]・3着の艇・オッズ。"""
    out, second, rem = {}, [None] * 6, [0] * 6          # rem: 2着(2つめ)の艇の欄が、あと何行続くか
    for cells in _rows(_tbody(page, title)):
        k = 0
        for g in range(6):
            if rem[g] <= 0 and k < len(cells):
                m = re.search(r'rowspan="(\d+)"', cells[k][0])
                rem[g] = int(m.group(1)) if m else 1
                t = _text(cells[k][1])
                second[g] = int(t) if t.isdigit() else None
                k += 1
            rem[g] -= 1
            if k + 1 >= len(cells):
                break
            (a3, v3), (ao, vo) = cells[k], cells[k + 1]
            k += 2
            third = _text(v3)
            if second[g] and third.isdigit() and "oddsPoint" in ao:
                sep = "-" if title.startswith("3連単") else "="
                out[f"{g + 1}{sep}{second[g]}{sep}{third}"] = _num(_text(vo))
    return out


def parse_2(page: str, title: str, rng: bool = False) -> dict:
    """2連単・2連複・拡連複: 6つの列(1つめの艇)ごとに、2つめの艇・オッズ。"""
    out = {}
    sep = "-" if title.startswith("2連単") else "="
    for cells in _rows(_tbody(page, title)):
        for g in range(min(6, len(cells) // 2)):
            (_, v2), (ao, vo) = cells[2 * g], cells[2 * g + 1]
            b = _text(v2)
            if b.isdigit() and "oddsPoint" in ao:
                out[f"{g + 1}{sep}{b}"] = _range(_text(vo)) if rng else _num(_text(vo))
    return out


def parse_tf(page: str) -> tuple:
    """単勝・複勝: 艇ごとのオッズ(複勝は [下限, 上限])。"""
    def one(title, rng):
        i = page.find(title)
        j = page.find("</table>", i)
        out = {}
        if i < 0 or j < 0:
            return out
        for m in re.finditer(r'is-boatColor(\d)">\s*(\d)\s*</td>.*?<td class="oddsPoint[^"]*">([^<]*)</td>', page[i:j], re.S):
            out[m.group(2)] = _range(m.group(3)) if rng else _num(_text(m.group(3)))
        return out
    return one("単勝オッズ", False), one("複勝オッズ", True)


def fetch(page: str, jcd: str, no: int, ymd: str) -> str | None:
    req = urllib.request.Request(URL.format(page=page, no=no, jcd=jcd, ymd=ymd), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as ex:  # noqa: BLE001  通信の失敗は次の回にまわす
        print("読めませんでした:", page, jcd, no, ex, flush=True)
        return None


def read_race(jcd: str, no: int, ymd: str) -> dict | None:
    """1レース分のオッズ(3ページ)。どれも読めなければ None。"""
    rec: dict = {}
    for i, page in enumerate(PAGES):
        if i:
            time.sleep(WAIT_SEC)
        html = fetch(page, jcd, no, ymd)
        if not html:
            continue
        stamp, final = parse_stamp(html)
        rec["t"] = rec.get("t") or stamp
        rec["final"] = rec.get("final", False) or final
        if page == "odds3t":
            rec["3t"] = parse_3(html, "3連単オッズ")
        elif page == "odds2tf":
            rec["2t"] = parse_2(html, "2連単オッズ")
            rec["2f"] = parse_2(html, "2連複オッズ")
        else:
            rec["tan"], rec["fuku"] = parse_tf(html)
    if not any(rec.get(k) for k in ("3t", "2t", "tan")):
        return None
    rec["at"] = dt.datetime.now(JST).strftime("%H:%M:%S")
    return rec


# ---------------------------------------------------------------- 動きの記録(Actions のときだけ)
_LAST_REPORT = [0.0]


def report(state: str, desc: str, force: bool = False) -> None:
    """動いているか・失敗したかを、取り込みを始めたコミットの状態(commit status "odds")として残す。
    実行の記録(ログ)を見られないときでも、GitHub の API で確かめられる。成功の記録は5分に1回まで。"""
    import os
    sha, repo = os.environ.get("GITHUB_SHA"), os.environ.get("GITHUB_REPOSITORY")
    if not sha or not repo or not shutil.which("gh") or not os.environ.get("GH_TOKEN"):
        return
    if state == "success" and not force and time.time() - _LAST_REPORT[0] < 300:
        return
    _LAST_REPORT[0] = time.time()
    subprocess.run(["gh", "api", f"repos/{repo}/statuses/{sha}", "-f", f"state={state}", "-f", "context=odds",
                    "-f", f"description={desc[:139]}"], capture_output=True, text=True)


# ---------------------------------------------------------------- 置き場所(odds ブランチ)
def git(*a, cwd=None, check=False):
    return subprocess.run(["git", *a], cwd=cwd or ROOT, capture_output=True, text=True, check=check)


def setup_worktree() -> Path:
    """odds ブランチを作業場所に出す(なければ空のブランチを作る)。data/ 以外(形の確認に使ったページなど)は消す。"""
    if WT.exists():
        git("worktree", "remove", "--force", str(WT))
        shutil.rmtree(WT, ignore_errors=True)
    git("worktree", "prune")
    have = git("fetch", "-q", "origin", BRANCH).returncode == 0
    if have:
        git("worktree", "add", "--detach", str(WT), f"origin/{BRANCH}", check=True)
    else:
        git("worktree", "add", "--detach", str(WT), check=True)
        git("checkout", "-q", "--orphan", "odds-tmp", cwd=WT)
        git("rm", "-rqf", ".", cwd=WT)
    for p in WT.iterdir():
        if p.name not in (".git", "data"):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    return WT


def cleanup(base: Path, today: dt.date) -> None:
    """前の日までの最新オッズは消す。締切時オッズは KEEP_FINAL_DAYS 日だけ残す。"""
    for p in (base / "data" / "odds").glob("*"):
        if p.name != f"{today:%Y%m%d}":
            shutil.rmtree(p, ignore_errors=True)
    for p in (base / "data" / "odds_final").glob("*.json"):
        try:
            if (today - dt.datetime.strptime(p.stem, "%Y%m%d").date()).days > KEEP_FINAL_DAYS:
                p.unlink()
        except ValueError:
            pass


def publish(base: Path, msg: str) -> bool:
    """odds ブランチを、コミット1つだけにして上書きで送る。
    送るのはリポジトリの本体から(作業場所は本体とコミットを共有している。Actions の認証は本体の設定にあるため)。"""
    git("add", "-A", cwd=base)
    has_head = git("rev-parse", "--verify", "-q", "HEAD", cwd=base).returncode == 0
    r = git("commit", "-q", "--amend", "-m", msg, cwd=base) if has_head else git("commit", "-q", "-m", msg, cwd=base)
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        print("記録できませんでした:", r.stderr.strip(), flush=True)
    sha = git("rev-parse", "HEAD", cwd=base).stdout.strip()
    if not sha:
        return False
    err = ""
    for _ in range(3):
        p = git("push", "-q", "-f", "origin", f"{sha}:refs/heads/{BRANCH}")
        if p.returncode == 0:
            report("success", f"{msg} を送りました")
            return True
        err = p.stderr.strip()
        print("送れませんでした:", err, flush=True)
        time.sleep(3)
    report("failure", "送れませんでした: " + err, force=True)
    return False


# ---------------------------------------------------------------- 1回り
ORDER_3T = [f"{a}-{b}-{c}" for a in range(1, 7) for b in range(1, 7) for c in range(1, 7) if len({a, b, c}) == 3]
ORDER_2T = [f"{a}-{b}" for a in range(1, 7) for b in range(1, 7) if a != b]
ORDER_2F = [f"{a}={b}" for a in range(1, 7) for b in range(a + 1, 7)]


def compact_final(rec: dict) -> dict:
    """締切時オッズを、決まった並びの数字の並びにして小さくする(並びは ORDER_3T など)。"""
    def lst(d, order):
        return [d.get(k) for k in order] if d else None
    return {"t": rec.get("at"), "3t": lst(rec.get("3t"), ORDER_3T), "2t": lst(rec.get("2t"), ORDER_2T), "2f": lst(rec.get("2f"), ORDER_2F),
            "tan": [(rec.get("tan") or {}).get(str(i)) for i in range(1, 7)], "fuku": [(rec.get("fuku") or {}).get(str(i)) for i in range(1, 7)]}


def race_jobs(prog: dict, base: Path, day: dt.date, now: dt.datetime, state: dict) -> list:
    """読みに行くレース(締切が近い順。最新は WINDOW_MIN 分前から毎分、締切のあとは締切時オッズを1回)。"""
    out = []
    finals = load_json(base / "data" / "odds_final" / f"{day:%Y%m%d}.json", {}) or {}
    for code, v in prog.get("venues", {}).items():
        for race in v.get("races", []):
            dl = race.get("deadline")
            if not dl:
                continue
            hh, mm = map(int, dl.split(":"))
            mins = (now.replace(hour=hh, minute=mm, second=0, microsecond=0) - now).total_seconds() / 60
            key = f"{code}-{race['no']}"
            if -1 < mins <= WINDOW_MIN:
                last = state["last"].get(key, 0)
                if time.time() - last >= CYCLE_SEC - 5:
                    out.append((0, last, mins, code, race["no"]))
            elif -FINAL_UNTIL <= mins <= -1 and str(race["no"]) not in (finals.get(code) or {}) and state["tries"].get(key, 0) < FINAL_TRIES:
                out.append((1, state["tries"].get(key, 0), -mins, code, race["no"]))
    out.sort()
    return out


def cycle(base: Path, day: dt.date, state: dict, now: dt.datetime | None = None) -> int:
    prog = load_json(PROGRAM / f"{day:%Y%m%d}.json", None)
    if not prog:
        return 0
    now = now or dt.datetime.now(JST)
    jobs, pages, changed = race_jobs(prog, base, day, now, state), 0, 0
    final_path = base / "data" / "odds_final" / f"{day:%Y%m%d}.json"
    finals = load_json(final_path, {}) or {}
    for kind, _, _, code, no in jobs:
        if pages + len(PAGES) > PAGES_PER_CYCLE:
            break
        if pages:
            time.sleep(WAIT_SEC)
        key = f"{code}-{no}"
        rec = read_race(code, no, f"{day:%Y%m%d}")
        pages += len(PAGES)
        if kind == 0:
            state["last"][key] = time.time()
        else:
            state["tries"][key] = state["tries"].get(key, 0) + 1
        if not rec:
            continue
        path = base / "data" / "odds" / f"{day:%Y%m%d}" / code / f"{no:02d}.json"
        old = load_json(path, None)
        if old and any(old.get(k) for k in ("3t", "2t", "tan")):
            rec["prev"] = {k: old.get(k) for k in ("t", "at", "3t", "2t", "2f", "tan", "fuku") if old.get(k) is not None}
        rec["dl"] = next((r.get("deadline") for r in prog["venues"][code]["races"] if r["no"] == no), None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        changed += 1
        if kind == 1 and rec.get("final"):
            finals.setdefault(code, {})[str(no)] = compact_final(rec)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            final_path.write_text(json.dumps(finals, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if pages:
        print(f"{now:%H:%M} {pages}ページ・{changed}レースのオッズを更新", flush=True)
    return changed


def remaining(day: dt.date, now: dt.datetime, base: Path | None = None) -> bool:
    """まだ読むものがあるか(最後のレースの締切時オッズまで)。"""
    prog = load_json(PROGRAM / f"{day:%Y%m%d}.json", None) or {}
    last = None
    for v in prog.get("venues", {}).values():
        for race in v.get("races", []):
            if race.get("deadline"):
                hh, mm = map(int, race["deadline"].split(":"))
                t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                last = t if last is None or t > last else last
    return last is not None and now <= last + dt.timedelta(minutes=FINAL_UNTIL)


def loop(minutes: float, push: bool) -> None:
    end = time.time() + minutes * 60
    try:
        base = setup_worktree()
    except Exception as ex:  # noqa: BLE001
        report("failure", f"odds ブランチを用意できませんでした: {ex}", force=True)
        raise
    day = dt.datetime.now(JST).date()
    cleanup(base, day)
    state = {"last": {}, "tries": {}}
    if push:
        publish(base, f"オッズ {day:%Y-%m-%d}")
    while time.time() < end:
        now = dt.datetime.now(JST)
        if now.date() != day:
            print("日付が変わったので終わります", flush=True)
            break
        if not remaining(day, now):
            print("今日の分は終わりです", flush=True)
            break
        t0 = time.time()
        try:
            n = cycle(base, day, state, now)
        except Exception as ex:  # noqa: BLE001  1回りの失敗で止めない
            print("1回りに失敗:", ex, flush=True)
            report("error", f"1回りに失敗: {ex}", force=True)
            n = 0
        if n and push:
            publish(base, f"オッズ {now:%Y-%m-%d %H:%M}")
        time.sleep(max(5, CYCLE_SEC - (time.time() - t0)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=float, help="何分まで動かすか")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--need-more", action="store_true")
    a = ap.parse_args()
    if a.need_more:
        now = dt.datetime.now(JST)
        return 0 if now.hour >= 7 and remaining(now.date(), now) else 1
    if a.loop:
        loop(a.loop, a.push)
    return 0


if __name__ == "__main__":
    sys.exit(main())
