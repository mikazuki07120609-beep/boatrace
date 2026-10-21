#!/usr/bin/env python3
"""毎日の更新: 公式ファイルを取り込んでJSONを更新し、サイトを作り直す。

  python3 scripts/update.py            # ダウンロードしてから作る(GitHub Actions用)
  python3 scripts/update.py --offline  # data/raw にあるテキストだけで作る(手元での確認用)

公式サーバーへの負担を抑えるため、1回の実行で取りに行くファイル数に上限を設け、
過去分の成績は少しずつ(1回あたり BACKFILL_PER_RUN 日分)取り込む。
"""
import argparse
import datetime as dt
import pathlib
import shutil
import subprocess
import sys
import time

import build_site
import fetch
import parse
from common import DATA, PROGRAM, RAW, RESULTS, load_json, save_json, today_jst

HISTORY_DAYS = 365       # 選手のコース別成績・戦法の傾向に使う期間
COMPACT_AFTER = 10       # この日数より前の成績は、集計に使う項目だけに縮めて保存する
BACKFILL_FIRST = 30      # 成績データがほとんどないときに、1回で取り込む過去の日数
BACKFILL_PER_RUN = 10    # ふだんの1回で取り込む過去の日数
REFETCH_PER_RUN = 8      # 風・展示タイムを残していなかった古い縮めた成績を、取り直す日数(1回あたり)
STATE = DATA / "fetch_state.json"


def ingest(kind: str, day: dt.date, log: list, offline: bool) -> str:
    """1日分を取り込む。戻り値: 'ok' / 'missing'(公式にまだない) / 'error'"""
    out = PROGRAM if kind == "B" else RESULTS
    raw = RAW / kind / f"{day:%Y%m%d}.txt"
    if offline:
        if not raw.exists():
            return "missing"
        path = raw
    else:
        path = fetch.fetch_one(kind, day, RAW, log)
        time.sleep(fetch.WAIT_SEC)
        if not path:
            return "missing"
    text = path.read_text(encoding="utf-8")
    data = parse.parse_program(text) if kind == "B" else parse.parse_results(text)
    if not data["venues"]:
        log.append(f"{kind} {day}: 読み取れたレースが0件")
        return "error"
    data["date"] = day.isoformat()
    save_json(out / f"{day:%Y%m%d}.json", data)
    n = sum(len(v["races"]) for v in data["venues"].values())
    log.append(f"{kind} {day}: {len(data['venues'])}場 {n}レースを保存")
    return "ok"


def compact(day: dict) -> dict:
    """集計と答え合わせに使う項目だけ残す。
    レース: 決まり手(k)と天候・風向・風速・波高(w)。
    艇: [着順か失格などの記号, 枠, 登番, 名前, 進入, ST, フライング, 展示タイム, モーター番号]"""
    out = {"date": day.get("date"), "compact": 2, "venues": {}}
    for code, v in day.get("venues", {}).items():
        out["venues"][code] = {"races": [
            {"no": r["no"], "k": r.get("kimarite"), "nm": r.get("name"),
             "w": [r.get("weather"), r.get("wind_dir"), r.get("wind"), r.get("wave")],
             "e": [[x.get("rank") or x.get("status"), x["waku"], x["toban"], x.get("name", ""), x.get("course"), x.get("st"),
                    1 if x.get("flying") else 0, x.get("ex"), x.get("motor")] for x in r.get("entries", [])]}
            for r in v.get("races", [])]}
    return out


def lacks_wind(day: dict) -> bool:
    """古い形式で縮めた成績(風・展示タイムを残していない)か。"""
    return day.get("compact") is True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    today = today_jst()
    state = load_json(STATE, {"missing_K": []})
    missing_k = set(state.get("missing_K", []))
    log: list[str] = []

    # 番組表: 今日と明日(まだ取り込んでいなければ取りに行く)
    for d in (today, today + dt.timedelta(days=1)):
        if not (PROGRAM / f"{d:%Y%m%d}.json").exists():
            ingest("B", d, log, a.offline)

    # 成績: 昨日の分(その日の全レースが終わったあとのファイル)と、過去分を少しずつ。
    # 今日の分は途中のファイルを取らないよう、日付が変わってから取り込む。
    have = {p.stem for p in RESULTS.glob("*.json")}
    d = today - dt.timedelta(days=1)
    if f"{d:%Y%m%d}" not in have:
        ingest("K", d, log, a.offline)
    have = {p.stem for p in RESULTS.glob("*.json")}
    limit = BACKFILL_FIRST if len(have) < 5 else BACKFILL_PER_RUN
    done = 0
    for i in range(2, HISTORY_DAYS + 1):
        if done >= limit:
            break
        d = today - dt.timedelta(days=i)
        key = f"{d:%Y%m%d}"
        if key in have or key in missing_k:
            continue
        r = ingest("K", d, log, a.offline)
        if a.offline and r == "missing":
            continue
        done += 1
        if r == "missing" and not a.offline:
            missing_k.add(key)

    # 風・展示タイムを残していなかった古い成績を、少しずつ取り直す(スタートの見立てと風の影響の集計に使う)
    if not a.offline:
        refetch = 0
        for p in sorted(RESULTS.glob("*.json"), reverse=True):
            if refetch >= REFETCH_PER_RUN:
                break
            if p.stem in missing_k or not lacks_wind(load_json(p, {})):
                continue
            r = ingest("K", dt.datetime.strptime(p.stem, "%Y%m%d").date(), log, False)
            refetch += 1
            if r != "ok":
                missing_k.add(p.stem)   # 取れなかった日は、縮めたまま使い続ける

    # 古いデータは消す(番組表は14日、成績は HISTORY_DAYS+7 日を超えたもの)
    for folder, keep in ((PROGRAM, 14), (RESULTS, HISTORY_DAYS + 7)):
        for p in folder.glob("*.json"):
            try:
                if (today - dt.datetime.strptime(p.stem, "%Y%m%d").date()).days > keep:
                    p.unlink()
            except ValueError:
                pass
    # 古い成績を縮める(着順・枠・登番・名前・進入・ST・フライングと、決まり手だけ残す)
    for p in RESULTS.glob("*.json"):
        try:
            age = (today - dt.datetime.strptime(p.stem, "%Y%m%d").date()).days
        except ValueError:
            continue
        if age > COMPACT_AFTER:
            day = load_json(p, {})
            if day and not day.get("compact"):
                save_json(p, compact(day))
    cutoff = f"{today - dt.timedelta(days=HISTORY_DAYS + 7):%Y%m%d}"
    save_json(STATE, {"missing_K": sorted(k for k in missing_k if k >= cutoff)})

    # 記録した本番前の見立ても、成績と同じ期間だけ残す
    for p in (DATA / "pred").glob("*.json"):
        try:
            if (today - dt.datetime.strptime(p.stem, "%Y%m%d").date()).days > HISTORY_DAYS + 7:
                p.unlink()
        except ValueError:
            pass

    print("\n".join(log))
    # 見立ての学習と答え合わせ(numpy・scipy が必要。ない環境では前回の学習結果をそのまま使う)
    try:
        import fit
        fit.main()
    except ImportError as ex:
        print("学習をとばしました:", ex)
    build_site.main()
    # 締切前のレースの見立てを記録する(答え合わせで、本番前に出していた数字と結果を比べるため)
    if shutil.which("node"):
        subprocess.run(["node", str(pathlib.Path(__file__).with_name("predlog.js"))], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
