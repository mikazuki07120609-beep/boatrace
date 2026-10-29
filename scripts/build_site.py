#!/usr/bin/env python3
"""data/ のJSONから、公開用のサイト(_site/)を作る。"""
import datetime as dt
import html
import json
import math
import os
import shutil
import subprocess

from common import DATA, OUT, PROGRAM, RESULTS, ROOT, SITE, VENUES, KIMARITE, deadline_of, load_json, parse_ymd, today_jst
from alerts import badges, race_alerts
from motor import motor_rates, raw_scores, venue_grades
import pace as pacemod
from stats import VENUE_DAYS, category_resolver, collect, venue_table

SITE_NAME = "水面ノート"
# サイトのURL(canonical・OGP・サイトマップ)。独自ドメインにしたら、ここを書きかえる(試すときは環境変数 SITE_URL で上書き)
BASE_URL = os.environ.get("SITE_URL") or "https://mikazuki07120609-beep.github.io/boatrace/"
PAST_DAYS = 0          # 今日より前に何日分のページを残すか(終わった日のページは出さない。今日と明日だけ)
# ページが開いている間に読みに行く直前情報・結果・締切の変更・オッズの置き場所。
# DATA_BASE(Cloudflare R2 の公開URL。例 https://data.example.com/)を先に読み、空のとき・読めないときは GitHub から読む
DATA_BASE = os.environ.get("DATA_BASE", "")
RAW_BASE = "https://raw.githubusercontent.com/mikazuki07120609-beep/boatrace/"
DATA_FALLBACK = {"live": RAW_BASE + "main/data/live/", "odds": RAW_BASE + "odds/data/odds/"}


def data_js() -> str:
    """どのページにも入れる小さな読み込み係(window.suimenGet(種類, "YYYYMMDD/…json"))。
    先に Cloudflare(DATA_BASE)を読み、ない(404)・読めないときは GitHub を読む。読めなかったときは3分間 GitHub だけを読む。
    中身は JSON か、ないときは null。つながらないときだけ失敗(reject)を返す。"""
    return ("<script>window.suimenGet=(function(){var P=" + json.dumps(DATA_BASE) + ",F=" + json.dumps(DATA_FALLBACK) + ",off=0;"
            "function one(u,ms){var c=ms&&window.AbortController?new AbortController():null,t=c?setTimeout(function(){c.abort();},ms):0;"
            "return fetch(u,c?{cache:\"no-store\",signal:c.signal}:{cache:\"no-store\"}).then(function(r){clearTimeout(t);"
            "if(r.status===404)return null;if(!r.ok)throw new Error(\"HTTP \"+r.status);return r.json();},function(e){clearTimeout(t);throw e;});}"
            "return function(k,rel){var q=\"?t=\"+Math.floor(Date.now()/15000),g=function(){return one(F[k]+rel+q).catch(function(e){"
            "if(e&&/^HTTP /.test(e.message))return null;throw e;});};"
            "if(!P||Date.now()<off)return g();"
            "return one(P+k+\"/\"+rel+q,6000).then(function(j){return j===null?g():j;},function(){off=Date.now()+180000;return g();});};})();</script>")
SEARCH: dict = {}      # 日付ごとの検索用のデータ(レース検索のページが読む {ymd}/search.json)
WD = "月火水木金土日"


def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def jdate(d: dt.date) -> str:
    return f"{d.month}月{d.day}日({WD[d.weekday()]})"


def f1(x, d=1):
    return "—" if x is None else f"{x:.{d}f}"


def pct(a, b):
    return None if not b else round(a / b * 100)


BASE_NOTES = ["当サイトは非公式のデータ解説サイトです。データは公式の番組表・競走成績ファイルと、BOAT RACE オフィシャルウェブサイトの直前情報・結果から自動で作っています。"
              "読み取りに誤りが含まれることがあるので、正確な情報は主催者発表のものをご確認ください。",
              "見立てや映像は過去のデータから計算した目安で、結果を保証するものではなく、舟券の購入をすすめるものでもありません。舟券の購入は20歳以上に限られます。"]


def page(title, desc, body, depth, path, scripts="", notes=None):
    rel = "../" * depth
    items = "".join(f"<li>{x}</li>" for x in (notes or []) + BASE_NOTES)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:type" content="website"><meta property="og:url" content="{BASE_URL}{path}">
<meta property="og:site_name" content="{SITE_NAME}"><meta name="twitter:card" content="summary">
<link rel="canonical" href="{BASE_URL}{path}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@400;500;700;800&family=Mochiy+Pop+One&family=Dela+Gothic+One&display=swap">
<link rel="stylesheet" href="{rel}assets/style.css">
{data_js()}
</head><body><div class="wrap">
<header class="site-head"><a class="logo" href="{rel}index.html">{SITE_NAME}</a>
<nav class="site-nav"><a href="{rel}index.html">今日のレース</a><a href="{rel}search.html">レース検索</a><a href="{rel}seiseki.html">見立ての成績</a><a href="{rel}about.html">このサイトについて</a></nav></header>
{body}
<footer><h2>注意とこのページの見方</h2><ul class="notes">{items}</ul></footer>
</div>{scripts}</body></html>"""


_OUT = [OUT]               # 書き出す先(ふだんは公開用の _site。答え合わせ用のページは build_review で別の場所に作る)


def write(path: str, text: str):
    p = _OUT[0] / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def venue_info(code, vstats, stadiums):
    st = stadiums.get(code, {})
    tbl = venue_table(vstats.get(code))
    if tbl:
        span = "直近1年" if VENUE_DAYS >= 365 else f"直近{VENUE_DAYS}日"
        src = f"当サイト集計({span}・{tbl['races']}レース)"
        place, kim = tbl["place"], tbl["kimarite"]
    else:
        src = f"BOAT RACE オフィシャルウェブサイト「ボートレース場データ」({st.get('period', '')})"
        place, kim = st.get("place"), st.get("kimarite")
    return {"code": code, "name": VENUES.get(code, code), "pref": st.get("pref"), "water": st.get("water"),
            "tide": st.get("tide"), "place": place, "kimarite": kim, "src": src}


def tier(p1):
    if p1 >= 60:
        return "イン天国"
    if p1 >= 52:
        return "イン有利"
    if p1 >= 45:
        return "標準よりやや荒れ"
    return "荒れ水面"


def racer_view(entry, racers, code=None):
    r = racers.get(entry["toban"], {})
    cs = {}
    st_sum = st_n = n_all = 0
    for c, s in r.get("c", {}).items():
        cs[c] = {"n": s["n"], "w1": s["w1"], "w2": s["w2"], "w3": s["w3"], "st": s["st"], "km": s.get("km", {})}
        for k in ("ls", "s2", "s3", "ng", "wc", "sl", "sn"):       # sn: 平均STの本数(予想STの「このコースでのSTのくせ」に使う)
            if s.get(k):
                cs[c][k] = s[k]
        n_all += s["n"]
        if s["st"] is not None:
            st_sum += s["st"] * s["n"]
            st_n += s["n"]
    v = {k: entry.get(k) for k in ("waku", "toban", "name", "cls", "age", "branch", "weight", "rate", "rate2",
                                   "local", "local2", "motor", "motor2", "boat", "boat2")}
    # 番組表の名前は4文字で切れることがあるので、成績ファイルの名前(省略なし)があればそちらを使う
    if r.get("name"):
        v["name"] = r["name"]
    s = entry.get("series")
    v["series"] = " ".join(s) if isinstance(s, list) else (s or "")
    v["cs"] = cs
    v["n_all"] = n_all
    v["st_all"] = round(st_sum / st_n, 2) if st_n else None
    # 見立てモデル(model.js)が使う集計: 着順点[合計, 走数]、ST[走数, 合計, 2乗の合計]、フライングした日
    v["pts"] = r.get("pts", [0, 0])
    v["stx"] = r.get("stx", [0, 0, 0])
    v["f"] = r.get("f", [])
    v["r8"] = r.get("r8", [])
    v["cb"] = r.get("cb", [0, 0])            # ゴールで僅差だった相手との[勝ち, 回数](道中の競り合い)
    v["nk"] = r.get("nk", [0, 0])            # [抜きで1着, 抜かれて2着]
    if code:
        v["lv"] = list(r.get("v", {}).get(code, [0, 0]))   # この場での[着順点, 走数](見立てのモデルの「当地の相性」)
    v["series_codes"] = s if isinstance(s, list) else []
    return v


def period_start(d: dt.date) -> str:
    """フライングの回数を数える期の始まり(5月1日・11月1日)。"""
    if d.month >= 11:
        return f"{d.year}-11-01"
    if d.month >= 5:
        return f"{d.year}-05-01"
    return f"{d.year - 1}-11-01"


SERIES_MARK = {"S": "失", "F": "F", "L": "L", "K": "欠"}


def series_points(days: list) -> tuple:
    """今節成績(日ごとの着順の文字)から [得点, 走数]。失格・F・Lは0点で1走、欠場は数えない。"""
    pts = n = 0
    for day in days or []:
        for ch in day:
            if ch in "123456":
                pts += {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1}[int(ch)]
                n += 1
            elif ch in "SFL":
                n += 1
    return pts, n


def series_ranks(vprog: dict, extra: dict | None = None) -> dict:
    """その場の今節の得点率(着順点の平均)の順位。番組表に載っている選手の中で。extra は今日すでに走ったレースの着順。"""
    seen = {}
    for race in vprog.get("races", []):
        for x in race["entries"]:
            if x["toban"] not in seen:
                seen[x["toban"]] = series_points((x.get("series") or []) + [(extra or {}).get(x["toban"], "")])
    rows = sorted(((t, p / n) for t, (p, n) in seen.items() if n), key=lambda kv: -kv[1])
    out, total = {}, len(rows)
    for t, avg in rows:
        rank = 1 + sum(1 for _, a in rows if a > avg + 1e-9)                # 同点は同じ順位
        out[t] = (rank, total, avg)
    return out


def today_marks(vlive: dict, vprog: dict) -> dict:
    """今日すでに終わったレースの着順(選手ごと、レース順の文字列)。直後に取り込んだ結果から。"""
    out = {}
    for race in sorted(vprog.get("races", []), key=lambda r: r["no"]):
        res = (vlive.get("result") or {}).get(str(race["no"]))
        if not res:
            continue
        for o in res.get("order", []):
            st = o.get("status") or ""
            ch = str(o["rank"]) if o.get("rank") else ("F" if "F" in st else "L" if "L" in st else "K" if "欠" in st else "S" if st else "")
            if ch:
                out[o["toban"]] = out.get(o["toban"], "") + ch
    return out


def course_table(vs: dict | None) -> dict:
    """場・全国のコース別の集計を、見立てモデルが使う形(コース → 走数・1着数・決まり手)にする。"""
    out = {}
    for c in range(1, 7):
        vc = (vs or {}).get("c", {}).get(str(c), {"n": 0, "w1": 0, "km": {}})
        out[str(c)] = {"n": vc["n"], "w1": vc["w1"], "km": {k: v for k, v in vc["km"].items() if v > 0}}
    return out


def review_text(vname, rno, res, url):
    ents = res["entries"]
    fin = sorted([x for x in ents if x.get("rank")], key=lambda x: x["rank"])
    if not fin:
        return ""
    w = fin[0]
    k = res.get("kimarite") or "—"
    sts = [x for x in ents if x.get("st") is not None and not x.get("flying")]
    st_rank = sorted(sts, key=lambda x: x["st"])
    lines = [f"【{vname}{rno}R 回顧】"]
    how = {
        "逃げ": "スタートから先に1マークを回って、そのまま逃げ切り。",
        "捲り": "1マークで内側の艇をまとめて叩く、まくり。",
        "差し": "1マークで内の艇が回った内側を突く、差し。",
        "捲り差し": "1マークで外から内に切り込む、まくり差し。",
        "抜き": "1マークでは決まらず、道中の競り合いを制した抜き。",
        "恵まれ": "前を走る艇の事故や失格で繰り上がった恵まれ。",
    }.get(k, "")
    lines.append(f"1着は{w['course'] or w['waku']}コースの{w['waku']}号艇 {w['name']}。{how}")
    if w.get("st") is not None and st_rank:
        pos = next((i + 1 for i, x in enumerate(st_rank) if x is w), None)
        if pos == 1:
            lines.append(f"ST{w['st']:.2f}は{len(st_rank)}艇でトップ。スタートで主導権を取った。")
        elif pos:
            lines.append(f"STは{w['st']:.2f}で{pos}番目。トップは{st_rank[0]['waku']}号艇の{st_rank[0]['st']:.2f}。")
    one = next((x for x in ents if x.get("course") == 1), None)
    if one and one is not w:
        rk = f"{one['rank']}着" if one.get("rank") else (one.get("status") or "着外")
        lines.append(f"1コースの{one['name']}は{rk}。")
    if len(fin) >= 3:
        lines.append(f"2着 {fin[1]['waku']}号艇 {fin[1]['name']}、3着 {fin[2]['waku']}号艇 {fin[2]['name']}。")
    fl = [x for x in ents if x.get("flying")]
    if fl:
        lines.append("フライング: " + "、".join(f"{x['waku']}号艇 {x['name']}" for x in fl) + "。")
    lines.append(f"天候 {res.get('weather', '')}・風 {res.get('wind_dir', '')}{res.get('wind', '')}m・波 {res.get('wave', '')}cm。")
    lines += ["", f"#ボートレース #{vname}"]
    return "\n".join(lines)


LOSS = {"差し": "差され", "捲り": "捲られ", "捲り差し": "捲り差され"}
KS = {"逃げ": "逃げ", "捲り": "捲り", "差し": "差し", "捲り差し": "捲差", "抜き": "抜き", "恵まれ": "恵まれ"}
SECOND_ORDER = ["差し", "捲り", "捲り差し", "残し", "道中", "差され", "捲られ", "捲り差され", "抜かれ", "その他"]


def st_txt(x) -> str:
    return "—" if x is None else (f"{x:.2f}".lstrip("0") if x >= 0 else "F" + f"{-x:.2f}".lstrip("0"))


def win_text(cs, course) -> str:
    """勝ったときの決まり手(多い順に2つ)。"""
    if not cs or not cs.get("n"):
        return "—"
    km = cs.get("km") or {}
    if course == 1:
        return f"逃げ{km.get('逃げ', 0)}" + (f" 抜き{km['抜き']}" if km.get("抜き") else "")
    items = sorted(((k, v) for k, v in km.items() if v > 0 and k != "恵まれ"), key=lambda kv: -kv[1])[:2]
    return " ".join(f"{KS.get(k, k)}{v}" for k, v in items) or "—"


def second_text(cs) -> str:
    """2着になったときの動き(推定。多い順に2つ)。"""
    s2 = (cs or {}).get("s2") or {}
    items = sorted(((k, v) for k, v in s2.items() if v > 0 and k != "その他"),
                   key=lambda kv: (-kv[1], SECOND_ORDER.index(kv[0]) if kv[0] in SECOND_ORDER else 99))[:2]
    return " ".join(f"{KS.get(k, k)}{v}" for k, v in items) or "—"


def nige_pair(cs, course) -> tuple:
    if not cs or not cs.get("n"):
        return ("", "—")
    if course == 1:
        return ("逃げ", f"{pct((cs.get('km') or {}).get('逃げ', 0), cs['n'])}%")
    if course == 2:
        return ("逃がし", f"{pct(cs.get('ng', 0), cs['n'])}%")
    return ("", "—")


def course_cells(cs, course) -> str:
    """出走表の「このコース」の4つのセル(1着・2着・3連対・ST/走数)と、勝ち方・2着の時・逃げ逃がし。"""
    if cs and cs.get("n"):
        n = cs["n"]
        a = (f'<td class="c1"><b>{pct(cs["w1"], n)}%</b></td><td class="c2">{pct(cs["w2"], n)}%</td>'
             f'<td class="c3">{pct(cs["w1"] + cs["w2"] + cs["w3"], n)}%</td>'
             f'<td class="c4"><span>{st_txt(cs.get("st"))}</span><span class="dim">{n}走</span></td>')
    else:
        a = '<td class="c1">—</td><td class="c2">—</td><td class="c3">—</td><td class="c4"><span>—</span><span class="dim">0走</span></td>'
    lab, val = nige_pair(cs, course)
    return (a + f'<td class="txt c5"><span>{e(win_text(cs, course))}</span><span class="dim">{e(second_text(cs))}</span></td>'
            f'<td class="c6"><span class="dim">{e(lab) or "&nbsp;"}</span><span>{e(val)}</span></td>')


def series_html(days: list, today: str, rk) -> str:
    groups = []
    for day in list(days or []) + ([today] if today else []):
        groups.append("".join(f'<i class="ng">{SERIES_MARK[ch]}</i>' if ch in SERIES_MARK else (f'<i class="top">{ch}</i>' if ch == "1" else f"<i>{ch}</i>")
                              for ch in day))
    chips = '<span class="days">' + "".join(f"<em>{g}</em>" for g in groups if g) + "</span>" if any(groups) else "<span>—</span>"
    sub = f'<span class="dim">{rk[0]}位/{rk[1]}人</span>' if rk else '<span class="dim">&nbsp;</span>'
    return f'<td class="series">{chips}{sub}</td>'


def card_html(ents, d, ranks, today_m) -> str:
    """出走表。1艇1行で、1つのセルに縦に2〜3つの数字を並べる(公式の出走表と同じ読み方)。"""
    ps = period_start(d)
    rows = []
    for x in ents:
        cs = x["cs"].get(str(x["waku"]))
        fl = x.get("fl")
        fp = fl[0] if fl else sum(1 for f in x.get("f", []) if ps <= f < d.isoformat())
        lp = fl[1] if fl else None
        ast = fl[2] if fl and fl[2] is not None else x.get("st_all")
        mg = x.get("mg") or {}
        g = mg.get("grade") or "—"
        lhtml = f' <i class="dim">L{lp}</i>' if lp is not None else ""
        rows.append(
            f'<tr data-waku="{x["waku"]}"><td class="w w{x["waku"]}">{x["waku"]}</td>'
            f'<td class="who"><b>{e(x["name"])}</b><span class="dim">{e(x["toban"])} {e(x["cls"])} {e(x["branch"])}</span>'
            f'<span class="dim">{e(x["age"])}歳 {f1(x.get("weight"), 1) if x.get("weight") else "—"}kg</span></td>'
            f'<td class="fl"><span><i class="{"fon" if fp else ""}">F{fp}</i>{lhtml}</span>'
            f'<span>{st_txt(ast)}</span></td>'
            f'<td><b>{f1(x["rate"], 2)}</b><span class="dim">{f1(x["rate2"])}%</span></td>'
            f'<td><b>{f1(x["local"], 2)}</b><span class="dim">{f1(x["local2"])}%</span></td>'
            + course_cells(cs, x["waku"]) +
            f'<td class="mo"><b class="g g{g}" title="モーター評価">{g}</b></td>'
            f'<td><span>{e(x["motor"])}</span><span class="dim">{f1(x["motor2"])}%</span></td>'
            f'<td><span>{e(x["boat"])}</span><span class="dim">{f1(x["boat2"])}%</span></td>'
            + series_html(x.get("series_codes"), today_m.get(x["toban"], ""), ranks.get(x["toban"])) + "</tr>")
    head = ('<thead><tr><th class="w" rowspan="2">枠</th><th class="who" rowspan="2">選手</th><th rowspan="2">F・L<br>平均ST</th>'
            '<th rowspan="2">全国<br>勝率</th><th rowspan="2">当地<br>勝率</th><th colspan="6" class="grp" id="cardCourse">このコース(枠と同じ)</th>'
            '<th colspan="2" class="grp">モーター</th><th rowspan="2">ボート</th><th rowspan="2">今節<br>着順・順位</th></tr>'
            '<tr><th>1着</th><th>2着</th><th>3連</th><th>ST</th><th>勝ち方<br>2着の時</th><th>逃げ<br>逃がし</th><th>評価</th><th>No<br>2連率</th></tr></thead>')
    return f'<div class="scroll rcwrap"><table class="rc" id="card">{head}<tbody>{"".join(rows)}</tbody></table></div>'


def result_banner(res_live, result) -> str:
    """終わったレースの結果(3連単の組と払戻金)。"""
    tri = pay = pop = kim = None
    if res_live:
        tri, pay, pop, kim = res_live.get("tri"), res_live.get("pay"), res_live.get("pop"), res_live.get("kimarite")
    if result:
        fin = sorted([x for x in result["entries"] if x.get("rank")], key=lambda x: x["rank"])
        if not tri and len(fin) >= 3:
            tri = [x["waku"] for x in fin[:3]]
        kim = kim or result.get("kimarite")
    if not tri:
        return '<section class="resbar" id="resbar" hidden></section>'
    t = '<span class="sep">-</span>'.join(f'<span class="waku w{w}">{w}</span>' for w in tri)
    odds = f'<b class="odds">{pay / 100:.1f}倍</b>' + (f'<span class="dim">{pop}番人気</span>' if pop else "") if pay else ""
    return (f'<section class="resbar" id="resbar"><span class="lbl">結果</span><span class="tri">{t}</span>{odds}'
            + (f'<span class="tag">{e(kim)}</span>' if kim else "") + "</section>")


RACE_NOTES = [
    "出走表:「このコース」は、枠番と同じコースに入ったとき(展示で進入が変わったら、そのコース)の直近1年の成績です。1着・2着・3着の率、平均STと走数。赤はその項目で1位、青は2位の艇です。黄色の印はフライング(F)と、今節の失格・出遅れ・欠場です。",
    "女子戦・SG・G1・G2・G3・一般の区分は、BOAT RACE オフィシャルウェブサイトの開催のグレードから取っています(オールレディース・ヴィーナスシリーズと、6艇とも女子レーサーのレースは女子戦)。"
    "出走表の「(区分)のときのこのコース」は、その区分のレースだけで数えた直近1年の成績です。♥は女子レーサーです(公式の選手期別成績から。新しくデビューした選手は、次のファイルが出るまで付きません)。",
    "勝ち方は、そのコースで1着になったときの決まり手の回数。2着の時は、2着になったレースでどう動いたかの推定です(公式の記録は1着の決まり手だけなので、1着の艇のコース・決まり手と、スタートの並びから推定)。"
    "1コースは差され・捲られなど負け方、2〜6コースは差し(勝った艇の内の筋)・捲り(内より先に出て外から)・捲差(間の艇の前を横切って内へ)・残し(外に先に回られたが残した)・道中(道中の抜き合い)。",
    "逃げ・逃がしは、1コースのときに逃げた割合と、2コースのときに1コースが逃げた割合(逃がし率。低いほど1コースを崩している)。",
    "F・Lは今期(5〜10月・11〜4月)のフライング・出遅れの回数(公式の出走表から。取れていないときは当サイトの集計)。今節は日ごとの着順で、失は失格、欠は欠場。順位は今節の着順点の平均(得点率の目安)の順位です。",
    "モーター評価(S〜E)は、直近60日の成績から乗った選手の勝率とコースの有利不利を差し引いた分、展示タイムの速さ、公式のモーター2連率を合わせて、その場のモーターの中で比べたものです。"
    "S+は、全国の全モーターの中でも飛び抜けたもの(乗った選手の力を差し引いた成績と展示の速さが、全国の平均から4標準偏差以上で、直近60日に20走以上。数百機に1機ほどで、いないときは出ません)。"
    "展示のあとは、そのレースの展示タイムも加えて評価し直します。",
    "直前情報(展示タイム・スタート展示・チルト・部品交換・水面気象)は、締切の10〜15分前ごろに BOAT RACE オフィシャルウェブサイトから自動で取り込みます。",
    "桐生・浜名湖・三国・びわこ・尼崎・鳴門・徳山・若松は、場が出している展示航走の計測タイム(オリジナル展示データ: 一周または半周・まわり足・直線)をそのまま出しています。"
    "測り方は場ごとに違うので、同じレースの6艇の中で比べてください(短いほど良い)。",
    "直線速度(推定)は展示タイム(直線150m)から出した速さです。一周タイム(推定)は、その場の標準の一周に、モーター(直近60日)と選手(直近1年)のレースのペース"
    "(同じレースの同じ着順の平均と比べた速さ)と、展示タイムの差を足したもの。まわり足(推定)は、そのペースのうち展示タイム(直線の速さ)では説明できない分で、マイナスほど旋回が速い目安です。"
    "どちらも公式の計測ではなく、レースタイムから計算した推定です。展示タイム1位の選手の成績は、このレースで展示タイムが一番速かった選手(同タイムは全員)が、直近1年に展示タイム1位だったレースの、コース別の回数と1着・2着・3着になった割合です。下の小さい数字は、全国(全選手)で展示タイム1位だった艇の、直近半年のコース別の割合です(回数が20回に満たないときは出しません)。",
    "1周1マークの映像・スタートの見立て(直前情報のタブ)・展開の見立ては、スタート展示の進入とSTが出てから計算します。スタートの見立ては、選手の平均ST・ばらつき・フライング持ち・コース・"
    "そのコースでのSTのくせ(その選手のそのコースの平均ST)・展示タイム・風・展示STから、"
    "過去のレースで実際に起きたスタートのずれ方を当てはめた400通りのスタートで計算し、展開の見立てはそれぞれのスタートでどのコースがどの決まり手で1着になりやすいかを平均したものです。"
    "展開の見立てには、レースの種類(優勝戦・準優勝戦・ドリーム戦・選抜戦・特選・予選・一般・進入固定)による1号艇の勝ちやすさの違いも入れています。式の重みは毎晩学習し直しています。",
    "本線は、1着になる見込み(勝ち方を全部足したもの)が一番高い艇の、一番起こりやすい勝ち方です。1号艇の逃げ1つの見込みより、ほかの艇の勝ち方を足した見込みの方が高ければ、その艇を本線にします。",
    "欠場の艇があるレースは、展開の見立て・1周1マークの映像・スタートの見立て・展開ナビを出しません(見立ては6艇そろったレースだけで計算しています)。"
    "締切の時刻は、公式サイトの最新の締切予定時刻に合わせます(レースが遅れたときは「(変更)」と出します)。",
    "映像の差しは内の艇の後ろから内へ、捲りは内の艇の外を全速で、まくり差しは隣の艇の前を横切ってさらに内の艇の内へ。吹き出しの戦法名は、走らせた結果の位置関係から決めています。",
    "本線の2着・3着は、1着の艇と決まり手ごとに、1着の艇から見た位置・勝率・スタート・展示タイム・モーター・そのコースの2着率から、過去のレースで学習した式で出しています。"
    "映像は、決着パターンごとに一番ありそうな着順になるように、各艇の伸びと回り方を合わせています。",
    "終わったレースの映像も、スタート展示のあとに出した見立てのままです(各艇が実際にどう回ったかは公式の記録にないため、レースの再現はしていません)。",
    "道中の競り合いは、ゴールで0.6秒差以内だった相手との勝ち負けから見ています。",
    "展開ナビは、選んだ艇がその決まり手で1着になったとして、2着・3着の起こりやすさを本線の2着・3着と同じ式で出しています。動きの言葉(捲りについて行く・最内を差すなど)は、1着の艇との位置関係と、"
    "その艇がそのコースで2着になったときの動き方から付けた目安です。「全国」は、過去1年の全国のレースで同じコース・同じ決まり手だったときの、そのコースが2着・3着になった割合です。"
    "スタート展示の前は、枠なりの進入・ふだんのSTとして計算し、展示のあとに計算し直します。",
    "結果(3連単の払戻金・決まり手)は、レースの数分後に BOAT RACE オフィシャルウェブサイトから取り込みます。",
    "オッズは、締切の15分前から締切までのレースだけ、1分ごとに BOAT RACE オフィシャルウェブサイトから取り込んでいます(公式の表示より最大で1〜2分遅れます)。"
    "締切のあとは締切時オッズです。矢印は、ひとつ前の取り込み(約1分前)からの変化で、↓はオッズが下がった(票が集まった)組です。",
]


CAT_CLASS = {"女子戦": "cw", "SG": "cSG", "G1": "cG1", "G2": "cG2", "G3": "cG3", "一般": "cIp"}


def cat_tag(cat) -> str:
    return f'<span class="tag cat {CAT_CLASS.get(cat, "")}">{e(cat)}</span>' if cat else ""


KIM_HEAD = {"逃げ": "逃げ", "捲り": "捲り", "差し": "差し", "捲り差し": "捲り<br>差し", "抜き": "抜き", "恵まれ": "恵まれ"}


def place_kim_tables(place, kim) -> str:
    """コース別の着順(1着・2着・3着)と、1着の決まり手の割合を、横に動かさなくても見られる2つの表にする。
    1位(一番高い)は赤、2位は青(着順は列ごと、決まり手は行ごと)。"""
    if not place:
        return ""
    def r12(vals):
        u = sorted({v for v in vals if v is not None and v > 0}, reverse=True)
        return (u[0] if u else None), (u[1] if len(u) > 1 else None)
    cols = [r12([place[i][j] for i in range(6)]) for j in range(3)]
    rows1 = "".join(f'<tr><td><span class="waku w{i + 1}">{i + 1}</span></td>' + "".join(
        f'<td class="num{" hi" if v == cols[j][0] else " hi2" if v == cols[j][1] else ""}">{f1(v)}</td>' for j, v in enumerate(place[i])) + "</tr>" for i in range(6))
    rows2 = ""
    for i in range(6):
        k = kim[i] if kim else [0] * 6
        a, b = r12(k)
        rows2 += (f'<tr><td><span class="waku w{i + 1}">{i + 1}</span></td>' + "".join(
            f'<td class="num{" hi" if v == a else " hi2" if v == b else ""}">{f1(v)}</td>' for v in k) + "</tr>")
    return ('<div class="pkt"><div class="gridt-wrap"><table class="gridt kt"><caption>着順の割合</caption><thead><tr><th>コース</th><th class="num">1着</th><th class="num">2着</th><th class="num">3着</th></tr></thead>'
            f'<tbody>{rows1}</tbody></table></div>'
            '<div class="gridt-wrap"><table class="gridt kt kk"><caption>1着の決まり手</caption><thead><tr><th>コース</th>'
            + "".join(f'<th class="num">{KIM_HEAD.get(k, k)}</th>' for k in KIMARITE) + f'</tr></thead><tbody>{rows2}</tbody></table></div></div>')


def build_race(d, code, vprog, race, vinfo, racers, result, tables, depth=2, ranks=None, vlive=None, motors=None, today_m=None, alerts=None, pace=None, mrates=None,
               cat=None, cat_tbl=None, fem=None):
    ymd = d.strftime("%Y%m%d")
    vname = vinfo["name"]
    path = f"{ymd}/{code}/{race['no']:02d}.html"
    url = BASE_URL + path
    vlive = vlive or {}
    no = str(race["no"])
    before = (vlive.get("before") or {}).get(no)
    res_live = (vlive.get("result") or {}).get(no)
    dl_prog = race.get("deadline")
    dl_now = deadline_of(race, vlive)                 # 公式の今の締切(レースが遅れて変わっていればそちら)
    ents = [racer_view(x, racers, code) for x in race["entries"]]
    ps = period_start(d)
    for x in ents:
        x["mg"] = (motors or {}).get(str(x["motor"]))
        x["motorR"] = ((mrates or {}).get(code) or {}).get(str(x["motor"]))   # 直近180日の成績の2連率(見立てのモデルが使う)
        fl = (vlive.get("fl") or {}).get(x["toban"])
        if fl:
            x["fl"] = fl
        # 出走表(race.js が縦の表にする)に使う: F・Lの回数、平均ST、今節の着順(今日の分も)、節間順位
        x["fp"] = fl[0] if fl else sum(1 for f in x.get("f", []) if ps <= f < d.isoformat())
        x["lp"] = fl[1] if fl else None
        x["ast"] = fl[2] if fl and fl[2] is not None else x.get("st_all")
        x["series_days"] = list(x.get("series_codes") or []) + ([(today_m or {}).get(x["toban"])] if (today_m or {}).get(x["toban"]) else [])
        rk = (ranks or {}).get(x["toban"])
        x["srank"] = [rk[0], rk[1]] if rk else None
        x["fem"] = 1 if fem and x["toban"] in fem else 0            # 女子レーサー(公式の選手期別成績から)
        if cat:
            x["csg"] = ((racers.get(x["toban"]) or {}).get("g") or {}).get(cat) or {}   # このレースの区分(女子戦・SG など)での、コースごとの[走数, 1着, 2着, 3着]
    SEARCH.setdefault(ymd, {"venues": {}, "races": []})["races"].append({
        "c": code, "no": race["no"], "nm": race["name"], "dl": dl_now, "ds": race.get("distance"),
        "al": {k: v for k, v in (alerts or {}).items() if v},
        "e": [{"w": x["waku"], "t": x["toban"], "n": x["name"], "k": x.get("cls"), "f": x.get("fp") or 0, "fm": x.get("fem") or 0,
               "g": (x.get("mg") or {}).get("grade"), "z": (x.get("mg") or {}).get("z"), "sp": (x.get("mg") or {}).get("sp") or 0} for x in ents]})
    rel = "../" * depth
    names = "".join(f'<li><span class="waku w{x["waku"]}">{x["waku"]}</span> {e(x["name"])}{"<span class=\"fem\">♥</span>" if x.get("fem") else ""} <span class="small">{e(x["cls"])} {e(x["branch"])}</span></li>' for x in ents)
    card = ('<section><h2>出走表</h2><div id="cardBox"><ul class="plain">' + names + "</ul></div>"
            '<p class="note">赤はその項目で1位、青は2位の艇です。黄色の印はフライング(F)と、今節の失格・出遅れ・欠場です。</p></section>')
    before_html = ('<section aria-labelledby="h-before"><div class="row-head"><h2 id="h-before">直前情報</h2><span class="sub" id="beforeAt"></span></div>'
                   '<div id="beforeBox"><p class="wait">展示航走のあと(締切の10〜15分前ごろ)に自動で入ります。</p></div>'
                   '<p class="note">赤はその項目で1位、青は2位の艇です。推定の数字は、過去のレースのタイムと展示タイムから計算した目安です。</p></section>'
                   '<section class="ex1sec"><div id="ex1Box"></div></section>'
                   '<section class="gated" aria-labelledby="h-st"><h2 id="h-st">スタートの見立て</h2><p class="wait">スタート展示のあとに出します。</p><div class="gbody" hidden>'
                   '<div id="stBox"></div><ul class="points" id="stNotes"></ul></div></section>')
    view = ('<section class="t1" aria-labelledby="h-t1"><div class="row-head"><h2 id="h-t1">1周1マーク展開シミュレーション</h2></div>'
            '<p class="wait" id="t1Wait">スタート展示の進入とSTが出たら、それをもとに作ります。</p>'
            '<h3 class="t1hl" id="t1Head" hidden aria-live="polite"></h3>'
            '<div id="t1Body" hidden><canvas id="t1view" role="img" aria-label="スタートから全艇が1周1マークを回り切るまでを上空から見たシミュレーション"></canvas>'
            '<div class="ctrl"><button class="primary" id="t1Replay" type="button">もう一度再生</button>'
            '<button id="t1Pause" type="button">一時停止</button>'
            '<button id="t1Slow" type="button" aria-pressed="false">ゆっくり再生</button>'
            '<button id="t1Save" type="button">動画を保存</button></div>'
            '<div class="ctrl" id="t1Out" hidden></div><p class="note" id="t1Msg" aria-live="polite"></p>'
            '<p class="sub nvnote" id="t1Note" hidden></p>'
            '<div class="pats" id="t1Pats" role="group" aria-label="決着パターン"></div></div></section>')
    navi = ('<section class="navi" aria-labelledby="h-navi"><div class="row-head"><h2 id="h-navi">展開ナビ</h2><span class="sub" id="nvState"></span></div>'
            '<p class="sub">軸にする艇と、その艇の勝ち方(戦術)を選ぶと、2着・3着に考えられる展開を、起こりやすさとデータと一緒に並べます。</p>'
            '<div class="nvsel"><div class="nvl">軸艇</div><div class="nvboats" id="nvBoats" role="group" aria-label="軸艇"></div>'
            '<div class="nvl">戦術</div><div class="nvtacs" id="nvTacs" role="group" aria-label="戦術"></div></div>'
            '<div id="nvOut"><p class="wait">計算しています…</p></div></section>')
    analysis = ('<section class="gated"><h2>展開の見立て</h2><p class="wait">スタート展示のあとに出します。</p><div class="gbody" hidden>'
                '<p class="sub" id="scenLead"></p><div class="scen" id="scen"></div><div class="p2" id="scen2"></div></div></section>'
                '<section class="gated"><h2>道中のポイント</h2><p class="wait">スタート展示のあとに出します。</p><div class="gbody" hidden>'
                '<ul class="points" id="points"></ul><div class="boats" id="boats"></div></div></section>'
                '<section class="gated"><div class="row-head"><h2>解説文</h2><button id="btnCopy" type="button">コピー</button></div>'
                '<p class="wait">スタート展示のあとに出します。</p><div class="gbody" hidden><textarea id="post" aria-label="解説文"></textarea>'
                '<p class="note" id="copyMsg" aria-live="polite"></p></div></section>')
    # 結果の詳細(翌日の競走成績ファイルから)
    res_html = ""
    if result:
        rr = sorted(result["entries"], key=lambda x: (x["rank"] or 9, x["waku"]))
        sts = [x["st"] for x in result["entries"] if x.get("st") is not None and not x.get("flying")]
        top_st = min(sts) if sts else None
        trs = "".join(
            f'<tr><td class="num">{x["rank"] or ("欠場" if str(x.get("status") or "").startswith("K") else e(x["status"]))}</td><td><span class="waku w{x["waku"]}">{x["waku"]}</span></td>'
            f'<td>{e(x["name"])}{"<span class=\"fem\">♥</span>" if fem and x.get("toban") in fem else ""}</td><td class="num">{x["course"] or "—"}</td>'
            f'<td class="num{" hi" if x.get("st") is not None and x["st"] == top_st and not x.get("flying") else ""}">'
            f'{("F" if x.get("flying") else "") + f1(x.get("st"), 2)}</td><td class="num">{f1(x.get("ex"), 2)}</td>'
            f'<td class="num">{e(x.get("time") or "—")}</td></tr>' for x in rr)
        rv = review_text(vname, race["no"], result, url)
        res_html = (f'<section><div class="row-head"><h2>結果の詳細</h2><span class="tag">決まり手 {e(result.get("kimarite") or "—")}</span>'
                    f'<span class="sub">{e(result.get("weather"))}・風 {e(result.get("wind_dir"))}{e(result.get("wind"))}m・波 {e(result.get("wave"))}cm</span></div>'
                    '<div class="gridt-wrap"><table class="gridt"><thead><tr><th class="num">着</th><th>枠</th><th>選手</th><th class="num">進入</th>'
                    f'<th class="num">ST</th><th class="num">展示</th><th class="num">タイム</th></tr></thead><tbody>{trs}</tbody></table></div>'
                    '<div class="row-head"><h2>回顧文</h2><button id="btnCopyR" type="button">コピー</button></div>'
                    f'<textarea id="review" aria-label="回顧文">{e(rv)}</textarea><p class="note" id="copyMsgR" aria-live="polite"></p></section>')
    # 場
    p1 = vinfo["place"][0][0] if vinfo["place"] else 0
    facts = " ".join(f'<span class="tag">{e(t)}</span>' for t in [vinfo.get("pref"), vinfo.get("water") and "水質:" + vinfo["water"],
                                                                     vinfo.get("tide") and "干満差:" + vinfo["tide"], tier(p1)] if t)
    venue_html = ('<section><h2>レース場の特徴</h2>' + f'<div class="meta">{facts}</div>'
                  + place_kim_tables(vinfo["place"], vinfo["kimarite"]) + f'<p class="note">単位:%。{e(vinfo["src"])}</p></section>')
    if cat and cat_tbl:
        venue_html += (f'<section class="catsec"><h2>{e(cat)}のコース別成績 <small class="h2s">全国・直近1年</small></h2>'
                       + place_kim_tables(cat_tbl["place"], cat_tbl["kimarite"]) +
                       f'<p class="note">単位:%。全国の{e(cat)}({cat_tbl["races"]}レース)の、コースごとの1着・2着・3着の割合と、1着になったときの決まり手の割合(当サイト集計)。</p></section>')
    # ナビ
    chips = "".join(f'<a class="chip{" on" if r["no"] == race["no"] else ""}" href="{r["no"]:02d}.html">{r["no"]}R</a>' for r in vprog["races"])
    head = (f'<nav class="crumb"><a href="{rel}index.html">今日のレース</a>›<a href="{rel}{ymd}/index.html">{jdate(d)}</a>›'
            f'<a href="index.html">{e(vname)}</a></nav>'
            f'<h1>{e(vname)} {race["no"]}R {e(race["name"])}</h1>'
            f'<div class="meta"><span class="tag" id="dlTag">締切 {e(dl_now)}{"(変更)" if dl_now != dl_prog else ""}</span><span class="tag">{race["distance"]}m</span>'
            + cat_tag(cat) + (f'<span class="tag">第{vprog["day"]}日</span>' if vprog.get("day") else "")
            + f'<span class="sub">{e(vprog.get("title", ""))}</span></div>'
            f'<div class="alerts" id="alerts">{badges(alerts or {})}</div><div class="chips">{chips}</div>')
    data = {"venue": {k: vinfo[k] for k in ("code", "name", "place", "kimarite")}, "alerts": alerts or {}, "cat": cat,
            "race": {"date": d.isoformat(), "ymd": ymd, "no": race["no"], "name": race["name"], "deadline": dl_now,
                     **({"deadline0": dl_prog} if dl_now != dl_prog else {})}, "entries": ents,
            "vt": tables[0], "nt": tables[1]}
    if result:
        data["result"] = {"kimarite": result.get("kimarite"), "wind": result.get("wind"), "wind_dir": result.get("wind_dir"),
                          "entries": [{k: x.get(k) for k in ("waku", "course", "st", "flying", "rank", "status", "ex")}
                                      for x in result["entries"]]}
    if before:
        data["before"] = before          # 直前情報(scripts/live.py)
    if res_live:
        data["live"] = res_live          # レース直後の結果(scripts/live.py)
    og = (vlive.get("orig") or {}).get(no)
    if og:
        data["orig"] = og                # 場のオリジナル展示データ(一周・まわり足・直線。scripts/live.py)
    if pace:
        data["pace"] = pace              # 推定タイム(一周・まわり足)と展示タイム1位の1着率(scripts/pace.py)
    tabs = ('<nav class="tabs" role="tablist" aria-label="このレースの情報">'
            '<button type="button" role="tab" data-tab="card">出走表</button><button type="button" role="tab" data-tab="tac">戦法</button>'
            '<button type="button" role="tab" data-tab="before">直前<br class="tb">情報</button>'
            '<button type="button" role="tab" data-tab="odds">オッズ</button>'
            '<button type="button" role="tab" data-tab="t1">1S1M<br class="tb">展開</button><button type="button" role="tab" data-tab="navi">展開<br class="tb">ナビ</button>'
            '<button type="button" role="tab" data-tab="data">データ</button></nav>')
    tac_html = ('<section class="tac" aria-labelledby="h-tac"><div class="row-head"><h2 id="h-tac">コース別の戦法</h2><span class="sub">直近1年</span></div>'
                '<p class="sub">このレースの6人の、今日のコースでの戦い方です。1着の決まり手だけでなく、2着・3着になったときの動きと、'
                'その選手がそのコースにいたときに1コースの逃げや外の艇の差しがどれだけ決まったかも出します。</p>'
                '<div id="tacNow"><p class="wait">計算しています…</p></div><ul class="points" id="tacNotes"></ul></section>'
                '<section class="tac" aria-labelledby="h-tac2"><h2 id="h-tac2">選手ごとの全コースの戦法</h2>'
                '<div class="tacsel" id="tacBoats" role="group" aria-label="選手"></div><div id="tacAll"></div>'
                '<p class="note">2着・3着の時の動きは、公式の記録が1着の決まり手だけなので、1着の艇のコース・決まり手と、スタートの差から推定しています'
                '(差し: 勝った艇の内の筋を回った・捲り: スタートで内より先に出て外から攻めた・捲り差し: 間の艇の前を横切って内へ切り込んだ・残し: 外の艇に先に回られたが残した・道中: 2マーク以降で決まった)。'
                '「内より先に出た」はスタートで内側のどの艇よりも0.03秒以上早かった割合、「1コースの逃げ」はその選手がそのコースにいたレースで1コースの艇が逃げた割合(1コースの選手は自分の逃げ率)、'
                '「外の差し・捲り差し」はその選手より外の艇が差し・捲り差しで1着になった割合です。小さい数字は全国の割合。▲▼は、15走以上で全国と大きく違うところです。</p></section>')
    odds_html = ('<section class="odds" aria-labelledby="h-odds"><div class="row-head"><h2 id="h-odds">オッズ</h2><span class="sub" id="odAt"></span></div>'
                 '<div class="chips odsel" id="odKinds" role="group" aria-label="券種">'
                 '<button type="button" class="chip on" data-k="3t">3連単</button><button type="button" class="chip" data-k="2t">2連単・2連複</button>'
                 '<button type="button" class="chip" data-k="tf">単勝・複勝</button></div>'
                 '<div id="odBox"><p class="wait">締切の15分前から、1分ごとに公式サイトのオッズを表示します。</p></div></section>')
    body = (head + result_banner(res_live, result) + tabs
            + '<div class="pane" id="pane-card">' + card + "</div>"
            + '<div class="pane" id="pane-tac">' + tac_html + "</div>"
            + '<div class="pane" id="pane-before">' + before_html + "</div>"
            + '<div class="pane" id="pane-odds">' + odds_html + "</div>"
            + '<div class="pane" id="pane-t1">' + view + analysis + "</div>"
            + '<div class="pane" id="pane-navi">' + navi + "</div>"
            + '<div class="pane" id="pane-data">' + venue_html + res_html + "</div>")
    first = ents[0]
    c1 = first["cs"].get("1")
    c1txt = f"1コース1着率{pct(c1['w1'], c1['n'])}%({c1['n']}走)" if c1 and c1["n"] else f"全国勝率{f1(first['rate'], 2)}"
    desc = (f"{vname}{race['no']}R {race['name']}({jdate(d)} {race['deadline']}締切)。1号艇 {first['name']}({first['cls']}) {c1txt}。"
            "出走表・直前情報・1周1マークの展開シミュレーション。")
    title = f"{vname} {race['no']}R {race['name']} 出走表と展開 {d.month}/{d.day} | {SITE_NAME}"
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    script = (f'<script type="application/json" id="race-data">{blob}</script>'
              f'<script src="{rel}assets/model.js"></script><script src="{rel}assets/params.js"></script>'
              f'<script src="{rel}assets/turn1.js"></script><script src="{rel}assets/race.js"></script><script src="{rel}assets/odds.js"></script>')
    write(path, page(title, desc, body, depth, path, script, RACE_NOTES))
    return path


def build_venue(d, code, vprog, vinfo, racers, results_v, vlive=None, al_map=None):
    ymd = d.strftime("%Y%m%d")
    vname = vinfo["name"]
    rows = []
    for race in vprog["races"]:
        x = racer_view(race["entries"][0], racers)
        c1 = x["cs"].get("1")
        c1txt = f'{pct(c1["w1"], c1["n"])}%<span class="small">{c1["n"]}走</span>' if c1 and c1["n"] else "—"
        lr = ((vlive or {}).get("result") or {}).get(str(race["no"]))
        res = (results_v or {}).get(race["no"])
        tri = (lr or {}).get("tri")
        if not tri and res:
            fin = sorted([y for y in res["entries"] if y.get("rank")], key=lambda y: y["rank"])
            tri = [y["waku"] for y in fin[:3]] if len(fin) >= 3 else None
        restxt = ('<span class="tri small-tri">' + "-".join(f'<span class="waku w{w}">{w}</span>' for w in tri) + "</span>"
                  + (f'<span class="small">{lr["pay"] / 100:.1f}倍</span>' if lr and lr.get("pay") else "")) if tri else ""
        dl_now = deadline_of(race, vlive)
        rows.append(f'<tr data-deadline="{e(dl_now)}" data-no="{race["no"]}"><td><a class="rno" href="{race["no"]:02d}.html">{race["no"]}R</a></td>'
                    f'<td class="num"><span class="dl{" moved" if dl_now != race["deadline"] else ""}">{e(dl_now)}</span><span class="small cd"></span></td>'
                    f'<td><a href="{race["no"]:02d}.html">{e(race["name"])}</a>' + (f'<span class="small">{race["distance"]}m</span>' if race["distance"] != 1800 else "")
                    + (f'<span class="alrow">{badges((al_map or {}).get(race["no"]), True)}</span>' if (al_map or {}).get(race["no"]) and any((al_map or {}).get(race["no"]).values()) else "")
                    + f'</td><td class="res">{restxt}</td><td><span class="waku w1">1</span> {e(x["name"])} <span class="small">{e(x["cls"])}</span></td>'
                    f'<td class="num">{c1txt}</td></tr>')
    p1 = vinfo["place"][0][0] if vinfo["place"] else 0
    body = (f'<nav class="crumb"><a href="../../index.html">今日のレース</a>›<a href="../index.html">{jdate(d)}</a></nav>'
            f'<h1>{e(vname)} {jdate(d)}</h1><div class="meta">' + cat_tag(venue_cat(ymd, code)) + (f'<span class="tag">第{vprog["day"]}日</span>' if vprog.get("day") else "")
            + f'<span class="tag">{tier(p1)}(1コース1着率{f1(p1)}%)</span><span class="sub">{e(vprog.get("title", ""))}</span></div>'
            f'<section><h2>レース一覧</h2><div class="scroll"><table class="race-list" data-date="{d.isoformat()}" data-live="{ymd}/{code}.json" data-code="{code}" data-dlurl="{ymd}/dl.json"><thead><tr><th>R</th><th class="num">締切</th><th>レース</th>'
            '<th>結果</th><th>1号艇</th><th class="num">1号艇の<br>1コース1着率</th></tr></thead><tbody>' + "".join(rows)
            + "</tbody></table></div></section>")
    title = f"{vname} {jdate(d)} 出走表・レース一覧 | {SITE_NAME}"
    desc = f"{vname}の{jdate(d)}の全レースの出走表、選手のコース別成績、展開の見立て。{vprog.get('title', '')}"
    notes = ["1号艇の1コース1着率は、直近1年に1コースに入ったときの成績です。締切までの時間は、この端末の時計で数えています。"]
    write(f"{ymd}/{code}/index.html", page(title, desc, body, 2, f"{ymd}/{code}/", '<script src="../../assets/day.js"></script>', notes))


GRADES_ALL: dict = {}   # 開催のグレード(data/grades.json。main で読み込む)


def venue_cat(ymd: str, code: str):
    """開催のグレードの表示名(オールレディース・ヴィーナスシリーズは「女子戦」)。"""
    g = (GRADES_ALL.get(ymd) or {}).get(code)
    if not g:
        return None
    return "女子戦" if ("lady" in g or "venus" in g) else g[0]


def day_cards(d, prog, depth_prefix, alerts=None, live=None):
    """開催場のカード。締切の時刻を持たせておき、ページを開いたときに次のレースが近い順に並べ替える(day.js)。
    締切は公式の今の時刻(遅れて変わっていればそちら)。ページを開いている間は、day.js が dl.json を読んで合わせ直す。"""
    ymd = d.strftime("%Y%m%d")
    items = []
    for code, v in prog["venues"].items():
        lv = (live or {}).get(code)
        first, last = v["races"][0]["deadline"], v["races"][-1]["deadline"]
        dls = ",".join(f'{r["no"]}-{deadline_of(r, lv)}' for r in v["races"] if deadline_of(r, lv))
        am = (alerts or {}).get(code, {})
        als = ",".join(f"{no}:{k}{lv}" for no, a in sorted(am.items()) for k, lv in a.items() if lv)
        items.append((first, f'<a class="card vcard" href="{depth_prefix}{ymd}/{code}/index.html" data-dl="{dls}" data-al="{als}" data-code="{code}">'
                             f'<span class="vrow"><span class="v">{e(VENUES.get(code, code))}</span>{cat_tag(venue_cat(ymd, code))}<span class="als"></span></span>'
                             f'<span class="next" aria-live="polite"></span>'
                             f'<span class="t">{e(v.get("title", ""))}</span><span class="sub">'
                             + (f'第{v["day"]}日 ・ ' if v.get("day") else "") + f'{len(v["races"])}R ・ 締切 {e(first)}〜{e(last)}</span></a>'))
    items.sort()
    return f'<div class="cards" data-date="{d.isoformat()}" data-dlurl="{ymd}/dl.json">' + "".join(x[1] for x in items) + "</div>"


DAY_NOTES = ["開催場は、次のレースの締切が近い順に並べています(この端末の時計で数え、開いている間は1分ごとに並べ直します)。締切まで10分を切ったレースは赤で示します。",
             "場の名前の横の警戒アラートは、次のレースのものです。イン飛び警戒は、1コースの選手の1コース1着率と2コースの選手の逃がし率が、どちらも40%以下で注意報(緑)、33%以下で警報(黄)、25%以下で特別警報(赤)。"
             "カドまくり警戒は、4コースの選手が4コースでよく捲って勝っていて(捲りの1着が走数の8%以上)、予想STが1〜3コースのどの艇よりも早いとき。差が0.00秒以上で注意報(ピンク)、0.01秒以上で警報(紫)、0.02秒以上で特別警報(オレンジ)。"
             "展示の前の、枠なりの進入での計算です(レースのページでは、スタート展示のあとに計算し直します)。"]


def build_day(d, prog, dates, alerts=None, live=None):
    ymd = d.strftime("%Y%m%d")
    nav = " ".join(f'<a class="chip{" on" if x == d else ""}" href="../{x:%Y%m%d}/index.html">{x.month}/{x.day}</a>' for x in dates)
    body = (f'<nav class="crumb"><a href="../index.html">今日のレース</a></nav><h1>{jdate(d)}の開催</h1>'
            f'<div class="chips">{nav}</div><section><h2>開催場</h2>{day_cards(d, prog, "../", alerts, live)}</section>')
    write(f"{ymd}/index.html", page(f"{jdate(d)}のボートレース開催一覧 | {SITE_NAME}",
                                    f"{jdate(d)}に開催のボートレース全場の出走表と展開の見立て。", body, 1, f"{ymd}/",
                                    '<script src="../assets/day.js"></script>', DAY_NOTES))


def build_index(today, progs, dates, alerts_by_day=None):
    show = today if today in progs else max(progs)
    nav = " ".join(f'<a class="chip{" on" if x == show else ""}" href="{x:%Y%m%d}/index.html">{x.month}/{x.day}</a>' for x in dates)
    label = "今日" if show == today else ("明日" if show == today + dt.timedelta(days=1) else "")
    body = (f'<h1>{label}{"の" if label else ""}レース {jdate(show)}</h1>'
            '<p class="lead">全国のボートレースの出走表を毎日自動で更新し、直前情報と1周1マークの展開シミュレーションを出しています。買い目は出しません。</p>'
            f'<div class="chips">{nav}</div><section><h2>開催場</h2>{day_cards(show, progs[show], "", (alerts_by_day or {}).get(show))}</section>')
    write("index.html", page(f"{SITE_NAME} | ボートレースの出走表と展開の見立て",
                             "全国のボートレースの出走表を毎日自動更新。直前情報と1周1マークの展開シミュレーション。", body, 0, "",
                             '<script src="assets/day.js"></script>', DAY_NOTES))


def search_venue(vname: str, vprog: dict, vnext: dict | None) -> dict:
    """検索用: 場の今節の段階(予選・準優・優勝戦)と、選手ごとの今節成績(準優の勝負駆けを出すため)。"""
    names = " ".join(r["name"] for r in vprog.get("races", []))
    phase = "final" if "優勝" in names and "準優" not in names else "junyu" if "準優" in names else "yosen"
    last = None                            # 明日の番組がまだないとき(ナイターの場は夜に足される)は分からない
    if vnext is not None:
        nn = " ".join(r["name"] for r in vnext.get("races", []))
        last = phase == "yosen" and "準優" in nn
    roster = {}
    for race in vprog.get("races", []):
        for x in race["entries"]:
            roster.setdefault(x["toban"], {"n": x.get("name"), "s": list(x.get("series") or [])})
    return {"name": vname, "day": vprog.get("day"), "title": vprog.get("title", ""), "phase": phase, "last": last, "roster": roster}


def write_search(dates, today):
    """日付ごとの検索用のデータ({ymd}/search.json)と、レース検索のページ。見立て(1号艇の逃げなど)は node で足す(scripts/searchidx.js)。"""
    for d in dates:
        ymd = f"{d:%Y%m%d}"
        blob = SEARCH.get(ymd)
        if blob:
            blob["date"] = d.isoformat()
            blob["ymd"] = ymd
            write(f"{ymd}/search.json", json.dumps(blob, ensure_ascii=False, separators=(",", ":")))
    try:
        subprocess.run(["node", str(ROOT / "scripts" / "searchidx.js")], cwd=ROOT, timeout=600, check=False)
    except Exception as ex:  # noqa: BLE001  見立てが足せなくても、検索のページは出す
        print("検索用の見立てを足せませんでした:", ex)
    tabs = "".join(f'<button type="button" class="chip{" on" if d == today else ""}" data-ymd="{d:%Y%m%d}">'
                   f'{"今日" if d == today else "明日" if d == today + dt.timedelta(days=1) else ""} {d.month}/{d.day}</button>' for d in dates)
    body = ('<h1>レース検索</h1><p class="lead">条件を選ぶと、当てはまるレースが締切の順に並びます。「直前」の条件は、スタート展示のあとに取り込んだレースから探します。</p>'
            f'<div class="chips" id="sDates">{tabs}</div>'
            '<section class="sform"><div id="sConds" class="sconds"></div>'
            '<div class="srow"><input type="search" id="sName" placeholder="選手名・登番" autocomplete="off" aria-label="選手名・登番">'
            '<select id="sVenue" aria-label="場"><option value="">すべての場</option></select></div>'
            '<div class="srow"><label class="sw"><input type="checkbox" id="sUpcoming" checked> これからのレースだけ</label>'
            '<span class="sw"><label><input type="radio" name="sMode" value="and" checked>すべて満たす</label>'
            '<label><input type="radio" name="sMode" value="or">どれか満たす</label></span>'
            '<button type="button" id="sClear">条件を外す</button></div>'
            '<button type="button" id="sJump" class="sjump" hidden></button></section>'
            '<section><h2 id="sCount">レース</h2><div id="sList" class="slist"><p class="sub">読み込み中…</p></div></section>')
    notes = ["準優の勝負駆けは、今節の着順を点数(1着10点・2着8点・3着6点・4着4点・5着2点・6着1点)にした得点率で、今の18位をボーダーの目安にした推定です。"
             "残り1走の選手は、その1走で何着以内ならボーダーの目安に届くかを出しています。場によって点数の数え方や準優の枠の数が違うことがあります。",
             "モーター評価は、展示タイムが出ていればそれも加えて計算し直します。チルト・進入・展示タイム・部品交換・風は、取り込んだ直前情報から調べます。",
             "逃げの見立ては、ページを作ったときの計算です(展示の前のものは枠なり・ふだんのSTとして計算)。"]
    write("search.html", page(f"レース検索 | {SITE_NAME}", "イン飛び・カドまくりの警報、準優の勝負駆け、モーター評価S、チルトを跳ねた選手などで、今日のレースを探す。",
                              body, 0, "search.html", '<script src="assets/search.js"></script>', notes))


# 見立ての変更の記録(成績のページに出す)
MODEL_CHANGES = [
    ("2026-10-29", "見立てにレースの種類(優勝戦・ドリーム戦など)と、選手ごとのコースでのSTのくせを入れ、本線を「1着の見込みが一番高い艇」にしました。"),
]
REC_ITEMS = [   # (キー, 名前, 説明)
    ("boat", "本線の艇が1着", "本線(1着になる見込みが一番高い艇)が、実際に1着になった割合。"),
    ("pat", "本線の決着パターンがそのまま", "本線の艇と決まり手(逃げ・差し・捲りなど)の両方が当たった割合。"),
    ("top3", "上位3つの決着パターンに入った", "実際の決着(1着のコースと決まり手)が、見立ての起こりやすい上位3つに入っていた割合。"),
    ("ex2", "本線の並びで1-2着がそのまま", "本線の決着パターンのときの並び(2着〜6着の見立て)で、1着と2着が実際と同じだった割合。"),
    ("ex3", "本線の並びで1-2-3着がそのまま", "同じく、1着・2着・3着が実際と同じだった割合。"),
    ("nnb", "1号艇以外が本線のとき、その艇が1着", "本線が1号艇(1コース)以外になったレースで、その艇が1着になった割合。"),
]


def record_days() -> list:
    """毎晩の答え合わせ(data/learn)から、日ごとの成績。サイトが締切前に記録した見立て(data/live/*/pred.json)と結果の比べ。"""
    out = []
    for p in sorted((DATA / "learn").glob("*.json")):
        x = load_json(p, {}) or {}
        L = x.get("lead") or {}
        if not L.get("races") or L.get("one") is None or L["races"] < 30:
            continue
        a = x.get("anim") or {}
        out.append({"d": x.get("date") or f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}", "n": L["races"], "boat": L["boat"], "one": L["one"],
                    "pat": L["pattern"], "top3": x.get("top3"), "ex2": L.get("ex2"), "ex3": L.get("ex3"), "nn": L.get("non1") or 0,
                    "nnb": L.get("non1_boat"), "nno": L.get("non1_one"),
                    "anim": {k: a.get(k) for k in ("races", "lead", "kind", "hit2", "hit3")} if a.get("races") else None})
    return out


def record_sum(days: list) -> dict:
    """日ごとの成績を、レースの数で重みを付けてまとめる(1号艇以外の本線は、そのレースの数で)。"""
    n = sum(x["n"] for x in days)
    out = {"n": n, "days": len(days)}
    if not n:
        return out
    for k in ("boat", "one", "pat", "top3", "ex2", "ex3"):
        v = [(x[k], x["n"]) for x in days if x.get(k) is not None]
        out[k] = round(sum(a * b for a, b in v) / sum(b for _, b in v), 1) if v else None
    nn = sum(x["nn"] for x in days if x.get("nnb") is not None)
    out["nn"] = nn
    out["nnb"] = round(sum(x["nnb"] * x["nn"] for x in days if x.get("nnb") is not None) / nn, 1) if nn else None
    out["nno"] = round(sum(x["nno"] * x["nn"] for x in days if x.get("nno") is not None) / nn, 1) if nn else None
    return out


def build_record():
    """見立ての成績のページ(seiseki.html)。"""
    days = record_days()
    title = f"見立ての成績 | {SITE_NAME}"
    desc = "水面ノートの見立て(本線)が実際にどれだけ当たったかの記録。毎晩、前の日の分を足します。"
    if not days:
        write("seiseki.html", page(title, desc, "<h1>見立ての成績</h1><section><p>まだ記録がありません。</p></section>", 0, "seiseki.html"))
        return
    last7 = days[-7:]
    S7, SA = record_sum(last7), record_sum(days)
    def md(iso):
        return f"{int(iso[5:7])}/{int(iso[8:10])}"
    def pc(v):
        return "—" if v is None else f"{v:.0f}<small>%</small>"
    span7 = f"{md(last7[0]['d'])}〜{md(last7[-1]['d'])}・{S7['n']:,}レース"
    spanA = f"{md(days[0]['d'])}〜{md(days[-1]['d'])}・{SA['n']:,}レース"
    tiles = []
    for k, name, _ in REC_ITEMS:
        if k == "boat":
            sub = f'<span class="cmp">毎回1号艇(1コース)と言った場合 <b>{pc(S7.get("one"))}</b></span>'
        elif k == "nnb":
            sub = (f'<span class="cmp">そのとき1号艇が1着 <b>{pc(S7.get("nno"))}</b>・{S7.get("nn", 0)}レース</span>')
        else:
            sub = ""
        tiles.append(f'<div class="rtile"><div class="rl">{e(name)}</div><div class="rv">{pc(S7.get(k))}</div>{sub}'
                     f'<div class="ra">これまで {pc(SA.get(k))}</div></div>')
    # 直近7日の表(列が日付)
    heads = "".join(f"<th>{md(x['d'])}" + ("<small>見立て更新</small>" if any(x["d"] == c[0] for c in MODEL_CHANGES) else "") + "</th>" for x in last7)
    def row(label, vals):
        return f'<tr><th scope="row">{label}</th>' + "".join(f"<td>{v}</td>" for v in vals) + "</tr>"
    def p0(v):
        return "—" if v is None else f"{v:.0f}%"
    rows = [row("レース", [str(x["n"]) for x in last7]),
            row("本線の艇が1着", [f"<b>{p0(x['boat'])}</b>" for x in last7]),
            row("毎回1号艇なら", [p0(x["one"]) for x in last7]),
            row("決着パターン", [p0(x["pat"]) for x in last7]),
            row("上位3つ", [p0(x["top3"]) for x in last7]),
            row("1-2着", [p0(x["ex2"]) for x in last7]),
            row("1-2-3着", [p0(x["ex3"]) for x in last7]),
            row("1号艇以外が本線", [f'{p0(x["nnb"])}<small>{x["nn"]}R</small>' if x["nn"] else "—" for x in last7])]
    t7 = '<div class="vt-wrap"><table class="vt rect"><thead><tr><th class="corner"></th>' + heads + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    # 全期間の日ごと(新しい順)
    allrows = "".join(f"<tr><td>{md(x['d'])}</td><td>{x['n']}</td><td><b>{p0(x['boat'])}</b></td><td>{p0(x['one'])}</td><td>{p0(x['top3'])}</td><td>{p0(x['ex2'])}</td></tr>"
                      for x in reversed(days))
    tall = ('<div class="gridt-wrap"><table class="gridt rall"><thead><tr><th>日付</th><th>レース</th><th>本線の艇</th><th>毎回1号艇</th><th>上位3つ</th><th>1-2着</th></tr></thead>'
            f"<tbody>{allrows}</tbody></table></div>")
    # 1周1マークの映像の再現度
    an = [x for x in days if x.get("anim")]
    anim_html = ""
    if an:
        ar = "".join(f"<tr><td>{md(x['d'])}</td><td>{x['anim']['races']}</td><td>{p0(x['anim']['lead'])}</td><td>{p0(x['anim']['kind'])}</td>"
                     f"<td>{p0(x['anim']['hit2'])}</td><td>{p0(x['anim']['hit3'])}</td></tr>" for x in reversed(an))
        anim_html = ('<section><details><summary><h2>1周1マークの映像の再現度</h2></summary>'
                     '<p class="sub">終わったレースの実際の進入・ST・決まり手・着順を映像の仕組みに入れたとき、映像の先頭・決まり手・2着・3着が実際と同じになった割合です(映像の動き方の確かめ)。</p>'
                     '<div class="gridt-wrap"><table class="gridt rall"><thead><tr><th>日付</th><th>レース</th><th>先頭</th><th>決まり手</th><th>2着</th><th>3着</th></tr></thead>'
                     f"<tbody>{ar}</tbody></table></div></details></section>")
    chart = {"days": [{"d": x["d"], "boat": x["boat"], "one": x["one"], "n": x["n"]} for x in days]}
    notes = "".join(f"<li><b>{e(name)}</b>: {e(txt)}</li>" for _, name, txt in REC_ITEMS)
    changes = "".join(f"<li><b>{md(d)}</b>: {e(t)}</li>" for d, t in MODEL_CHANGES)
    body = ('<h1>見立ての成績</h1>'
            '<p class="lead">サイトが締切前(スタート展示のあと)に出した見立てと、実際の結果を比べた記録です。毎晩、前の日の分を足します。</p>'
            f'<section class="rsec"><div class="row-head"><h2>直近7日</h2><span class="sub">{span7}</span></div><div class="rtiles">{"".join(tiles)}</div>'
            f'<p class="note">「これまで」は記録を始めてからの全部({spanA})。</p></section>'
            '<section class="rsec"><h2>日ごとの推移</h2>'
            '<div class="rlegend" aria-hidden="true"><span class="k main"></span>本線の艇が1着<span class="k base"></span>毎回1号艇(1コース)と言った場合</div>'
            '<div id="recChart" class="rchart" role="img" aria-label="日ごとの、本線の艇が1着になった割合と、1号艇(1コース)が1着になった割合の折れ線グラフ。数字は下の表にもあります。"></div>'
            f"{t7}"
            f'<details class="rdet"><summary>全部の日を見る({len(days)}日)</summary>{tall}</details></section>'
            f'<section><h2>見方</h2><ul class="points">{notes}</ul>'
            '<p class="note">本線の並びは、本線の決着パターンになったときの2着〜6着の見立てです。見立ては締切前に最後に記録したもので、欠場のあるレースなど見立てを出さなかったレースは数えていません。</p></section>'
            f'<section><h2>見立ての変更</h2><ul class="points">{changes}</ul></section>'
            + anim_html)
    blob = json.dumps(chart, ensure_ascii=False).replace("</", "<\\/")
    script = f'<script type="application/json" id="rec-data">{blob}</script><script src="assets/record.js"></script>'
    write("seiseki.html", page(title, desc, body, 0, "seiseki.html", script))


def build_about():
    body = ('<h1>このサイトについて</h1><section><p>水面ノートは、ボートレースの出走表と成績をデータで読み解く非公式のサイトです。'
            '毎日、公式が配布している番組表と競走成績のファイルを自動で取り込み、選手のコース別成績とレース場の特徴をまとめています。'
            'レースの当日は、締切の前後に BOAT RACE オフィシャルウェブサイトから直前情報と結果を取り込みます。</p>'
            '<p>見立てと1周1マークの展開シミュレーションは、過去の成績をもとにした目安です。</p></section>')
    write("about.html", page(f"このサイトについて | {SITE_NAME}", "水面ノートについて。データの出典と注意事項。", body, 0, "about.html"))


def load_live(d: dt.date) -> dict:
    """その日の直前情報・レース直後の結果(場ごと)。"""
    out = {}
    folder = DATA / "live" / f"{d:%Y%m%d}"
    if folder.exists():
        for p in folder.glob("[0-9][0-9].json"):
            out[p.stem] = load_json(p, {}) or {}
    return out


def build_date(d, progs, dates, cache, cats, model, stadiums, alerts_by_day, urls):
    """1日分のページ(開催一覧・場ごとのレース一覧・レースのページ)を作る。"""
    ctabs: dict = {}
    racers, vstats, nat = collect(d, cache, cats, ctabs)
    nt = course_table(nat)
    res_day = load_json(RESULTS / f"{d:%Y%m%d}.json", {}) or {}
    live_day = load_live(d)
    mraw = raw_scores(d, racers)
    mrates = motor_rates(d)
    P_pace = pacemod.build(d)
    sm = (model or {}).get("start")
    al_day = {}
    for code, vprog in progs[d]["venues"].items():
        al_day[code] = {race["no"]: race_alerts([racer_view(x, racers, code) for x in race["entries"]], sm, code, d.isoformat())
                        for race in vprog["races"]}
    alerts_by_day[d] = al_day
    build_day(d, progs[d], dates, al_day, live_day)
    urls.append(f"{d:%Y%m%d}/")
    nxt = progs.get(d + dt.timedelta(days=1))
    for code, vprog in progs[d]["venues"].items():
        vinfo = venue_info(code, vstats, stadiums)
        if not vinfo["place"]:
            continue
        SEARCH.setdefault(f"{d:%Y%m%d}", {"venues": {}, "races": []})["venues"][code] = search_venue(vinfo["name"], vprog, (nxt or {}).get("venues", {}).get(code))
        vlive = live_day.get(code, {})
        rv = {r["no"]: r for r in res_day.get("venues", {}).get(code, {}).get("races", [])}
        build_venue(d, code, vprog, vinfo, racers, rv, vlive, al_day.get(code))
        urls.append(f"{d:%Y%m%d}/{code}/")
        tables = (course_table(vstats.get(code)), nt)
        tm = today_marks(vlive, vprog)
        ranks = series_ranks(vprog, tm)
        motors = venue_grades(code, vprog, mraw)
        for race in vprog["races"]:
            cat = cats(d, code, race["entries"])
            urls.append(build_race(d, code, vprog, race, vinfo, racers, rv.get(race["no"]), tables,
                                   ranks=ranks, vlive=vlive, motors=motors, today_m=tm, alerts=al_day[code][race["no"]],
                                   pace=pacemod.for_race(P_pace, code, race["entries"]), mrates=mrates,
                                   cat=cat, cat_tbl=venue_table(ctabs.get(cat), 100) if cat else None, fem=cats.fem))


def build_review(d: dt.date, out) -> int:
    """終わった日のレースのページを、公開しない場所(out)に作る。公開するサイトは今日と明日だけなので、
    前の日の1周1マークの映像を実際の結果と比べる答え合わせ(scripts/learn_anim.js)は、こちらを読む。作ったレースの数を返す。"""
    prog = load_json(PROGRAM / f"{d:%Y%m%d}.json", None)
    if not prog or not prog.get("venues"):
        return 0
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    _OUT[0] = out
    try:
        cats = category_resolver()
        GRADES_ALL.clear()
        GRADES_ALL.update(cats.grades)
        urls: list = []
        build_date(d, {d: prog}, [d], {}, cats, load_json(DATA / "model.json", None), load_json(DATA / "stadiums.json", {}), {}, urls)
    finally:
        _OUT[0] = OUT
    return sum(1 for u in urls if u.endswith(".html"))


def main():
    SEARCH.clear()
    today = today_jst()
    stadiums = load_json(DATA / "stadiums.json", {})
    progs = {}
    for p in sorted(PROGRAM.glob("*.json")):
        d = parse_ymd(p.stem)
        if today - dt.timedelta(days=PAST_DAYS) <= d <= today + dt.timedelta(days=1):
            progs[d] = load_json(p, {})
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    for f in (SITE / "assets").iterdir():
        shutil.copy(f, OUT / "assets" / f.name)
    (OUT / ".nojekyll").write_text("")
    if not progs:
        write("index.html", page(SITE_NAME, "準備中", "<h1>準備中</h1><p>出走表のデータがまだありません。</p>", 0, ""))
        return
    dates = sorted(progs)
    cache: dict = {}
    urls = ["", "about.html", "seiseki.html"]
    # 見立てモデルの重み(scripts/fit.py が学習したもの)。ページから読めるように JS にして置く
    model = load_json(DATA / "model.json", None)
    (OUT / "assets" / "params.js").write_text(
        "window.SUIMEN_PARAMS = " + (json.dumps(model, ensure_ascii=False, separators=(",", ":")) if model else "null") + ";\n",
        encoding="utf-8")
    alerts_by_day = {}
    cats = category_resolver()                # レースの区分(開催のグレードと女子戦)と女子レーサー
    GRADES_ALL.clear()
    GRADES_ALL.update(cats.grades)
    for d in dates:
        build_date(d, progs, dates, cache, cats, model, stadiums, alerts_by_day, urls)
    build_index(today, progs, dates, alerts_by_day)
    build_about()
    build_record()
    write_search(dates, today)
    sm = "".join(f"<url><loc>{BASE_URL}{u}</loc></url>" for u in urls)
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}sitemap.xml\n")
    print(f"pages: {len(urls)} / dates: {[str(x) for x in dates]}")


if __name__ == "__main__":
    main()
