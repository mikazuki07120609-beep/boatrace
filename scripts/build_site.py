#!/usr/bin/env python3
"""data/ のJSONから、公開用のサイト(_site/)を作る。"""
import datetime as dt
import html
import json
import shutil

from common import DATA, OUT, PROGRAM, RESULTS, SITE, VENUES, KIMARITE, load_json, parse_ymd, today_jst
from stats import collect, venue_table

SITE_NAME = "水面ノート"
BASE_URL = "https://mikazuki07120609-beep.github.io/boatrace/"
PAST_DAYS = 6          # 今日より前に何日分のページを残すか
WD = "月火水木金土日"


def e(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def jdate(d: dt.date) -> str:
    return f"{d.month}月{d.day}日({WD[d.weekday()]})"


def f1(x, d=1):
    return "—" if x is None else f"{x:.{d}f}"


def pct(a, b):
    return None if not b else round(a / b * 100)


def page(title, desc, body, depth, path, scripts=""):
    rel = "../" * depth
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
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@400;500;700&family=IBM+Plex+Mono:wght@400;600&display=swap">
<link rel="stylesheet" href="{rel}assets/style.css">
</head><body><div class="wrap">
<header class="site-head"><a class="logo" href="{rel}index.html">{SITE_NAME}</a>
<nav class="site-nav"><a href="{rel}index.html">今日のレース</a><a href="{rel}about.html">このサイトについて</a></nav></header>
{body}
<footer><span>データは公式の番組表・競走成績ファイルから自動で作っています。正確な情報は主催者発表のものをご確認ください。</span>
<span>当サイトは非公式のデータ解説サイトで、舟券の購入をすすめるものではありません。舟券の購入は20歳以上に限られます。</span></footer>
</div>{scripts}</body></html>"""


def write(path: str, text: str):
    p = OUT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def venue_info(code, vstats, stadiums):
    st = stadiums.get(code, {})
    tbl = venue_table(vstats.get(code))
    if tbl:
        src = f"当サイト集計(直近90日・{tbl['races']}レース)"
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


def racer_view(entry, racers):
    r = racers.get(entry["toban"], {})
    cs = {}
    st_sum = st_n = n_all = 0
    for c, s in r.get("c", {}).items():
        cs[c] = {"n": s["n"], "w1": s["w1"], "w2": s["w2"], "w3": s["w3"], "st": s["st"], "km": s.get("km", {})}
        if s.get("ls"):
            cs[c]["ls"] = s["ls"]
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
    return v


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
    lines += ["", f"#ボートレース #{vname}", url]
    return "\n".join(lines)


LOSS = {"差し": "差され", "捲り": "捲られ", "捲り差し": "捲り差され"}


def tactic_cell(cs, course):
    """そのコースでの勝ち方(と1コースなら負け方)。2勝以上で6割以上が同じ決まり手なら「〇〇型」。"""
    if not cs or not cs.get("n"):
        return '<td>—</td>'
    km = cs.get("km") or {}
    if course == 1:
        lost = "・".join(f"{LOSS[k]}{cs['ls'][k]}" for k in ("差し", "捲り", "捲り差し") if cs.get("ls", {}).get(k))
        return f'<td>逃げ{km.get("逃げ", 0)}<span class="small">{e(lost) or "—"}</span></td>'
    items = sorted(((k, km.get(k, 0)) for k in ("捲り", "捲り差し", "差し") if km.get(k)), key=lambda kv: -kv[1])
    tot = sum(v for _, v in items)
    typ = f"{items[0][0]}型" if tot >= 2 and items[0][1] / tot >= 0.6 else ""
    return f'<td>{e("・".join(f"{k}{v}" for k, v in items) or "—")}<span class="small">{e(typ)}</span></td>'


def build_race(d, code, vprog, race, vinfo, racers, result, depth=2):
    ymd = d.strftime("%Y%m%d")
    vname = vinfo["name"]
    path = f"{ymd}/{code}/{race['no']:02d}.html"
    url = BASE_URL + path
    ents = [racer_view(x, racers) for x in race["entries"]]
    rel = "../" * depth
    # 出走表
    rows = []
    for x in ents:
        cs = x["cs"].get(str(x["waku"]))
        if cs and cs["n"]:
            crec = (f'<td class="num">{pct(cs["w1"], cs["n"])}%<span class="small">{cs["n"]}走</span></td>'
                    f'<td class="num">{pct(cs["w1"] + cs["w2"] + cs["w3"], cs["n"])}%</td><td class="num">{f1(cs["st"], 2)}</td>')
        else:
            crec = '<td class="num">—</td><td class="num">—</td><td class="num">—</td>'
        rows.append(
            f'<tr><td><span class="waku w{x["waku"]}">{x["waku"]}</span></td>'
            f'<td>{e(x["name"])}<span class="small">{e(x["toban"])} {e(x["cls"])} {e(x["branch"])} {e(x["age"])}歳</span></td>'
            f'<td class="num">{f1(x["rate"], 2)}<span class="small">{f1(x["rate2"])}%</span></td>'
            f'<td class="num">{f1(x["local"], 2)}<span class="small">{f1(x["local2"])}%</span></td>'
            f'{crec}{tactic_cell(cs, x["waku"])}'
            f'<td class="num">{e(x["motor"])}<span class="small">{f1(x["motor2"])}%</span></td>'
            f'<td class="num">{e(x["boat"])}<span class="small">{f1(x["boat2"])}%</span></td>'
            f'<td class="num">{e(x["series"] or "—")}</td></tr>')
    card = ("<section><h2>出走表</h2><p class=\"sub\">「同じコース」は枠番と同じコースに入ったときの直近1年の成績です(1着率・3連対率・平均ST)。"
            "「勝ち方」はそのコースで勝ったときの決まり手の回数で、1号艇は1コースで負けたときの決まり手(差され・捲られ)も出しています。</p>"
            '<div class="scroll"><table><thead><tr><th>枠</th><th>選手</th><th class="num">全国勝率</th><th class="num">当地勝率</th>'
            '<th class="num">同じコース<br>1着率</th><th class="num">3連対率</th><th class="num">平均ST</th><th>勝ち方</th>'
            '<th class="num">モーター</th><th class="num">ボート</th><th class="num">今節</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div></section>")
    # 直前情報の入力
    inrows = "".join(
        f'<tr><td><span class="waku w{x["waku"]}">{x["waku"]}</span></td><td>{e(x["name"])}</td>'
        f'<td><input id="ex{x["waku"]}" inputmode="decimal" placeholder="6.70" aria-label="{x["waku"]}号艇の展示タイム"></td>'
        f'<td><select id="c{x["waku"]}" aria-label="{x["waku"]}号艇の進入コース">'
        + "".join(f'<option value="{c}"{" selected" if c == x["waku"] else ""}>{c}</option>' for c in range(1, 7))
        + "</select></td></tr>" for x in ents)
    inputs = ('<section><h2>直前情報で見直す</h2><p class="sub">展示タイム・進入・風を入れると、下の展開の見立てが計算し直されます。'
              '空欄のままでも使えます。</p><div class="scroll"><table class="inputs"><thead><tr><th>枠</th><th>選手</th><th>展示タイム</th>'
              f'<th>進入</th></tr></thead><tbody>{inrows}</tbody></table></div>'
              '<div class="row"><label class="f">風向き<select id="wind"><option value="none">無風・弱い</option>'
              '<option value="head">向かい風</option><option value="tail">追い風</option><option value="side">横風</option></select></label>'
              '<label class="f">風速(m)<input id="windspd" type="number" min="0" max="15" step="1" value="2" style="width:80px"></label></div></section>')
    analysis = ('<section><h2>展開の見立て</h2><p class="sub" id="scenLead"></p><div class="scen" id="scen"></div>'
                '<p class="note">場のコース別1着率と決まり手の割合に、選手のコース別成績・勝率・ST・モーター・展示・風を掛け合わせた簡易モデルです。'
                '的中を保証するものではありません。</p></section>'
                '<section><h2>道中のポイント</h2><ul class="points" id="points"></ul><div class="boats" id="boats"></div></section>'
                '<section><div class="row" style="justify-content:space-between;align-items:center"><h2>解説文(X・note用)</h2>'
                '<button id="btnCopy" type="button">コピー</button></div><textarea id="post" aria-label="解説文"></textarea>'
                '<p class="note" id="copyMsg" aria-live="polite"></p></section>')
    # 結果
    res_html = ""
    if result:
        rr = sorted(result["entries"], key=lambda x: (x["rank"] or 9, x["waku"]))
        sts = [x["st"] for x in result["entries"] if x.get("st") is not None and not x.get("flying")]
        top_st = min(sts) if sts else None
        trs = "".join(
            f'<tr><td class="num">{x["rank"] or e(x["status"])}</td><td><span class="waku w{x["waku"]}">{x["waku"]}</span></td>'
            f'<td>{e(x["name"])}</td><td class="num">{x["course"] or "—"}</td>'
            f'<td class="num{" hi" if x.get("st") is not None and x["st"] == top_st and not x.get("flying") else ""}">'
            f'{("F" if x.get("flying") else "") + f1(x.get("st"), 2)}</td><td class="num">{f1(x.get("ex"), 2)}</td>'
            f'<td class="num">{e(x.get("time") or "—")}</td></tr>' for x in rr)
        rv = review_text(vname, race["no"], result, url)
        res_html = (f'<section><div class="result-head"><h2>結果</h2><span class="tag">決まり手 {e(result.get("kimarite") or "—")}</span>'
                    f'<span class="sub">{e(result.get("weather"))}・風 {e(result.get("wind_dir"))}{e(result.get("wind"))}m・波 {e(result.get("wave"))}cm</span></div>'
                    '<div class="scroll"><table><thead><tr><th class="num">着</th><th>枠</th><th>選手</th><th class="num">進入</th>'
                    f'<th class="num">ST</th><th class="num">展示</th><th class="num">タイム</th></tr></thead><tbody>{trs}</tbody></table></div>'
                    '<div class="row" style="justify-content:space-between;align-items:center"><h2>回顧文(X・note用)</h2>'
                    '<button id="btnCopyR" type="button">コピー</button></div>'
                    f'<textarea id="review" aria-label="回顧文">{e(rv)}</textarea><p class="note" id="copyMsgR" aria-live="polite"></p></section>')
    # 場
    vrows = ""
    if vinfo["place"]:
        for i in range(6):
            p = vinfo["place"][i]
            k = vinfo["kimarite"][i]
            mx = max(k) if k else 0
            vrows += (f'<tr><td><span class="waku w{i + 1}">{i + 1}</span></td>' + "".join(f'<td class="num">{f1(v)}</td>' for v in p)
                      + "".join(f'<td class="num{" hi" if v == mx and v > 0 else ""}">{f1(v)}</td>' for v in k) + "</tr>")
    p1 = vinfo["place"][0][0] if vinfo["place"] else 0
    facts = " ".join(f'<span class="tag">{e(t)}</span>' for t in [vinfo.get("pref"), vinfo.get("water") and "水質:" + vinfo["water"],
                                                                     vinfo.get("tide") and "干満差:" + vinfo["tide"], tier(p1)] if t)
    venue_html = ('<section><h2>レース場の特徴</h2>' + f'<div class="meta">{facts}</div>'
                  '<div class="scroll"><table><thead><tr><th>コース</th><th class="num">1着</th><th class="num">2着</th><th class="num">3着</th>'
                  + "".join(f'<th class="num">{k}</th>' for k in KIMARITE) + f'</tr></thead><tbody>{vrows}</tbody></table></div>'
                  f'<p class="note">単位:%。出典:{e(vinfo["src"])}</p></section>')
    # ナビ
    chips = "".join(f'<a class="chip{" on" if r["no"] == race["no"] else ""}" href="{r["no"]:02d}.html">{r["no"]}R</a>' for r in vprog["races"])
    head = (f'<nav class="crumb"><a href="{rel}index.html">今日のレース</a>›<a href="{rel}{ymd}/index.html">{jdate(d)}</a>›'
            f'<a href="index.html">{e(vname)}</a></nav>'
            f'<h1>{e(vname)} {race["no"]}R {e(race["name"])}</h1>'
            f'<div class="meta"><span class="tag">締切 {e(race["deadline"])}</span><span class="tag">{race["distance"]}m</span>'
            + (f'<span class="tag">第{vprog["day"]}日</span>' if vprog.get("day") else "")
            + f'<span class="sub">{e(vprog.get("title", ""))}</span></div><div class="chips">{chips}</div>')
    data = {"venue": {k: vinfo[k] for k in ("code", "name", "place", "kimarite")},
            "race": {"date": d.isoformat(), "no": race["no"], "name": race["name"]}, "entries": ents}
    # 1周1マーク展開ビュー(スタートから全艇が1マークを回り切るまでの上空シミュレーション)
    view = ('<section class="t1" aria-labelledby="h-t1"><div class="row" style="justify-content:space-between;align-items:center">'
            '<h2 id="h-t1">1周1マーク展開ビュー</h2><span class="sub">データに基づくシミュレーション</span></div>'
            '<canvas id="t1view" role="img" aria-label="スタートから全艇が1周1マークを回り切るまでを上空から見たシミュレーション"></canvas>'
            '<div class="ctrl"><button class="primary" id="t1Replay" type="button">もう一度再生</button>'
            '<button id="t1Pause" type="button">一時停止</button>'
            '<button id="t1Slow" type="button" aria-pressed="false">ゆっくり再生</button>'
            '<button id="t1Save" type="button">動画を保存</button></div>'
            '<div class="ctrl" id="t1Out" hidden></div><p class="note" id="t1Msg" aria-live="polite"></p>'
            '<div class="pats" id="t1Pats" role="group" aria-label="決着パターン"></div>'
            '<p class="note">展開の見立てで上位の決着パターンを、選手の平均ST・モーター・コースごとの勝ち方から動かしています。'
            '下の「直前情報で見直す」に展示タイムや進入を入れると、映像も作り直します。</p></section>')
    body = head + (res_html if result else "") + view + card + inputs + analysis + venue_html
    first = ents[0]
    c1 = first["cs"].get("1")
    c1txt = f"1コース1着率{pct(c1['w1'], c1['n'])}%({c1['n']}走)" if c1 and c1["n"] else f"全国勝率{f1(first['rate'], 2)}"
    desc = (f"{vname}{race['no']}R {race['name']}({jdate(d)} {race['deadline']}締切)。1号艇 {first['name']}({first['cls']}) {c1txt}。"
            "選手のコース別成績と展開の見立て。")
    title = f"{vname} {race['no']}R {race['name']} 出走表と展開 {d.month}/{d.day} | {SITE_NAME}"
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    script = (f'<script type="application/json" id="race-data">{blob}</script>'
              f'<script src="{rel}assets/turn1.js"></script><script src="{rel}assets/race.js"></script>')
    write(path, page(title, desc, body, depth, path, script))
    return path


def build_venue(d, code, vprog, vinfo, racers, results_v):
    ymd = d.strftime("%Y%m%d")
    vname = vinfo["name"]
    rows = []
    for race in vprog["races"]:
        x = racer_view(race["entries"][0], racers)
        c1 = x["cs"].get("1")
        c1txt = f'{pct(c1["w1"], c1["n"])}%<span class="small">{c1["n"]}走</span>' if c1 and c1["n"] else "—"
        res = (results_v or {}).get(race["no"])
        if res:
            w = next((y for y in res["entries"] if y.get("rank") == 1), None)
            restxt = (f'<span class="waku w{w["waku"]}">{w["waku"]}</span> {e(res.get("kimarite") or "")}' if w else "—")
        else:
            restxt = ""
        rows.append(f'<tr><td><a class="rno" href="{race["no"]:02d}.html">{race["no"]}R</a></td><td class="num">{e(race["deadline"])}</td>'
                    f'<td><a href="{race["no"]:02d}.html">{e(race["name"])}</a>' + (f'<span class="small">{race["distance"]}m</span>' if race["distance"] != 1800 else "")
                    + f'</td><td><span class="waku w1">1</span> {e(x["name"])} <span class="small">{e(x["cls"])}</span></td>'
                    f'<td class="num">{c1txt}</td><td>{restxt}</td></tr>')
    p1 = vinfo["place"][0][0] if vinfo["place"] else 0
    body = (f'<nav class="crumb"><a href="../../index.html">今日のレース</a>›<a href="../index.html">{jdate(d)}</a></nav>'
            f'<h1>{e(vname)} {jdate(d)}</h1><div class="meta">' + (f'<span class="tag">第{vprog["day"]}日</span>' if vprog.get("day") else "")
            + f'<span class="tag">{tier(p1)}(1コース1着率{f1(p1)}%)</span><span class="sub">{e(vprog.get("title", ""))}</span></div>'
            '<section><h2>レース一覧</h2><div class="scroll"><table class="race-list"><thead><tr><th>R</th><th class="num">締切</th><th>レース</th>'
            '<th>1号艇</th><th class="num">1号艇の<br>1コース1着率</th><th>結果</th></tr></thead><tbody>' + "".join(rows)
            + "</tbody></table></div><p class=\"note\">1号艇の1コース1着率は、直近1年に1コースに入ったときの成績です。</p></section>")
    title = f"{vname} {jdate(d)} 出走表・レース一覧 | {SITE_NAME}"
    desc = f"{vname}の{jdate(d)}の全レースの出走表、選手のコース別成績、展開の見立て。{vprog.get('title', '')}"
    write(f"{ymd}/{code}/index.html", page(title, desc, body, 2, f"{ymd}/{code}/"))


def day_cards(d, prog, depth_prefix):
    ymd = d.strftime("%Y%m%d")
    items = []
    for code, v in prog["venues"].items():
        first, last = v["races"][0]["deadline"], v["races"][-1]["deadline"]
        items.append((first, f'<a class="card" href="{depth_prefix}{ymd}/{code}/index.html"><span class="v">{e(VENUES.get(code, code))}</span>'
                             f'<span class="t">{e(v.get("title", ""))}</span><span class="sub">'
                             + (f'第{v["day"]}日 ・ ' if v.get("day") else "") + f'{len(v["races"])}R ・ 締切 {e(first)}〜{e(last)}</span></a>'))
    items.sort()
    return '<div class="cards">' + "".join(x[1] for x in items) + "</div>"


def build_day(d, prog, dates):
    ymd = d.strftime("%Y%m%d")
    nav = " ".join(f'<a class="chip{" on" if x == d else ""}" href="../{x:%Y%m%d}/index.html">{x.month}/{x.day}</a>' for x in dates)
    body = (f'<nav class="crumb"><a href="../index.html">今日のレース</a></nav><h1>{jdate(d)}の開催</h1>'
            f'<div class="chips">{nav}</div><section><h2>開催場</h2>{day_cards(d, prog, "../")}</section>')
    write(f"{ymd}/index.html", page(f"{jdate(d)}のボートレース開催一覧 | {SITE_NAME}",
                                    f"{jdate(d)}に開催のボートレース全場の出走表と展開の見立て。", body, 1, f"{ymd}/"))


def build_index(today, progs, dates):
    show = today if today in progs else max(progs)
    nav = " ".join(f'<a class="chip{" on" if x == show else ""}" href="{x:%Y%m%d}/index.html">{x.month}/{x.day}</a>' for x in dates)
    label = "今日" if show == today else ("明日" if show == today + dt.timedelta(days=1) else "")
    body = (f'<h1>{label}{"の" if label else ""}レース {jdate(show)}</h1>'
            '<p class="lead">全国のボートレースの出走表を毎日自動で更新しています。選手のコース別成績・レース場の特徴から、'
            '展開の見立てとX・note用の解説文を作ります。買い目は出しません。</p>'
            f'<div class="chips">{nav}</div><section><h2>開催場</h2>{day_cards(show, progs[show], "")}</section>')
    write("index.html", page(f"{SITE_NAME} | ボートレースの出走表と展開の見立て",
                             "全国のボートレースの出走表を毎日自動更新。選手のコース別成績とレース場の特徴から展開の見立てを作るデータサイト。", body, 0, ""))


def build_about():
    body = ('<h1>このサイトについて</h1><section><p>水面ノートは、ボートレースの出走表と成績をデータで読み解く非公式のサイトです。'
            '毎日、公式が配布している番組表と競走成績のファイルを自動で取り込み、選手のコース別成績とレース場の特徴をまとめています。</p>'
            '<p>「展開の見立て」は、過去の成績をもとにした簡易モデルによる目安です。レースの結果を保証するものではなく、舟券の購入をすすめるものでもありません。</p>'
            '<p>データの読み取りには誤りが含まれる可能性があります。正確な情報は主催者発表のものをご確認ください。'
            '舟券の購入は20歳以上に限られます。</p></section>')
    write("about.html", page(f"このサイトについて | {SITE_NAME}", "水面ノートについて。データの出典と注意事項。", body, 0, "about.html"))


def main():
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
    urls = ["", "about.html"]
    for d in dates:
        racers, vstats = collect(d, cache)
        res_day = load_json(RESULTS / f"{d:%Y%m%d}.json", {}) or {}
        build_day(d, progs[d], dates)
        urls.append(f"{d:%Y%m%d}/")
        for code, vprog in progs[d]["venues"].items():
            vinfo = venue_info(code, vstats, stadiums)
            if not vinfo["place"]:
                continue
            rv = {r["no"]: r for r in res_day.get("venues", {}).get(code, {}).get("races", [])}
            build_venue(d, code, vprog, vinfo, racers, rv)
            urls.append(f"{d:%Y%m%d}/{code}/")
            for race in vprog["races"]:
                urls.append(build_race(d, code, vprog, race, vinfo, racers, rv.get(race["no"])))
    build_index(today, progs, dates)
    build_about()
    sm = "".join(f"<url><loc>{BASE_URL}{u}</loc></url>" for u in urls)
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>')
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}sitemap.xml\n")
    print(f"pages: {len(urls)} / dates: {[str(x) for x in dates]}")


if __name__ == "__main__":
    main()
