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
import tide as tidemod
from stats import VENUE_DAYS, category_resolver, collect, venue_table

SITE_NAME = "水面ノート"
# サイトのURL(canonical・OGP・サイトマップ)。独自ドメインにしたら、ここを書きかえる(試すときは環境変数 SITE_URL で上書き)
BASE_URL = os.environ.get("SITE_URL") or "https://suimennote.com/"
PAST_DAYS = 0          # 今日より前に何日分のページを残すか(終わった日のページは出さない。今日と明日だけ)
# ページが開いている間に読みに行く直前情報・結果・締切の変更・オッズの置き場所。
# DATA_BASE(Cloudflare R2 の公開URL。例 https://data.example.com/)を先に読み、空のとき・読めないときは GitHub から読む
DATA_BASE = os.environ.get("DATA_BASE", "https://data.suimennote.com/")
GSV = (os.environ.get("GOOGLE_SITE_VERIFICATION") or "").strip()   # Google Search Console の所有確認(HTML タグの content の値。リポジトリの変数に入れる)
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


SITE_NAME_URA = "裏水面ノート"
URA_NOTES = ["裏水面ノートは、荒れる(3連単が1万円以上の万舟になる)レースと、荒れるとしたらどの形かを探すためのモードです。"
             "当たる割合は表の本線よりずっと低く、配当の高さで当たりにくさを補う考え方です。荒れを狙えば回収率が上がるとは限りません(見立ての成績のページに、実際の当たり方と配当を出しています)。"]


# ページのアイコン(表: 昼の水面の青い玉、裏: 夜の赤い三日月)
ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='14' fill='%231478b8'/%3E"
        "%3Ccircle cx='12' cy='11' r='5' fill='%237fd3ff' opacity='.75'/%3E%3C/svg%3E")
ICON_URA = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230d0b12'/%3E"
            "%3Ccircle cx='15' cy='17' r='11' fill='%23ff5470'/%3E%3Ccircle cx='20' cy='12' r='9' fill='%230d0b12'/%3E%3C/svg%3E")


def page(title, desc, body, depth, path, scripts="", notes=None, mode="omote", alt=None, page_class=""):
    """1ページの枠。mode は "omote"(水面ノート)か "ura"(裏水面ノート)。alt はもう一方のモードの同じページ(サイトの一番上からの道筋)。"""
    rel = "../" * depth
    ura = mode == "ura"
    items = "".join(f"<li>{x}</li>" for x in (notes or []) + (URA_NOTES if ura else []) + BASE_NOTES)
    name = SITE_NAME_URA if ura else SITE_NAME
    home = f"{rel}ura/index.html" if ura else f"{rel}today.html"
    nav = (f'<a href="{home}">今日のレース</a><a href="{rel}{"ura/" if ura else ""}search.html">レース検索</a>'
           f'<a href="{rel}{"ura/" if ura else ""}seiseki.html">見立ての成績</a><a href="{rel}{"ura/" if ura else ""}about.html">このサイトについて</a>')
    other = alt if alt is not None else ("today.html" if ura else "ura/index.html")
    switch = (f'<a class="mode-sw" href="{rel}{other}" title="{"表の水面ノートで見る" if ura else "裏水面ノートで見る"}">'
              f'{"表へ" if ura else "裏へ"}<span aria-hidden="true">⇄</span></a>') if mode in ("omote", "ura") else ""
    head = ("" if mode == "top" else
            f'<header class="site-head"><a class="logo" href="{rel}index.html" title="表と裏を選ぶページへ">{name}</a>{switch}'
            f'<nav class="site-nav">{nav}</nav></header>')
    cls = " ".join(x for x in ("ura" if ura else "", page_class) if x)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:type" content="website"><meta property="og:url" content="{BASE_URL}{path}">
<meta property="og:site_name" content="{SITE_NAME}"><meta name="twitter:card" content="summary_large_image">
<meta property="og:image" content="{BASE_URL}assets/{"og-ura.png" if ura else "og-top.png" if mode == "top" else "og-omote.png"}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">{f'<meta name="google-site-verification" content="{e(GSV)}">' if GSV and mode == "top" else ""}
<link rel="canonical" href="{BASE_URL}{path}">{'<meta name="theme-color" content="#0d0b12">' if ura else ""}
<link rel="icon" href="{ICON_URA if ura else ICON}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@400;500;700;800&family=Mochiy+Pop+One&family=Dela+Gothic+One&display=swap">
<link rel="stylesheet" href="{rel}assets/style.css">
{data_js()}
</head><body{f' class="{cls}"' if cls else ""}><div class="wrap">
{head}
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


def result_banner(res_live, result, ura=False) -> str:
    """終わったレースの結果(3連単の組と払戻金)。裏では、万舟(1万円以上)に印を付ける。"""
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
    man = '<span class="uman-tag">万舟</span>' if ura and pay and pay >= 10000 else ""
    return (f'<section class="resbar" id="resbar"><span class="lbl">結果</span><span class="tri">{t}</span>{odds}{man}'
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


URA_RACE_NOTES = [
    "万舟の見込みは、このレースの3連単が1万円以上(100倍以上)になる見込みです。見立て(表と同じ式)から3連単120通りの起こりやすさを出し、"
    "組み合わせごとに「100倍以上で売れそうか」を掛けて足したものを、風・波・場・レースの種類・前づけで補正しています。"
    "100倍以上で売れそうかは、オッズが出る前は、過去のレースで見立ての起こりやすさと実際の配当の関係から学習した目安で、オッズが出たあと(締切の15分前から)は実際のオッズで計算します。",
    "荒れ度(大荒れ注意・荒れ気味・ふつう・平穏)は、万舟の見込みが、この場のふだんの万舟率の何倍かで分けています(1.5倍以上・1.15倍以上・0.85倍以上・それより下)。",
    "裏本線は、表の本線(1着になる見込みが一番高い艇)以外の艇で、「その決着になって、しかも万舟になる」見込みが一番高い決着(艇と決まり手)です。"
    "1着になる見込みそのものは低く、当たる割合は表の本線よりずっと低くなります。",
    "荒れる理由の数字(場・風・波・前づけ・1コースの見込みごとの万舟率、決着ごとの万舟率、最近の万舟)は、過去1年の公式の競走成績の払戻金から数えたものです。"
    "回数が少ないものは、その場全体の率に寄せています。",
    "人気と見立てのずれは、単勝オッズから出した「人気からの見込み」(オッズの逆数を6艇で合計1にしたもの)と、見立ての1着の見込みを比べたものです。"
    "見立てが人気より1.3倍以上高い艇を「人気より見立てが上」、人気からの見込みが見立てより8ポイント以上高い艇を「人気しすぎ」としています。",
    "1周1マークの映像は、裏本線を最初に、荒れたときにありそうな決着の順に並べています。",
] + RACE_NOTES[:5] + [RACE_NOTES[-1]]


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
               cat=None, cat_tbl=None, fem=None, pay=None):
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
    try:
        td = tidemod.at(code, d, dl_now)                # 締切の時刻の潮(潮の満ち引きの差がある場だけ)
        if td:
            td["rl"] = tidemod.range_level(code, td.get("rg"))
    except Exception:  # noqa: BLE001
        td = None
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
        x["ana"], x["inm"] = racer_ura(x["toban"], x.get("cls"))    # 穴をあけやすいか・1コースで万舟が多いか(裏の穴の材料)
    SEARCH.setdefault(ymd, {"venues": {}, "races": []})["races"].append({
        "c": code, "no": race["no"], "nm": race["name"], "dl": dl_now, "ds": race.get("distance"), "td": td["ph"] if td else None,
        "al": {k: v for k, v in (alerts or {}).items() if v},
        "e": [{"w": x["waku"], "t": x["toban"], "n": x["name"], "k": x.get("cls"), "f": x.get("fp") or 0, "fm": x.get("fem") or 0,
               "g": (x.get("mg") or {}).get("grade"), "z": (x.get("mg") or {}).get("z"), "sp": (x.get("mg") or {}).get("sp") or 0,
               "an": (x.get("ana") or [0] * 5)[4], "im": (x.get("inm") or [0] * 5)[4]} for x in ents]})
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
    meta_html = (f'<h1>{e(vname)} {race["no"]}R {e(race["name"])}</h1>'
                 f'<div class="meta"><span class="tag" id="dlTag">締切 {e(dl_now)}{"(変更)" if dl_now != dl_prog else ""}</span><span class="tag">{race["distance"]}m</span>'
                 + cat_tag(cat) + (f'<span class="tag">第{vprog["day"]}日</span>' if vprog.get("day") else "") + tide_tag(td)
                 + f'<span class="sub">{e(vprog.get("title", ""))}</span></div>'
                 f'<div class="alerts" id="alerts">{badges(alerts or {})}</div><div class="chips">{chips}</div>')
    head = (f'<nav class="crumb"><a href="{rel}today.html">今日のレース</a>›<a href="{rel}{ymd}/index.html">{jdate(d)}</a>›'
            f'<a href="index.html">{e(vname)}</a></nav>' + meta_html)
    data = {"venue": {k: vinfo[k] for k in ("code", "name", "place", "kimarite")}, "alerts": alerts or {}, "cat": cat,
            "race": {"date": d.isoformat(), "ymd": ymd, "no": race["no"], "name": race["name"], "deadline": dl_now,
                     **({"deadline0": dl_prog} if dl_now != dl_prog else {})}, "entries": ents,
            "vt": tables[0], "nt": tables[1]}
    if result:
        data["result"] = {"kimarite": result.get("kimarite"), "wind": result.get("wind"), "wind_dir": result.get("wind_dir"), "wave": result.get("wave"),
                          "entries": [{k: x.get(k) for k in ("waku", "course", "st", "flying", "rank", "status", "ex")}
                                      for x in result["entries"]]}
    if td:
        data["tide"] = td                # 締切の時刻の潮(気象庁の潮位表。scripts/tide.py)
    if pay:
        data["pay"] = {k: pay[k] for k in ("3t", "tan") if pay.get(k)}   # 払戻金(翌日の競走成績ファイルから。裏の振り返りに使う)
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
    write(path, page(title, desc, body, depth, path, script, RACE_NOTES, mode="omote", alt=f"ura/{path}"))
    # ---- 裏水面ノートの同じレースのページ(ura/ の下)。タブの種類は同じで、裏の見方に書きかえ、要るものを足して要らないものを外す
    ur = "../" * (depth + 1)
    uhead = (f'<nav class="crumb"><a href="{ur}ura/index.html">今日のレース</a>›<a href="{ur}ura/{ymd}/index.html">{jdate(d)}</a>›'
             f'<a href="index.html">{e(vname)}</a></nav>' + meta_html)
    uhero = ('<section class="uhero" id="uraHero" aria-live="polite"><div class="uh-wait">'
             '<p class="sub">万舟(3連単が1万円以上)になる見込みと、荒れるとしたら一番ありそうな決着(裏本線)を計算しています…</p></div></section>')
    u_card = (card + '<section class="usec" aria-labelledby="h-ucard"><h2 id="h-ucard">穴の材料</h2>'
              '<p class="sub">艇ごとの、荒れを起こしそうな材料と、荒れるとしたらその艇が1着になる見込みです。</p><div id="uraCard"><p class="wait">計算しています…</p></div></section>')
    u_tac = ('<section class="usec" aria-labelledby="h-utac"><h2 id="h-utac">外の攻め手と、1号艇の負け方</h2>'
             '<p class="sub">荒れるレースは、外の艇が1マークで攻めて決まることが多いので、捲り・捲り差しの多い選手と、1号艇が1コースで負けたときの形を先に並べます。</p>'
             '<div id="uraTac"><p class="wait">計算しています…</p></div></section>' + tac_html)
    u_before = ('<section class="usec" aria-labelledby="h-ubefore"><h2 id="h-ubefore">荒れのサイン(直前情報)</h2>'
                '<div id="uraBefore"><p class="wait">展示航走のあと(締切の10〜15分前ごろ)に、展示タイム・スタート展示・進入・チルト・部品交換・風と波から、荒れにつながるサインを探します。</p></div></section>'
                + before_html)
    u_odds = ('<section class="usec" aria-labelledby="h-uodds"><h2 id="h-uodds">人気と見立てのずれ</h2>'
              '<div id="uraOdds"><p class="wait">締切の15分前から、オッズ(人気)と見立ての1着の見込みを並べ、人気しすぎの艇と、人気より見立てが上の艇を探します。</p></div></section>'
              + odds_html)
    u_view = view.replace("1周1マーク展開シミュレーション", "1周1マーク 荒れ展開シミュレーション")
    u_analysis = ('<section class="gated"><h2>荒れたときの展開</h2><p class="wait">スタート展示のあとに出します。</p><div class="gbody" hidden>'
                  '<p class="sub" id="scenLead"></p><div class="scen" id="scen"></div><div class="p2" id="scen2"></div></div></section>'
                  '<section class="usec"><h2>荒れる理由</h2><ul class="points" id="points"><li>計算しています…</li></ul>'
                  '<p class="note">数字は過去1年の払戻金(公式の競走成績)から数えたものです。オッズが出たあとは、人気とのずれも入れて計算し直します。</p></section>'
                  '<section class="gated"><div class="row-head"><h2>裏メモ</h2><button id="btnCopy" type="button">コピー</button></div>'
                  '<p class="wait">スタート展示のあとに出します。</p><div class="gbody" hidden><textarea id="post" aria-label="裏メモ"></textarea>'
                  '<p class="note" id="copyMsg" aria-live="polite"></p></div></section>')
    u_data = ('<section class="usec" aria-labelledby="h-udata"><h2 id="h-udata">この場の荒れ方</h2><div id="uraData"><p class="wait">計算しています…</p></div></section>'
              + venue_html + res_html)
    ubody = (uhead + result_banner(res_live, result, ura=True) + '<section class="urev" id="uraReview" hidden></section>' + uhero + tabs
             + '<div class="pane" id="pane-card">' + u_card + "</div>"
             + '<div class="pane" id="pane-tac">' + u_tac + "</div>"
             + '<div class="pane" id="pane-before">' + u_before + "</div>"
             + '<div class="pane" id="pane-odds">' + u_odds + "</div>"
             + '<div class="pane" id="pane-t1">' + u_view + u_analysis + "</div>"
             + '<div class="pane" id="pane-navi">' + navi + "</div>"
             + '<div class="pane" id="pane-data">' + u_data + "</div>")
    upath = f"ura/{path}"
    uscript = (f'<script type="application/json" id="race-data">{blob}</script>'
               f'<script src="{ur}assets/model.js"></script><script src="{ur}assets/params.js"></script><script src="{ur}assets/uraparams.js"></script>'
               f'<script src="{ur}assets/turn1.js"></script><script src="{ur}assets/ura.js"></script><script src="{ur}assets/ura_page.js"></script>'
               f'<script src="{ur}assets/race.js"></script><script src="{ur}assets/odds.js"></script>')
    utitle = f"{vname} {race['no']}R 万舟の見込み・裏本線 {d.month}/{d.day} | {SITE_NAME_URA}"
    udesc = (f"{vname}{race['no']}R {race['name']}({jdate(d)} {race['deadline']}締切)の荒れ予報。万舟になる見込み、荒れるとしたら一番ありそうな決着(裏本線)と、"
             "風・波・展開・人気から見た荒れる理由。")
    write(upath, page(utitle, udesc, ubody, depth + 1, upath, uscript, URA_RACE_NOTES, mode="ura", alt=path))
    return path


VENUE_LIST: dict = {}   # 場ごとのレース一覧の中身((ymd, 場コード) → 行)。裏の場のページも同じ並び・同じ列で作る


def build_venue(d, code, vprog, vinfo, racers, results_v, vlive=None, al_map=None):
    ymd = d.strftime("%Y%m%d")
    vname = vinfo["name"]
    rows = []
    keep = []
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
        keep.append({"no": race["no"], "dl": dl_now, "moved": dl_now != race["deadline"], "name": race["name"], "dist": race["distance"],
                     "al": badges((al_map or {}).get(race["no"]), True) if (al_map or {}).get(race["no"]) and any((al_map or {}).get(race["no"]).values()) else "",
                     "tri": tri, "pay": (lr or {}).get("pay"), "w1": (x["name"], x["cls"]), "c1": c1txt})
        rows.append(f'<tr data-deadline="{e(dl_now)}" data-no="{race["no"]}"><td><a class="rno" href="{race["no"]:02d}.html">{race["no"]}R</a></td>'
                    f'<td class="num"><span class="dl{" moved" if dl_now != race["deadline"] else ""}">{e(dl_now)}</span><span class="small cd"></span></td>'
                    f'<td><a href="{race["no"]:02d}.html">{e(race["name"])}</a>' + (f'<span class="small">{race["distance"]}m</span>' if race["distance"] != 1800 else "")
                    + (f'<span class="alrow">{badges((al_map or {}).get(race["no"]), True)}</span>' if (al_map or {}).get(race["no"]) and any((al_map or {}).get(race["no"]).values()) else "")
                    + f'</td><td class="res">{restxt}</td><td><span class="waku w1">1</span> {e(x["name"])} <span class="small">{e(x["cls"])}</span></td>'
                    f'<td class="num">{c1txt}</td></tr>')
    p1 = vinfo["place"][0][0] if vinfo["place"] else 0
    VENUE_LIST[(ymd, code)] = {"rows": keep, "tier": f"{tier(p1)}(1コース1着率{f1(p1)}%)"}
    body = (f'<nav class="crumb"><a href="../../today.html">今日のレース</a>›<a href="../index.html">{jdate(d)}</a></nav>'
            f'<h1>{e(vname)} {jdate(d)}</h1><div class="meta">' + cat_tag(venue_cat(ymd, code)) + (f'<span class="tag">第{vprog["day"]}日</span>' if vprog.get("day") else "")
            + f'<span class="tag">{tier(p1)}(1コース1着率{f1(p1)}%)</span><span class="sub">{e(vprog.get("title", ""))}</span></div>'
            f'<section><h2>レース一覧</h2><div class="scroll"><table class="race-list" data-date="{d.isoformat()}" data-live="{ymd}/{code}.json" data-code="{code}" data-dlurl="{ymd}/dl.json"><thead><tr><th>R</th><th class="num">締切</th><th>レース</th>'
            '<th>結果</th><th>1号艇</th><th class="num">1号艇の<br>1コース1着率</th></tr></thead><tbody>' + "".join(rows)
            + "</tbody></table></div></section>")
    title = f"{vname} {jdate(d)} 出走表・レース一覧 | {SITE_NAME}"
    desc = f"{vname}の{jdate(d)}の全レースの出走表、選手のコース別成績、展開の見立て。{vprog.get('title', '')}"
    notes = ["1号艇の1コース1着率は、直近1年に1コースに入ったときの成績です。締切までの時間は、この端末の時計で数えています。"]
    write(f"{ymd}/{code}/index.html", page(title, desc, body, 2, f"{ymd}/{code}/", '<script src="../../assets/day.js"></script>', notes,
                                           mode="omote", alt=f"ura/{ymd}/{code}/index.html"))


GRADES_ALL: dict = {}   # 開催のグレード(data/grades.json。main で読み込む)


def venue_cat(ymd: str, code: str):
    """開催のグレードの表示名(オールレディース・ヴィーナスシリーズは「女子戦」)。"""
    g = (GRADES_ALL.get(ymd) or {}).get(code)
    if not g:
        return None
    return "女子戦" if ("lady" in g or "venus" in g) else g[0]


def day_cards(d, prog, depth_prefix, alerts=None, live=None, ura=False, S=None):
    """開催場のカード。締切の時刻を持たせておき、ページを開いたときに次のレースが近い順に並べ替える(day.js)。
    締切は公式の今の時刻(遅れて変わっていればそちら)。ページを開いている間は、day.js が dl.json を読んで合わせ直す。
    ura のときは、その場のふだんの万舟率と、今日の荒れ気味以上のレースの数も出す。"""
    ymd = d.strftime("%Y%m%d")
    items = []
    for code, v in prog["venues"].items():
        lv = (live or {}).get(code)
        first, last = v["races"][0]["deadline"], v["races"][-1]["deadline"]
        dls = ",".join(f'{r["no"]}-{deadline_of(r, lv)}' for r in v["races"] if deadline_of(r, lv))
        am = (alerts or {}).get(code, {})
        als = ",".join(f"{no}:{k}{lv}" for no, a in sorted(am.items()) for k, lv in a.items() if lv)
        extra = ""
        if ura:
            base = ura_base(code)
            hot = [r for r in (S or {}).get("races", []) if r["c"] == code and (r.get("u") or {}).get("pm") is not None
                   and r["u"]["pm"] >= base * 1.15]
            nums = sorted(r["no"] for r in hot)
            extra = (f'<span class="ubadge">ふだんの万舟率 {base * 100:.0f}%</span>'
                     + (f'<span class="ubadge hot">荒れ気味以上 {"・".join(str(n) for n in nums[:5])}R{f" ほか{len(nums) - 5}" if len(nums) > 5 else ""}</span>' if nums else ""))
        items.append((first, f'<a class="card vcard" href="{depth_prefix}{ymd}/{code}/index.html" data-dl="{dls}" data-al="{als}" data-code="{code}">'
                             f'<span class="vrow"><span class="v">{e(VENUES.get(code, code))}</span>{cat_tag(venue_cat(ymd, code))}<span class="als"></span></span>'
                             f'<span class="next" aria-live="polite"></span>'
                             f'<span class="t">{e(v.get("title", ""))}</span>' + (f'<span class="ubadges">{extra}</span>' if extra else "") + '<span class="sub">'
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
    body = (f'<nav class="crumb"><a href="../today.html">今日のレース</a></nav><h1>{jdate(d)}の開催</h1>'
            f'<div class="chips">{nav}</div><section><h2>開催場</h2>{day_cards(d, prog, "../", alerts, live)}</section>')
    write(f"{ymd}/index.html", page(f"{jdate(d)}のボートレース開催一覧 | {SITE_NAME}",
                                    f"{jdate(d)}に開催のボートレース全場の出走表と展開の見立て。", body, 1, f"{ymd}/",
                                    '<script src="../assets/day.js"></script>', DAY_NOTES, mode="omote", alt=f"ura/{ymd}/index.html"))


def build_index(today, progs, dates, alerts_by_day=None):
    show = today if today in progs else max(progs)
    nav = " ".join(f'<a class="chip{" on" if x == show else ""}" href="{x:%Y%m%d}/index.html">{x.month}/{x.day}</a>' for x in dates)
    label = "今日" if show == today else ("明日" if show == today + dt.timedelta(days=1) else "")
    body = (f'<h1>{label}{"の" if label else ""}レース {jdate(show)}</h1>'
            '<p class="lead">全国のボートレースの出走表を毎日自動で更新し、直前情報と1周1マークの展開シミュレーションを出しています。買い目は出しません。</p>'
            f'<div class="chips">{nav}</div><section><h2>開催場</h2>{day_cards(show, progs[show], "", (alerts_by_day or {}).get(show))}</section>')
    write("today.html", page(f"今日のレース | {SITE_NAME} ボートレースの出走表と展開の見立て",
                             "全国のボートレースの出走表を毎日自動更新。直前情報と1周1マークの展開シミュレーション。", body, 0, "today.html",
                             '<script src="assets/day.js"></script>', DAY_NOTES, mode="omote", alt="ura/index.html"))


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
        subprocess.run(["node", str(ROOT / "scripts" / "searchidx.js")], cwd=ROOT, timeout=600, check=False, env={**os.environ, "SITE_DIR": str(_OUT[0])})
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
                              body, 0, "search.html", '<script src="assets/search.js"></script>', notes, mode="omote", alt="ura/search.html"))


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
        write("seiseki.html", page(title, desc, "<h1>見立ての成績</h1><section><p>まだ記録がありません。</p></section>", 0, "seiseki.html",
                                   mode="omote", alt="ura/seiseki.html"))
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
    write("seiseki.html", page(title, desc, body, 0, "seiseki.html", script, mode="omote", alt="ura/seiseki.html"))


def build_about():
    body = ('<h1>このサイトについて</h1><section><p>水面ノートは、ボートレースの出走表と成績をデータで読み解く非公式のサイトです。'
            '毎日、公式が配布している番組表と競走成績のファイルを自動で取り込み、選手のコース別成績とレース場の特徴をまとめています。'
            'レースの当日は、締切の前後に BOAT RACE オフィシャルウェブサイトから直前情報と結果を取り込みます。</p>'
            '<p>見立てと1周1マークの展開シミュレーションは、過去の成績をもとにした目安です。</p></section>')
    write("about.html", page(f"このサイトについて | {SITE_NAME}", "水面ノートについて。データの出典と注意事項。", body, 0, "about.html",
                             mode="omote", alt="ura/about.html"))


# ======================================================================
# 表と裏を選ぶ最初のページと、裏水面ノートの一覧のページ
# ======================================================================
URA: dict = {}          # data/ura.json(裏の学習の結果。main で読み込む)


URA_RACERS: dict = {}  # data/ura_racers.json(選手ごとの万舟の数。main で読み込む)


def racer_ura(toban, cls):
    """選手の [万舟のレースで3着以内, 3着以内, その割合%, 同じ級の平均%, 穴をあけやすい印] と、
    [1コースの走数, そのうち万舟, 割合%, 同じ級の平均%, 1コースで万舟が多い印](過去1年の払戻金から)。"""
    a = (URA_RACERS.get("r") or {}).get(toban)
    if not a:
        return None, None
    _n, t3, m, _w, n1, m1 = a
    sh, ir = URA_RACERS.get("share") or {}, URA_RACERS.get("inr") or {}
    bs = (sh.get(cls) or sh.get("all") or 16.4) / 100
    bi = (ir.get(cls) or ir.get("all") or 16.4) / 100
    s_ = (m + 20 * bs) / (t3 + 20)
    r1 = (m1 + 10 * bi) / (n1 + 10)
    ana = [m, t3, round(m / t3 * 100) if t3 else 0, round(bs * 100), 1 if m >= 6 and s_ >= bs * 1.5 else 0]
    inm = [n1, m1, round(m1 / n1 * 100) if n1 else 0, round(bi * 100), 1 if n1 >= 8 and r1 >= bi * 1.4 else 0]
    return ana, inm


def tide_tag(td) -> str:
    """レースの見出しの潮の札(潮の満ち引きの差がある場だけ)。"""
    if not td:
        return ""
    nm = "満潮" if td["ph"] in ("上げ潮", "満潮前後") else "干潮"
    ev = td.get("ev") if td["ph"] in ("満潮前後", "干潮前後") and td.get("ev") else (td["hi"] if nm == "満潮" else td["lo"])
    return (f'<span class="tag tidetag" title="気象庁の潮位表({e(td["st"])})の推算潮位。締切の時刻の潮">潮 {e(td["ph"])}'
            + (f'・{nm} {e(ev[0])}' if ev else "") + "</span>")


def ura_level(pm, base):
    """万舟の見込みの、場のふだんの率に対する荒れ度(ura.js の level と同じ)。"""
    r = pm / max(base, 0.01)
    return ("大荒れ注意", "L3") if r >= 1.5 else ("荒れ気味", "L2") if r >= 1.15 else ("ふつう", "L1") if r >= 0.85 else ("平穏", "L0")


def ura_base(code):
    st = (URA.get("stats") or {})
    v = (st.get("ven") or {}).get(code)
    return (v[0] if v else st.get("nat", 16)) / 100


def read_search(ymd) -> dict:
    """node が見立てを足したあとの {ymd}/search.json。"""
    return load_json(_OUT[0] / ymd / "search.json", None) or {}


def ura_cell(r) -> str:
    """裏の一覧の「荒れの見込み」の欄(万舟の見込み・荒れ度と、裏本線)。r は search.json のレース。"""
    u = (r or {}).get("u") or {}
    pm = u.get("pm")
    if pm is None:
        return '<span class="dim">—</span>'
    name, cls = ura_level(pm, ura_base(r["c"]))
    ul = u.get("ul")
    line = (f'<span class="uln"><span class="waku w{ul[0]}">{ul[0]}</span><span class="uline">{ul[1]}コース <span class="nw">{e(ul[2])}</span></span></span>'
            if ul else "")
    return (f'<span class="ubox"><span class="umeter {cls}"><i style="width:{min(100, pm * 250):.0f}%"></i></span>'
            f'<b class="upct">{pm * 100:.0f}<small>%</small></b><span class="ulv {cls}">{name}</span></span>{line}')


def res_cell(tri, pay, ura=True) -> str:
    """一覧の結果の欄(3連単の組と払戻金)。裏では万舟(1万円以上)に印を付ける。"""
    if not tri:
        return ""
    return ('<span class="tri small-tri">' + "-".join(f'<span class="waku w{w}">{w}</span>' for w in tri) + "</span>"
            + (f'<span class="small">{pay / 100:.1f}倍</span>' if pay else "")
            + ('<span class="uman-tag sm">万舟</span>' if ura and pay and pay >= 10000 else ""))


def ura_row(r, S, prefix, live_day=None) -> str:
    """裏の「荒れそうなレース」の1行(場をまたいだ並び)。"""
    vn = (S.get("venues") or {}).get(r["c"], {}).get("name") or VENUES.get(r["c"], r["c"])
    href = f'{prefix}{S["ymd"]}/{r["c"]}/{r["no"]:02d}.html'
    lr = (((live_day or {}).get(r["c"]) or {}).get("result") or {}).get(str(r["no"])) or {}
    return (f'<tr><td><a class="rno" href="{href}">{e(vn)} {r["no"]}R</a><span class="small">{e(r.get("nm") or "")}</span></td>'
            f'<td class="num"><span class="dl">{e(r.get("dl") or "")}</span></td>'
            f'<td class="uman">{ura_cell(r)}</td><td class="res">{res_cell(lr.get("tri"), lr.get("pay"))}</td></tr>')


def ura_ranking(S, prefix, live_day=None, n=10) -> str:
    """荒れそうなレース(全場。場のふだんの万舟率の何倍かの順)。上位 n レースと、残りは開いて見る。"""
    rs = [r for r in S.get("races", []) if (r.get("u") or {}).get("pm") is not None]
    rs.sort(key=lambda r: -((r["u"]["pm"]) / max(ura_base(r["c"]), 0.01)))
    if not rs:
        return '<p class="sub">まだ計算できていません。</p>'
    def table(lst):
        return ('<div class="scroll"><table class="race-list ulist"><thead><tr><th>レース</th><th class="num">締切</th>'
                '<th>荒れの見込み<small class="th2">万舟・裏本線</small></th><th>結果</th></tr></thead><tbody>'
                + "".join(ura_row(r, S, prefix, live_day) for r in lst) + "</tbody></table></div>")
    rest = rs[n:]
    pre = any((r.get("u") or {}).get("pre") for r in rs)
    return (table(rs[:n])
            + (f'<details class="umore"><summary>残りの{len(rest)}レースも、荒れそうな順に見る</summary>{table(rest)}</details>' if rest else "")
            + ('<p class="note">展示の前のレースは、枠なりの進入・ふだんのSTで計算した目安です(レースのページでは、展示とオッズを入れて計算し直します)。</p>' if pre else ""))


URA_DAY_NOTES = ["荒れの見込みの数字は、そのレースが万舟(3連単が1万円以上)になる見込みです。荒れ度は、その場のふだんの万舟率(過去1年)の何倍かで、1.5倍以上が大荒れ注意、1.15倍以上が荒れ気味です。",
                 "裏本線は、表の本線(1着になる見込みが一番高い艇)以外の艇で、「その決着になって、しかも万舟になる」見込みが一番高い決着です。"]


def ura_man_html(d, prog, live, S, pfx) -> str:
    """今日の万舟(ページを作ったときまでの結果。開いている間は ura_day.js が読み直す)。"""
    ymd = d.strftime("%Y%m%d")
    U = load_json(DATA / "live" / ymd / "ura.json", {}) or {}
    dls = {f'{r["c"]}-{r["no"]}': r.get("dl") for r in S.get("races", [])}
    rows = []
    for code in prog["venues"]:
        for no, x in (((live or {}).get(code) or {}).get("result") or {}).items():
            if not x or not (x.get("pay") or 0) >= 10000 or len(x.get("tri") or []) != 3:
                continue
            k = f"{code}-{no}"
            cw = x.get("course") if len(x.get("course") or []) == 6 else None
            wc = cw.index(x["tri"][0]) + 1 if cw and x["tri"][0] in cw else None
            ul = ((U.get("races") or {}).get(k) or {}).get("ul")
            hit = ""
            if ul:
                hit = ('<span class="uhit">当たり</span>' if ul[1] == wc and ul[2] == x.get("kimarite") else
                       '<span class="uhit2">艇は当たり</span>' if ul[1] == wc else '<span class="dim">外れ</span>')
            rows.append((dls.get(k) or "", f'<tr><td><a class="rno" href="{pfx}{ymd}/{code}/{int(no):02d}.html">{e(VENUES.get(code, code))} {no}R</a>'
                         f'<span class="small">{e(dls.get(k) or "")}</span></td><td class="res">{res_cell(x["tri"], None, False)}'
                         f'<span class="small">{x["pay"]:,}円{("・" + str(x["pop"]) + "番人気") if x.get("pop") else ""}</span>'
                         f'<span class="small">1着 {(str(wc) + "コース ") if wc else ""}{e(x.get("kimarite") or "")}</span></td>'
                         f'<td class="uln2">{(f"<span class=\"waku w{ul[0]}\">{ul[0]}</span> {ul[1]}コース{e(ul[2])}<br>" + hit) if ul else "<span class=\"dim\">—</span>"}</td></tr>'))
    if not rows:
        return '<p class="sub">まだ万舟はありません。</p>'
    rows.sort(key=lambda r: r[0], reverse=True)
    return ('<div class="scroll"><table class="race-list ulist"><thead><tr><th>レース</th><th>結果</th><th>展示のあとの裏本線</th></tr></thead><tbody>'
            + "".join(r[1] for r in rows) + "</tbody></table></div>"
            + '<p class="note">展示のあとの裏本線は、スタート展示のあとに記録した裏本線です(レースのページでは、そのあとのオッズも入れて計算し直します)。</p>')


def build_ura_day(d, prog, dates, S, today, alerts=None, live=None, top=False):
    """裏の今日のレース(ura/index.html)と、日ごとのページ(ura/{ymd}/index.html)。表と同じ並び(開催場から各レースへ)に、荒れの見込みを足す。"""
    ymd = d.strftime("%Y%m%d")
    pfx = "" if top else "../"
    nav = " ".join(f'<a class="chip{" on" if x == d else ""}" href="{pfx}{x:%Y%m%d}/index.html">{x.month}/{x.day}</a>' for x in dates)
    label = "今日" if d == today else ("明日" if d == today + dt.timedelta(days=1) else "")
    rank = (f'<section><div class="row-head"><h2>荒れそうなレース</h2><span class="sub">場のふだんの万舟率と比べて高い順</span></div>'
            f'{ura_ranking(S, pfx, live)}</section>')
    if top:
        head = (f'<h1>{label}{"の" if label else ""}レース {jdate(d)}</h1>'
                '<p class="lead">全国の全レースを、荒れる(3連単が1万円以上の万舟になる)見込みと、荒れるとしたら一番ありそうな決着(裏本線)で見るモードです。'
                '当たる割合は低い代わりに、荒れたときを狙う見方です。買い目は出しません。</p>')
    else:
        head = f'<nav class="crumb"><a href="../index.html">今日のレース</a></nav><h1>{jdate(d)}の開催</h1>'
    live_sec, man_sec, strip, cfg_js = "", "", "", ""
    if d == today:                       # 今日: 展示のあとの荒れ(ura.json)・通知・今日の万舟。開いている間は ura_day.js が1分ごとに読み直す
        feed = (DATA_BASE + "ura/feed.xml") if DATA_BASE else RAW_BASE + "main/data/live/feed.xml"
        cfg = {"ymd": ymd, "date": d.isoformat(), "pfx": pfx, "vn": {c: VENUES.get(c, c) for c in prog["venues"]},
               "dl": {f'{r["c"]}-{r["no"]}': r.get("dl") for r in S.get("races", [])}}
        cfg_js = f'<script type="application/json" id="ura-day">{json.dumps(cfg, ensure_ascii=False)}</script>'
        strip = '<div class="ustrip" id="uraStrip" hidden></div>'
        live_sec = ('<section><div class="row-head"><h2>直前の荒れ</h2><span class="sub" id="uraLiveAt">展示のあとで計算し直した万舟の見込み</span></div>'
                    '<div id="uraLive"><p class="sub">スタート展示のあとに計算し直して、荒れ気味以上になったこれからのレースを出します。</p></div>'
                    f'<div class="unotify"><button type="button" class="chip" id="uraNotify" aria-pressed="false">大荒れ注意を通知する</button>'
                    f'<a class="chip" href="{e(feed)}">RSSで受け取る</a></div>'
                    '<p class="note">通知は、このページを開いている間だけ届きます(スマホは画面を開いているとき)。ページを閉じていても受け取りたいときは、'
                    'RSS(大荒れ注意になったレースの一覧)を RSS リーダーや通知のアプリに登録してください。</p></section>')
        man_sec = f'<section><h2>今日の万舟</h2><div id="uraMan">{ura_man_html(d, prog, live, S, pfx)}</div></section>'
    body = (head + f'<div class="chips">{nav}</div>' + strip
            + f'<section><h2>開催場</h2>{day_cards(d, prog, pfx, alerts, live, ura=True, S=S)}</section>' + live_sec + rank + man_sec + cfg_js)
    path = "ura/index.html" if top else f"ura/{ymd}/index.html"
    title = (f"今日のレース(裏) | {SITE_NAME_URA} 荒れ予報と裏本線" if top else f"{jdate(d)}の開催(裏) | {SITE_NAME_URA}")
    write(path, page(title, f"{jdate(d)}のボートレース全レースの、万舟になる見込みと裏本線。",
                     body, 1 if top else 2, path, f'<script src="{"../" if top else "../../"}assets/day.js"></script>'
                     + (f'<script src="{"../" if top else "../../"}assets/ura_day.js"></script>' if d == today else ""), URA_DAY_NOTES + DAY_NOTES,
                     mode="ura", alt="today.html" if top else f"{ymd}/index.html"))
    return path


def build_ura_venue(d, code, vprog, S, vlive=None):
    """裏の場ごとのレース一覧(ura/{ymd}/{code}/index.html)。表の場のページと同じ列に、荒れの見込み(万舟・裏本線)を足す。"""
    ymd = d.strftime("%Y%m%d")
    V = VENUE_LIST.get((ymd, code))
    if not V:
        return None
    vname = VENUES.get(code, code)
    races = {r["no"]: r for r in S.get("races", []) if r["c"] == code}
    rows = []
    for x in V["rows"]:
        nn = f'{x["no"]:02d}.html'
        rows.append(f'<tr data-deadline="{e(x["dl"])}" data-no="{x["no"]}"><td><a class="rno" href="{nn}">{x["no"]}R</a></td>'
                    f'<td class="num"><span class="dl{" moved" if x["moved"] else ""}">{e(x["dl"])}</span><span class="small cd"></span></td>'
                    f'<td><a href="{nn}">{e(x["name"])}</a>' + (f'<span class="small">{x["dist"]}m</span>' if x["dist"] != 1800 else "")
                    + (f'<span class="alrow">{x["al"]}</span>' if x["al"] else "")
                    + f'</td><td class="uman">{ura_cell(races.get(x["no"]))}</td><td class="res">{res_cell(x["tri"], x["pay"])}</td>'
                    f'<td><span class="waku w1">1</span> {e(x["w1"][0])} <span class="small">{e(x["w1"][1])}</span></td><td class="num">{x["c1"]}</td></tr>')
    st = URA.get("stats") or {}
    base = ura_base(code)
    rec = (st.get("recent") or {}).get(code) or []
    rec_html = ""
    if rec:
        rec_html = ('<section><h2>最近の万舟 <small class="h2s">この場</small></h2><div class="gridt-wrap"><table class="gridt"><thead><tr><th>日</th><th class="num">R</th>'
                    '<th>3連単</th><th class="num">払戻金</th><th class="num">人気</th><th>決まり手</th></tr></thead><tbody>'
                    + "".join(f'<tr><td>{e(x[0])}</td><td class="num">{x[1]}</td><td>{e(x[2])}</td><td class="num">{x[3]:,}円</td>'
                              f'<td class="num">{x[4] or "—"}</td><td>{(str(x[5]) + "コース " if x[5] else "") + e(x[6] or "")}</td></tr>' for x in rec)
                    + "</tbody></table></div></section>")
    body = (f'<nav class="crumb"><a href="../../index.html">今日のレース</a>›<a href="../index.html">{jdate(d)}</a></nav>'
            f'<h1>{e(vname)} {jdate(d)}</h1><div class="meta">' + cat_tag(venue_cat(ymd, code)) + (f'<span class="tag">第{vprog["day"]}日</span>' if vprog.get("day") else "")
            + f'<span class="tag">{e(V["tier"])}</span><span class="tag">この場の万舟率 {base * 100:.0f}%(全国 {st.get("nat", 16):.0f}%)</span>'
            f'<span class="sub">{e(vprog.get("title", ""))}</span></div>'
            f'<section><h2>レース一覧</h2><div class="scroll"><table class="race-list ulist" data-date="{d.isoformat()}" data-live="{ymd}/{code}.json" data-code="{code}" data-dlurl="{ymd}/dl.json">'
            '<thead><tr><th>R</th><th class="num">締切</th><th>レース</th><th>荒れの見込み<small class="th2">万舟・裏本線</small></th><th>結果</th><th>1号艇</th>'
            '<th class="num">1号艇の<br>1コース1着率</th></tr></thead><tbody>' + "".join(rows)
            + "</tbody></table></div></section>" + rec_html)
    path = f"ura/{ymd}/{code}/index.html"
    notes = ["荒れの見込みは、ページを作ったときの計算です(展示の前のレースは、枠なりの進入・ふだんのSTの目安)。レースのページでは、展示とオッズを入れて計算し直します。",
             "1号艇の1コース1着率は、直近1年に1コースに入ったときの成績です。締切までの時間は、この端末の時計で数えています。",
             "最近の万舟は、この場で3連単が1万円以上になったレース(新しい順)です。人気は3連単の人気の順位です。"]
    write(path, page(f"{vname} {jdate(d)} レース一覧(裏) | {SITE_NAME_URA}", f"{vname}の{jdate(d)}の全レースの、万舟になる見込みと裏本線。{vprog.get('title', '')}",
                     body, 3, path, '<script src="../../../assets/day.js"></script>', notes, mode="ura", alt=f"{ymd}/{code}/index.html"))
    return path


def build_ura_lists(dates, progs, today, alerts_by_day, urls):
    """node が見立て(裏も)を足した search.json を読み、裏の一覧のページを作る。"""
    shown = today if today in progs else max(progs)
    for d in dates:
        ymd = f"{d:%Y%m%d}"
        S = read_search(ymd)
        if not S:
            continue
        live_day = load_live(d)
        urls.append(build_ura_day(d, progs[d], dates, S, today, alerts_by_day.get(d), live_day))
        if d == shown:
            urls.append(build_ura_day(d, progs[d], dates, S, today, alerts_by_day.get(d), live_day, top=True))
        for code, vprog in progs[d]["venues"].items():
            pth = build_ura_venue(d, code, vprog, S, live_day.get(code))
            if pth:
                urls.append(pth)


def build_top(today, progs):
    """最初のページ(index.html): 水面ノート(表)と裏水面ノートを選ぶ。"""
    show = today if today in progs else max(progs)
    S = read_search(f"{show:%Y%m%d}")
    nv = len(progs[show]["venues"])
    nr = sum(len(v["races"]) for v in progs[show]["venues"].values())
    rs = [r for r in S.get("races", []) if (r.get("u") or {}).get("pm") is not None]
    rs.sort(key=lambda r: -(r["u"]["pm"] / max(ura_base(r["c"]), 0.01)))
    hot = ""
    if rs:
        r = rs[0]
        vn = (S.get("venues") or {}).get(r["c"], {}).get("name") or VENUES.get(r["c"], r["c"])
        hot = f'<span class="tsub">いちばん荒れそう: <b>{e(vn)} {r["no"]}R</b> 万舟の見込み {r["u"]["pm"] * 100:.0f}%</span>'
    label = "今日" if show == today else "明日"
    body = ('<div class="top-brand"><span class="logo">水面ノート</span><p class="sub">全国のボートレースを、データで読む。毎日自動で更新しています。買い目は出しません。</p></div>'
            '<div class="top-pick">'
            f'<a class="tpanel omote" href="today.html"><span class="tk">表</span><span class="tn">水面ノート</span>'
            '<span class="td">当てにいく本線。出走表・直前情報・1周1マークの展開シミュレーションで、一番ありそうな決着を出します。</span>'
            f'<span class="tsub">{label} {nv}場・{nr}レース</span><span class="tgo">今日のレースへ →</span></a>'
            '<a class="tpanel ura" href="ura/index.html"><span class="tk">裏</span><span class="tn">裏水面ノート</span>'
            '<span class="td">荒れを狙う裏本線。万舟になる見込みと、荒れるとしたら一番ありそうな決着を、風・波・展開・人気のずれから出します。</span>'
            f'<span class="tsub">{label} {nv}場・{nr}レース</span>{hot}<span class="tgo">今日のレースへ →</span></a></div>'
            '<nav class="top-links"><a href="search.html">レース検索(表)</a><a href="ura/search.html">レース検索(裏)</a>'
            '<a href="seiseki.html">見立ての成績(表)</a><a href="ura/seiseki.html">見立ての成績(裏)</a><a href="about.html">このサイトについて</a></nav>')
    write("index.html", page(f"{SITE_NAME} | ボートレースの出走表と展開の見立て(表)・荒れ予報(裏)",
                             "全国のボートレースの出走表を毎日自動更新。当てにいく本線の水面ノートと、荒れを狙う裏水面ノート。", body, 0, "",
                             "", None, mode="top", page_class="top"))


def build_ura_search(dates, today):
    tabs = "".join(f'<button type="button" class="chip{" on" if d == today else ""}" data-ymd="{d:%Y%m%d}">'
                   f'{"今日" if d == today else "明日" if d == today + dt.timedelta(days=1) else ""} {d.month}/{d.day}</button>' for d in dates)
    body = ('<h1>レース検索(裏)</h1><p class="lead">荒れの材料で、穴の出そうなレースを探します。「直前」の条件は、スタート展示のあとに取り込んだレースから探します。</p>'
            f'<div class="chips" id="sDates">{tabs}</div>'
            '<section class="sform"><div id="sConds" class="sconds"></div>'
            '<div class="srow"><input type="search" id="sName" placeholder="選手名・登番" autocomplete="off" aria-label="選手名・登番">'
            '<select id="sVenue" aria-label="場"><option value="">すべての場</option></select>'
            '<select id="sSort" aria-label="並び"><option value="man">荒れそうな順</option><option value="dl">締切の順</option></select></div>'
            '<div class="srow"><label class="sw"><input type="checkbox" id="sUpcoming" checked> これからのレースだけ</label>'
            '<span class="sw"><label><input type="radio" name="sMode" value="and" checked>すべて満たす</label>'
            '<label><input type="radio" name="sMode" value="or">どれか満たす</label></span>'
            '<button type="button" id="sClear">条件を外す</button></div>'
            '<button type="button" id="sJump" class="sjump" hidden></button></section>'
            '<section><h2 id="sCount">レース</h2><div id="sList" class="slist"><p class="sub">読み込み中…</p></div></section>')
    notes = ["万舟の見込みと裏本線は、ページを作ったときの計算です(展示の前のレースは、枠なりの進入・ふだんのSTの目安)。",
             "「荒れそうな順」は、万舟の見込みが、その場のふだんの万舟率の何倍かの順です。"]
    write("ura/search.html", page(f"レース検索(裏) | {SITE_NAME_URA}", "万舟の見込みが高い・1号艇が危ない・向かい風が強いなど、荒れの材料で今日のレースを探す。",
                                  body, 1, "ura/search.html", '<script src="../assets/search.js"></script>', notes, mode="ura", alt="search.html"))


def ura_record_days() -> list:
    """毎晩の答え合わせ(data/learn の ura)から、日ごとの裏の成績。締切前に記録した裏の見立て(pred.json の ura)と結果の比べ。"""
    out = []
    for p in sorted((DATA / "learn").glob("*.json")):
        x = (load_json(p, {}) or {}).get("ura") or {}
        if x.get("races", 0) >= 20:
            out.append({"d": (load_json(p, {}) or {}).get("date") or f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}", **x})
    return out


def build_ura_record():
    """裏の見立ての成績(ura/seiseki.html)。過去のレースで試した答え合わせと、毎日の記録。"""
    ev, back = URA.get("eval") or {}, URA.get("back") or {}
    title = f"見立ての成績(裏) | {SITE_NAME_URA}"
    desc = "裏水面ノートの見立て(万舟の見込み・裏本線)が、実際にどれだけ当たったかの記録。"
    def yen(v):
        return "—" if v is None else f"{v:,.0f}<small>円</small>"
    def pc(v):
        return "—" if v is None else f"{v:.0f}<small>%</small>"
    parts = ['<h1>見立ての成績(裏)</h1><p class="lead">裏水面ノートの見立てを、実際の結果(公式の競走成績の払戻金)と比べた記録です。'
             '裏は当たる割合が低い代わりに、当たったときの配当で補う見方なので、当たった割合と配当を並べて見てください。</p>']
    for lab, x in (("学習に使っていない直近の日", ev), ("学習した期間の全部", back)):
        if not x:
            continue
        span = f'{x["from"][5:].replace("-", "/")}〜{x["to"][5:].replace("-", "/")}・{x["races"]:,}レース'
        parts.append(
            f'<section class="rsec"><div class="row-head"><h2>{lab}</h2><span class="sub">{span}</span></div><div class="rtiles">'
            f'<div class="rtile"><div class="rl">裏本線の艇が1着</div><div class="rv">{pc(x.get("ura_hit"))}</div>'
            f'<span class="cmp">決まり手まで当たった {pc(x.get("ura_hitk"))}</span><div class="ra">表の本線の艇 {pc(x.get("omote_hit"))}</div></div>'
            f'<div class="rtile"><div class="rl">当たったときの3連単</div><div class="rv">{yen(x.get("ura_pay"))}</div>'
            f'<span class="cmp">まん中 {yen(x.get("ura_pay_med"))}・万舟 {pc(x.get("ura_man"))}</span><div class="ra">表の本線が当たったとき 平均 {yen(x.get("omote_pay"))}</div></div>'
            f'<div class="rtile"><div class="rl">万舟の見込みが高い2割のレース</div><div class="rv">{pc(x.get("top20_man"))}</div>'
            f'<span class="cmp">が万舟(全部では {pc(x.get("man"))})</span><div class="ra">見分けの良さ(AUC) {x.get("auc") or "—"}</div></div>'
            f'<div class="rtile"><div class="rl">単勝で見た回収率(参考)</div><div class="rv">{pc(x.get("ura_tan"))}</div>'
            f'<span class="cmp">裏本線の艇を毎回</span><div class="ra">表の本線の艇を毎回 {pc(x.get("omote_tan"))}</div></div>'
            "</div>")
        if x.get("calib"):
            parts.append('<details class="rdet"><summary>万舟の見込みと、実際に万舟になった割合</summary><div class="gridt-wrap"><table class="gridt rall"><thead><tr>'
                         '<th class="num">見込み(平均)</th><th class="num">実際の万舟率</th><th class="num">レース</th></tr></thead><tbody>'
                         + "".join(f'<tr><td class="num">{c[0]:.0f}%</td><td class="num">{c[1]:.0f}%</td><td class="num">{c[2]:,}</td></tr>' for c in x["calib"])
                         + "</tbody></table></div></details>")
        parts.append("</section>")
    days = ura_record_days()
    if days:
        def p0(v):
            return "—" if v is None else f"{v:.0f}%"
        rows = "".join(f'<tr><td>{x["d"][5:].replace("-", "/")}</td><td class="num">{x["races"]}</td><td class="num">{p0(x.get("man"))}</td>'
                       f'<td class="num">{p0(x.get("top_man"))}</td><td class="num"><b>{p0(x.get("hit"))}</b></td>'
                       f'<td class="num">{"—" if not x.get("pay") else format(x["pay"], ",.0f") + "円"}</td><td class="num">{p0(x.get("tan"))}</td>'
                       f'<td class="num">{(str(x["val_n"]) + "頭 " + p0(x.get("val_tan"))) if x.get("val_n") else "—"}</td></tr>'
                       for x in reversed(days))
        parts.append('<section><h2>日ごとの記録</h2><p class="sub">締切前(スタート展示のあと)に記録した裏の見立てと、その日の結果です。</p>'
                     '<div class="gridt-wrap"><table class="gridt rall"><thead><tr><th>日付</th><th class="num">レース</th><th class="num">万舟率</th>'
                     '<th class="num">見込み上位2割の万舟率</th><th class="num">裏本線の艇が1着</th><th class="num">当たったときの3連単(平均)</th>'
                     '<th class="num">単勝回収(参考)</th><th class="num">人気より見立てが上の艇(単勝・参考)</th></tr></thead>'
                     f"<tbody>{rows}</tbody></table></div></section>")
    else:
        parts.append('<section><h2>日ごとの記録</h2><p class="sub">締切前に記録した裏の見立ての答え合わせは、記録を始めた日の翌日から、ここに毎日足していきます。</p></section>')
    parts.append('<section><h2>見方</h2><ul class="points">'
                 "<li><b>裏本線の艇が1着</b>: 裏本線(表の本線の艇以外で、その決着になって万舟になる見込みが一番高い決着)の艇が、実際に1着になった割合。</li>"
                 "<li><b>当たったときの3連単</b>: 裏本線の艇が1着になったレースの、3連単の払戻金(100円あたり)。</li>"
                 "<li><b>万舟の見込みが高い2割のレース</b>: 万舟の見込みが高い順に並べた上位2割のレースのうち、実際に万舟になった割合。AUCは0.5が当てずっぽう、1が完全な見分け。</li>"
                 "<li><b>単勝で見た回収率(参考)</b>: 裏本線(または表の本線)の艇の単勝を、毎回同じ金額で買ったとしたときの払戻金の割合。買い目のおすすめではなく、"
                 "当たりにくさと配当の釣り合いを見るための目安です。100%を下回るのがふつうです。</li>"
                 "<li><b>人気より見立てが上の艇</b>: オッズが出たあとに、見立ての1着の見込みが人気(単勝オッズ)からの見込みの1.3倍以上だった艇(表の本線の艇を除く)。締切時オッズで数えています。</li>"
                 "</ul></section>")
    write("ura/seiseki.html", page(title, desc, "".join(parts), 1, "ura/seiseki.html", "", None, mode="ura", alt="seiseki.html"))


def build_ura_about():
    st = URA.get("stats") or {}
    back = URA.get("back") or {}
    body = ('<h1>裏水面ノートについて</h1>'
            '<section><h2>どんなモードか</h2><p>表の水面ノートは、レースを当てにいくための本線(一番ありそうな決着)を出します。'
            '裏水面ノートは反対に、荒れる(3連単が1万円以上の万舟になる)レースと、荒れるとしたらどの形かを探します。'
            '当たる割合は低い代わりに、当たったときの配当が大きい筋を見るためのモードです。</p></section>'
            '<section><h2>数字の出し方</h2><ul class="points">'
            '<li>見立ては表と同じ式です(スタートの見立てと、1着のコース×決まり手、2着・3着の並び)。そこから3連単120通りの起こりやすさを出します。</li>'
            '<li>組み合わせごとに「100倍以上で売れそうか」を見ます。オッズが出る前は、過去のレースで「見立ての起こりやすさ」と「実際の配当」の関係を学習した目安を使い、'
            'オッズが出たあとは実際のオッズを使います。</li>'
            '<li>その2つを掛けて足したものを、風・波・場・レースの種類・前づけで補正して「万舟の見込み」にします(過去の払戻金で学習し、毎日やり直します)。</li>'
            '<li>裏本線は、表の本線の艇以外で、「その決着になって、しかも万舟になる」見込みが一番高い決着です。</li>'
            '<li>荒れる理由は、過去1年の払戻金から数えた、場・風・波・前づけなどの条件ごとの万舟率と、このレースの選手・展示・オッズから並べます。</li>'
            '<li>オッズが出たあと(締切の15分前から)は、見立ての万舟の見込みと、票の割合(100倍以上の組に入っている票の割合)を、過去の締切時オッズで学習した重みで合わせます。'
            '締切の約15分前に最初に取り込んだオッズから大きく売れた艇・組も、「締切前の動き」として出します。</li>'
            '<li>潮の満ち引きの差がある場(江戸川・平和島・浜名湖・鳴門・丸亀・児島・宮島・徳山・下関・若松・福岡)は、気象庁の潮位表(推算潮位)から、締切の時刻の潮'
            '(上げ潮・下げ潮・満潮前後・干潮前後)とその日の干満の差を出し、過去1年の同じ潮のときの万舟率と比べます。</li>'
            '<li>穴をあけやすい選手は、過去1年に3着以内に来たレースのうち万舟だった割合が、同じ級の平均よりはっきり高い選手です(万舟絡みの回数も出します)。'
            '1コースのときにレースが万舟になった割合が高い選手(イン戦の万舟)も、同じように数えています。</li>'
            '<li>レースが終わると、実際の進入・スタート・決まり手・配当から、どう荒れたか(荒れなかったか)と、裏本線の当たり外れを振り返ります。</li></ul></section>'
            '<section><h2>大荒れ注意の知らせ</h2><ul class="points">'
            '<li>スタート展示のあとで、万舟の見込みがその場のふだんの1.5倍以上(大荒れ注意)になったレースを、裏の今日のレースの「直前の荒れ」に出します。</li>'
            '<li>「大荒れ注意を通知する」を押すと、そのページを開いている間、ブラウザの通知で知らせます。</li>'
            f'<li>ページを閉じていても受け取りたいときは、RSS({e(DATA_BASE or RAW_BASE + "main/data/live/")}{"ura/feed.xml" if DATA_BASE else "feed.xml"})を RSS リーダーや通知のアプリに登録してください。</li></ul></section>'
            '<section><h2>気をつけてほしいこと</h2><ul class="points">'
            f'<li>万舟は全国で{st.get("nat", 16):.0f}%ほどのレースでしか出ません。万舟の見込みが高いレースでも、荒れないことのほうが多くあります。</li>'
            '<li>人気のない艇は、実際に勝つ力より多く買われていることが多く、荒れを狙えば回収率が上がるとは限りません。'
            + (f'過去のレースで試すと、裏本線の艇が1着になったのは{back.get("ura_hit", 0):.0f}%で、そのときの3連単の払戻金は平均{back.get("ura_pay") or 0:,}円でした。' if back else "")
            + '実際の当たり方は見立ての成績のページに出しています。</li>'
            '<li>舟券の購入は20歳以上に限られます。無理のない範囲で楽しんでください。</li></ul></section>')
    write("ura/about.html", page(f"裏水面ノートについて | {SITE_NAME_URA}", "裏水面ノート(荒れ予報)の見方と、数字の出し方・注意。",
                                 body, 1, "ura/about.html", "", None, mode="ura", alt="about.html"))


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
    pay_day = (load_json(DATA / "pays" / f"{d:%Y%m%d}.json", {}) or {}).get("venues") or {}
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
            pth = build_race(d, code, vprog, race, vinfo, racers, rv.get(race["no"]), tables,
                             ranks=ranks, vlive=vlive, motors=motors, today_m=tm, alerts=al_day[code][race["no"]],
                             pace=pacemod.for_race(P_pace, code, race["entries"]), mrates=mrates,
                             cat=cat, cat_tbl=venue_table(ctabs.get(cat), 100) if cat else None, fem=cats.fem,
                             pay=(pay_day.get(code) or {}).get(str(race["no"])))
            urls += [pth, f"ura/{pth}"]


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
    urls = ["", "today.html", "about.html", "seiseki.html", "search.html", "ura/", "ura/about.html", "ura/seiseki.html", "ura/search.html"]
    # 見立てモデルの重み(scripts/fit.py が学習したもの)。ページから読めるように JS にして置く
    model = load_json(DATA / "model.json", None)
    (OUT / "assets" / "params.js").write_text(
        "window.SUIMEN_PARAMS = " + (json.dumps(model, ensure_ascii=False, separators=(",", ":")) if model else "null") + ";\n",
        encoding="utf-8")
    # 裏の学習(scripts/ura_fit.py)。ページが読む分だけ(答え合わせの細かい数字は除く)
    URA.clear()
    URA.update(load_json(DATA / "ura.json", {}) or {})
    URA_RACERS.update(load_json(DATA / "ura_racers.json", {}) or {})
    ura_js = {k: URA[k] for k in ("fitted", "man", "proxy", "cal", "stats", "mix") if k in URA} if URA else None
    (OUT / "assets" / "uraparams.js").write_text(
        "window.SUIMEN_URA = " + (json.dumps(ura_js, ensure_ascii=False, separators=(",", ":")) if ura_js else "null") + ";\n", encoding="utf-8")
    alerts_by_day = {}
    cats = category_resolver()                # レースの区分(開催のグレードと女子戦)と女子レーサー
    GRADES_ALL.clear()
    GRADES_ALL.update(cats.grades)
    for d in dates:
        build_date(d, progs, dates, cache, cats, model, stadiums, alerts_by_day, urls)
    build_index(today, progs, dates, alerts_by_day)
    build_about()
    build_record()
    write_search(dates, today)               # node が見立て(表・裏)を search.json に足す
    build_ura_lists(dates, progs, today, alerts_by_day, urls)
    build_top(today, progs)
    build_ura_search(dates, today)
    build_ura_about()
    build_ura_record()
    sm = "".join(f"<url><loc>{BASE_URL}{u}</loc></url>" for u in urls)
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}sitemap.xml\n")
    print(f"pages: {len(urls)} / dates: {[str(x) for x in dates]}")


if __name__ == "__main__":
    main()
