#!/usr/bin/env python3
"""毎日の更新: 公式ファイルを取り込んでJSONを更新し、サイトを作り直す。

  python3 scripts/update.py            # ダウンロードしてから作る(GitHub Actions用)
  python3 scripts/update.py --offline  # data/raw にあるテキストだけで作る(手元での確認用)

公式サーバーへの負担を抑えるため、1回の実行で取りに行くファイル数に上限を設け、
過去分の成績は少しずつ(1回あたり BACKFILL_PER_RUN 日分)取り込む。
"""
import argparse
import datetime as dt
import os
import pathlib
import shutil
import sys
import time

import build_site
import fetch
import parse
import pays
import times
from common import DATA, OUT as OUT_DIR, PROGRAM, RAW, RESULTS, load_json, save_json, today_jst

HISTORY_DAYS = 365       # 選手のコース別成績・戦法の傾向に使う期間
COMPACT_AFTER = 10       # この日数より前の成績は、集計に使う項目だけに縮めて保存する
BACKFILL_FIRST = 30      # 成績データがほとんどないときに、1回で取り込む過去の日数
LIVE_KEEP_DAYS = 90      # 取り込んだ直前情報・結果(data/live)と答え合わせの記録(data/learn)を残す日数
BACKFILL_PER_RUN = int(os.environ.get("BACKFILL_PER_RUN") or 10)   # ふだんの1回で取り込む過去の日数
REFETCH_PER_RUN = int(os.environ.get("REFETCH_PER_RUN") or 12)     # 風・展示タイムを残していなかった古い縮めた成績を、取り直す日数(1回あたり)
GRADE_PER_RUN = int(os.environ.get("GRADE_PER_RUN") or 20)         # 開催のグレードを取り込む過去の日数(1回あたり。今日・明日は毎回)
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
    if kind == "B":                       # 締切予定時刻は別に残す(番組表は数日で消すため。潮の満ち引きと合わせるのに使う)
        times.save(day, data)
    if kind == "K":                       # 払戻金は別のファイルに(裏水面ノートの「荒れ」の学習と答え合わせに使う)。成績のファイルの形は変えない
        pays.save(day, data)
        for v in data["venues"].values():
            for r in v.get("races", []):
                r.pop("pay", None)
    old = load_json(out / f"{day:%Y%m%d}.json", None) if kind == "B" else None
    if old and len(old.get("venues", {})) > len(data["venues"]):      # 取り直した番組表の方が場が少ないときは、前のものを残す
        log.append(f"{kind} {day}: 取り直した番組表の場が少ないので、前のものを残す")
        return "ok"
    save_json(out / f"{day:%Y%m%d}.json", data)
    n = sum(len(v["races"]) for v in data["venues"].values())
    log.append(f"{kind} {day}: {len(data['venues'])}場 {n}レースを保存")
    return "ok"


def compact(day: dict) -> dict:
    """集計と答え合わせに使う項目だけ残す。
    レース: 決まり手(k)と天候・風向・風速・波高(w)。
    艇: [着順か失格などの記号, 枠, 登番, 名前, 進入, ST, フライング, 展示タイム, モーター番号, レースタイム]"""
    out = {"date": day.get("date"), "compact": 3, "venues": {}}
    for code, v in day.get("venues", {}).items():
        out["venues"][code] = {"races": [
            {"no": r["no"], "k": r.get("kimarite"), "nm": r.get("name"),
             "w": [r.get("weather"), r.get("wind_dir"), r.get("wind"), r.get("wave")],
             "e": [[x.get("rank") or x.get("status"), x["waku"], x["toban"], x.get("name", ""), x.get("course"), x.get("st"),
                    1 if x.get("flying") else 0, x.get("ex"), x.get("motor"), x.get("time")] for x in r.get("entries", [])]}
            for r in v.get("races", [])]}
    return out


def lacks_wind(day: dict) -> bool:
    """古い形式で縮めた成績(風・展示タイム・レースタイムを残していない)か。"""
    c = day.get("compact")
    return c is True or c == 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    today = today_jst()
    state = load_json(STATE, {"missing_K": []})
    missing_k = set(state.get("missing_K", []))
    log: list[str] = []

    # 番組表: 今日と明日。前の日のうちに取ったものは、まだ全部の場がそろっていないことがあるので、毎回取り直す(1日1ファイル)
    for d in (today, today + dt.timedelta(days=1)):
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

    # 古いデータは消す(番組表は3日、成績は HISTORY_DAYS+7 日を超えたもの)。ページに出すのは今日と明日だけなので、番組表は短くてよい
    for folder, keep in ((PROGRAM, 3), (RESULTS, HISTORY_DAYS + 7)):
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

    # 取り込んだ直前情報・結果と、毎晩の答え合わせの記録は LIVE_KEEP_DAYS 日だけ残す(展示STの効き方の学習に使う分)。
    # 前に使っていた見立ての置き場(data/pred)は、もう使っていないので消す
    for p in list((DATA / "live").glob("*")) + list((DATA / "learn").glob("*.json")) + list((DATA / "pred").glob("*.json")):
        try:
            age = (today - dt.datetime.strptime(p.stem, "%Y%m%d").date()).days
        except ValueError:
            continue
        if p.parent.name == "pred" or age > LIVE_KEEP_DAYS:
            shutil.rmtree(p) if p.is_dir() else p.unlink()

    # 開催のグレード(女子戦の印)と女子レーサー(出走表の区分ごとのコース成績・女子レーサーの印に使う)
    if not a.offline:
        try:
            import grades
            grades.update_fem(today, log)
            grades.update_grades(today, GRADE_PER_RUN, log)
        except Exception as ex:  # noqa: BLE001  取れなくても、サイトの更新は続ける
            log.append(f"グレード・女子レーサーの取り込みをとばしました: {ex}")

    print("\n".join(log))
    if not a.offline:
        try:                                  # 潮位表(潮の満ち引きの差がある場の、今年の分。なければ気象庁から)
            import tide
            tide.ensure(today)
        except Exception as ex:  # noqa: BLE001
            print("潮位表の取り込みをとばしました:", ex)
    # 見立ての学習と答え合わせ(numpy・scipy が必要。ない環境では前回の学習結果をそのまま使う)
    try:
        import fit
        fit.main()
    except ImportError as ex:
        print("学習をとばしました:", ex)
    # 裏水面ノートの学習(1日1回。払戻金と見立てから、万舟の見込みの式と荒れの集計を作り直す)
    try:
        import ura_fit
        if ura_fit.due():
            import fit as _fit
            ura_fit.main(getattr(_fit, "LAST_RECS", None))
    except Exception as ex:  # noqa: BLE001  裏の学習に失敗しても、サイトの更新は続ける(前の学習結果を使う)
        print("裏の学習をとばしました:", ex)
    # 前の日の見立て・映像と結果を比べて記録する(成績のページに使うので、サイトを作る前に)
    try:
        import learn
        learn.main()
    except Exception as ex:  # noqa: BLE001  記録に失敗しても、サイトの更新は続ける
        print("見立てと結果の比較をとばしました:", ex)
    # 前の日の1周1マークの映像を、実際の結果と比べる。公開するサイトは今日と明日だけなので、
    # 前の日のレースのページは、答え合わせ用に公開しない場所(_review)に作って読ませる
    if shutil.which("node"):
        import subprocess
        yday = today - dt.timedelta(days=1)
        review = OUT_DIR.parent / "_review"
        try:
            n = build_site.build_review(yday, review)
        except Exception as ex:  # noqa: BLE001  答え合わせのページを作れなくても、サイトの更新は続ける
            print("答え合わせのページを作れませんでした:", ex)
            n = 0
        if n:
            subprocess.run(["node", str(pathlib.Path(__file__).with_name("learn_anim.js")), f"{yday:%Y%m%d}", str(review)], check=False)
        shutil.rmtree(review, ignore_errors=True)
    build_site.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
