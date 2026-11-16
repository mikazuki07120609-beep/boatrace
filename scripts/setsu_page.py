"""一節まとめのページ(build_site.py から呼ぶ)。データと集計は setsu.py。

ページ: setsu/{場}_{初日}.html(節ごと)と setsu/index.html(今の節の一覧)。
タブ: まとめ(今の優勝候補・得点率の順位・モーターの変化・相性・スタート・水面) / 前検(前検の時点の優勝候補・注目モーター・注目選手・出場選手) /
      初日・2日目…(その日のレースが全部終わったら足す)。
"""
from __future__ import annotations

import datetime as dt

import setsu as S_
from common import DATA, VENUES, load_json, parse_ymd
from setsu import ACCIDENT, CHG, MAN, e, is_final, is_semi

STAGE_TXT = {"before": "前検の見込み", "y4": "得点率と前検の見込みから", "y3": "得点率と前検の見込みから(予選の終盤)",
             "semi": "準優の顔ぶれと枠から", "final": "優勝戦の顔ぶれと枠から"}


def wk(w) -> str:
    return f'<span class="waku w{w}">{w}</span>' if w else ""


def gch(g) -> str:
    if not g:
        return ""
    return f'<b class="g {"gSp" if g == "S+" else "g" + g}">{e(g)}</b>'


def sgn(x, d=2) -> str:
    """符号つきの数(+0.03・−0.01)。丸めて0になるものは符号を付けない。"""
    if x is None:
        return "—"
    r = round(x, d)
    if r == 0:
        return f"{0:.{d}f}"
    return f"{r:+.{d}f}".replace("-", "−")


def stt(x) -> str:
    """ST の表示(.12)。マイナス(展示のフライング)は F.01。"""
    if x is None:
        return "—"
    r = round(x, 2)
    if r < 0:
        return "F" + f"{-r:.2f}"[1:]
    return f"{r:.2f}"[1:] if r < 1 else f"{r:.2f}"


def pc(p) -> str:
    return f"{p * 100:.1f}%"


def nm(R: dict, t: str, fb: str = "", sub: bool = True) -> str:
    x = R.get(t) or {}
    name = x.get("name") or fb or t
    if not sub:
        return e(name)
    s = " ".join(v for v in (x.get("cls"), x.get("branch")) if v)
    return f'{e(name)}<span class="small">{e(s)}</span>'


def day_label(day: dict) -> str:
    if any(is_final(r["name"]) for r in day["races"]):
        return "最終日"
    return "初日" if day["k"] == 1 else f"{day['k']}日目"


def phase_of(day: dict) -> str:
    names = " ".join(r["name"] for r in day["races"])
    if any(is_final(r["name"]) for r in day["races"]):
        return "優勝戦"
    if any(is_semi(r["name"]) for r in day["races"]):
        return "準優勝戦"
    return "予選" if "予選" in names else ""


# ---------------------------------------------------------------- 部品

def cand_list(R: dict, p: dict, n: int = 6, wkm: dict | None = None, S: dict | None = None, show_p0: bool = False) -> str:
    if not p:
        return '<p class="sub">まだ計算できません。</p>'
    top = sorted(p, key=lambda t: -p[t])[:n]
    mx = max(p[t] for t in top) or 1
    items = []
    for i, t in enumerate(top):
        x = R.get(t) or {}
        bits = []
        if x:
            bits.append(f"着順点の平均{x['str']:.2f}")
            if x.get("vn", 0) >= 6:
                bits.append(f"当地{sgn(x['loc'], 1)}")
            if x.get("mg"):
                bits.append(f"モーター{x['motor']}号機({x['mg']})")
        if S and t in S and S[t]["n"]:
            bits.append(f"今節の得点率{S[t]['avg']:.2f}({S[t]['rank']}位)")
        if show_p0 and x.get("p0") is not None:
            bits.append(f"前検の見込み{pc(x['p0'])}")
        items.append(f'<li class="sx-c"><span class="sx-rk">{i + 1}</span>{wk((wkm or {}).get(t))}<div class="sx-nm">{nm(R, t)}</div>'
                     f'<div class="sx-p"><b>{pc(p[t])}</b><div class="bar"><i style="width:{p[t] / mx * 100:.0f}%"></i></div></div>'
                     f'<div class="sx-why">{e("・".join(bits))}</div></li>')
    return '<ol class="sx-cands">' + "".join(items) + "</ol>"


def standings_table(R: dict, S: dict, days: list, upto: int, top: int | None = 18, mark: dict | None = None, border: bool = True,
                    more: bool = True) -> str:
    """得点率の順位の表。上位 top 人を出し、残りは「続きを見る」に入れる(more が False なら出さない)。"""
    ts = sorted([t for t in S if S[t]["n"]], key=lambda t: (S[t]["rank"], -S[t]["n"]))
    ks = [d["k"] for d in days[:upto]]
    head = "".join(f'<th class="num">{"初日" if k == 1 else f"{k}日"}</th>' for k in ks)

    def row(t):
        s = S[t]
        cells = "".join(f'<td class="num sx-mk">{e(s["marks"].get(k, ""))}</td>' for k in ks)
        tag = (mark or {}).get(t)
        cls = "sx-in" if tag else ("sx-border" if border and s["rank"] == 18 else "")
        return (f'<tr{f" class={cls}" if cls else ""}><td class="num">{s["rank"]}</td><td>{nm(R, t, s["name"])}'
                f'{f"<span class=sx-tag>{e(tag)}</span>" if tag else ""}</td>'
                f'<td class="num"><b>{s["avg"]:.2f}</b><span class="small">{s["pts"]}点・{s["n"]}走</span></td>{cells}</tr>')

    def table(rows):
        return (f'<div class="scroll"><table class="sx-tbl sx-std"><thead><tr><th class="num">順位</th><th>選手</th><th class="num">得点率</th>{head}</tr></thead>'
                f'<tbody>{"".join(row(t) for t in rows)}</tbody></table></div>')
    if not top or len(ts) <= top + 2:
        return table(ts)
    rest = f'<details class="sx-more"><summary>{top + 1}位から下を見る({len(ts) - top}人)</summary>{table(ts[top:])}</details>' if more else ""
    return table(ts[:top]) + rest


def results_table(R: dict, day: dict) -> str:
    """その日のレースの結果(R・1着と決まり手・3連単)。万舟の行は色を付ける。"""
    out = []
    for r in day["races"]:
        rn = f'<td class="rno">{r["no"]}R<span class="small">{e(r["name"])}</span></td>'
        if not r["done"]:
            out.append(f'<tr>{rn}<td colspan="2" class="sub">結果待ち</td></tr>')
            continue
        w = next((y for y in r["boats"] if y["rank"] == 1), None)
        tri = "".join(wk(x) for x in (r["tri"] or []))
        man = bool(r["pay"] and r["pay"] >= MAN)
        pay = ""
        if r["pay"]:
            pop = f"・{r['pop']}番人気" if r.get("pop") else ""
            pay = f'<span class="small">{r["pay"]:,}円{pop}</span>'
        how = "・".join(v for v in ((f'{w["course"]}コース' if w and w.get("course") else ""), r["kim"] or "") if v)
        win = (f'{wk(w["waku"])}<span class="sx-wn">{nm(R, w["toban"], w["name"], sub=False)}<span class="small">{e(how)}</span></span>' if w else "")
        out.append(f'<tr{" class=sx-man" if man else ""}>{rn}<td class="sx-win">{win}</td><td><span class="small-tri">{tri}</span>{pay}</td></tr>')
    return ('<div class="scroll"><table class="sx-tbl sx-res"><thead><tr><th>R</th><th>1着・決まり手</th><th>3連単</th></tr></thead><tbody>'
            + "".join(out) + "</tbody></table></div>")


# ---------------------------------------------------------------- タブ

def pane_summary(sf: dict, G: dict, A: dict, W: list, model: dict | None, vname: str) -> str:
    R = sf["roster"]
    days = G["days"]
    win = A["win"]
    S = A["S"]
    per = A["per"]
    k = A["kdone"]
    secs = []
    # 優勝候補(今)
    if win["stage"] == "done":
        c = win["champ"]
        x = R.get(c) or {}
        race = win["race"]
        y = next((b for b in race["boats"] if b["toban"] == c), {})
        rank0 = sorted(R, key=lambda t: -(R[t].get("p0") or 0)).index(c) + 1 if c in R and R[c].get("p0") is not None else None
        course = y.get("course")
        txt = (f'<p class="sx-champ">{wk(y.get("waku"))}<b>{nm(R, c, y.get("name", ""), sub=False)}</b>'
               f'<span>{f"{course}コース・" if course else ""}{e(race["kim"] or "")}</span></p>')
        if x.get("p0") is not None:
            txt += f'<p class="sub">前検の見込みでは{pc(x["p0"])}({rank0}番手)でした。</p>'
        secs.append(f'<section><h2>優勝</h2>{txt}</section>')
    else:
        stage = win["stage"]
        lead = STAGE_TXT.get(stage, "")
        ev = ((model or {}).get("eval") or {}).get("pre" if stage == "before" else stage) or {}
        evtxt = (f'直近{ev["n"]}節では、この段階の1番手が優勝したのは{ev["top1"]:.0f}%、3番手までに優勝者がいたのは{ev["top3"]:.0f}%です。'
                 if ev.get("n") else "")
        secs.append(f'<section><h2>今の優勝候補<span class="h2s">{e(lead)}</span></h2>'
                    + cand_list(R, win["p"], 6, win.get("wk"), S if k else None, show_p0=bool(k))
                    + f'<p class="note">優勝の見込みは、過去の節で学んだ式の計算です。{evtxt}</p></section>')
    # 得点率の順位
    if k:
        mark = {}
        nxt_day = next((d for d in days if not d["complete"]), None)
        if nxt_day:
            for r in nxt_day["races"]:
                if is_final(r["name"]) or is_semi(r["name"]):
                    for b in r["boats"]:
                        mark[b["toban"]] = "優出" if is_final(r["name"]) else "準優"
        secs.append('<section><h2>得点率の順位<span class="h2s">' + ("最終日まで" if win["stage"] == "done" else f"{k}日目まで") + "</span></h2>"
                    + standings_table(R, S, days, k, mark=mark, border=win["stage"] in ("y4", "y3"))
                    + '<p class="note">今節の着順を点数(1着10点・2着8点・3着6点・4着4点・5着2点・6着1点)にした平均です。'
                    'F・出遅れ・失格は0点で1走、欠場は数えません。事故点や特別な加点は入れていないので、公式の得点率と少し違うことがあります。'
                    '18位の行は準優のボーダーの目安です(準優の枠の数は節によって違います)。</p></section>')
    # モーターの変化
    if k:
        ts = sorted([t for t in per if per[t]["mc"]["avg"] is not None], key=lambda t: -per[t]["mc"]["avg"])
        ks = [d["k"] for d in days[:k]]
        up = [t for t in ts if per[t]["mc"]["label"] == "上向き"]
        down = [t for t in ts if per[t]["mc"]["label"] == "下向き"]
        accs = [t for t in ts if any(a.split(" ")[-1] in ("転覆", "落水", "沈没", "エンスト", "不完走") for a in per[t]["acc"])]

        def who(t):
            x = R.get(t) or {}
            return f'<b>{nm(R, t, per[t]["name"], sub=False)}</b><span class="sx-mn">{per[t]["motor"]}号機{gch(x.get("mg"))}</span>'

        def li_chg(t):
            mc = per[t]["mc"]
            ev = f'({e(mc["events"][-1])}の{e(mc["why"])})' if mc["events"] and mc["why"] == "前後" else f'({e(mc["why"])})'
            return f'<li>{who(t)}<span class="sub">展示の速さ{sgn(mc["delta"], 3)}秒{ev}</span></li>'

        def li_acc(t):
            mc = per[t]["mc"]
            aft = (f'。そのあとの展示は{sgn(mc["delta"], 3)}秒' if mc["delta"] is not None and mc["events"] and "部品" not in mc["events"][-1]
                   and "プロペラ" not in mc["events"][-1] else "")
            return f'<li>{who(t)}<span class="sub">{e("・".join(per[t]["acc"]))}{aft}</span></li>'
        fast = "".join(f'<li>{who(t)}<span class="sub">展示が平均より{sgn(per[t]["mc"]["avg"], 3)}秒(この節の{per[t].get("exrank")}位・{per[t]["mc"]["n"]}走)</span></li>'
                       for t in [t for t in ts if per[t]["mc"]["n"] >= 4][:5])
        rows = []
        for t in ts:
            p = per[t]
            mc = p["mc"]
            x = R.get(t) or {}
            byday = " ".join(sgn(mc["days"][kk], 2) if kk in mc["days"] else "—" for kk in ks)
            lab = mc["label"]
            labc = {"上向き": "sx-up", "下向き": "sx-down"}.get(lab, "")
            evs = "".join(f'<span class="small">{e(z)}</span>' for z in mc["events"])
            chg = (f'<b class="{labc}">{lab}</b><span class="small">{sgn(mc["delta"], 3)}秒・{e(mc["why"])}</span>' if lab else
                   f'<span class="small">{e(mc["why"] or "—")}</span>')
            rows.append(f'<tr><td>{nm(R, t, p["name"], sub=False)}<span class="small">{p["motor"]}号機 {e(x.get("mg") or "")}</span></td>'
                        f'<td class="num"><b>{sgn(mc["avg"], 3)}</b><span class="small">{p.get("exrank", "—")}位・{mc["n"]}走</span></td>'
                        f'<td class="num sx-byday">{byday}</td><td class="sx-ev">{chg}{evs}</td></tr>')
        head = "・".join("初日" if kk == 1 else f"{kk}日" for kk in ks)
        table = ('<details class="sx-more"><summary>全部の艇を見る(' + str(len(ts)) + '艇)</summary><div class="scroll"><table class="sx-tbl sx-mtbl"><thead><tr>'
                 f'<th>選手・モーター</th><th class="num">節の平均</th><th class="num">日ごと<span class="small">{head}</span></th><th>変わり方・整備</th></tr></thead>'
                 f'<tbody>{"".join(rows)}</tbody></table></div></details>')
        secs.append('<section><h2>モーターの変化<span class="h2s">展示タイムが同じレースの平均より何秒速いか</span></h2>'
                    '<div class="sx-two"><div><h3 class="sx-up">上向き</h3><ul class="sx-fit">' + ("".join(li_chg(t) for t in up) or "<li class=sub>いません</li>") + "</ul></div>"
                    '<div><h3 class="sx-down">下向き</h3><ul class="sx-fit">' + ("".join(li_chg(t) for t in down) or "<li class=sub>いません</li>") + "</ul></div>"
                    + ('<div><h3>事故があった艇</h3><ul class="sx-fit">' + "".join(li_acc(t) for t in accs) + "</ul></div>" if accs else "")
                    + '<div><h3>この節で展示が速いモーター</h3><ul class="sx-fit">' + fast + "</ul></div></div>" + table
                    + f'<p class="note">変わり方は、一番最近の部品交換・新しいプロペラ・転覆などの前後(なければ節の前半と後半)で、展示の速さが{CHG:.2f}秒以上変わったら上向き・下向きにしています。'
                    '何もしていない艇でも13%はこのくらい動くので目安です。10月21日からの記録では、リング交換のあとに展示が速くなったのは49%(平均では変わらず)、'
                    '転覆・落水・沈没のあとは平均0.007秒、新しいプロペラのあとは平均0.02秒遅くなっています。</p></section>')
        # 相性
        fit = sorted([t for t in per if "fit" in per[t] and per[t]["mc"]["n"] >= 3], key=lambda t: -per[t]["fit"])
        good = [t for t in fit if per[t]["fit"] >= 1.0][:5]
        bad = [t for t in reversed(fit) if per[t]["fit"] <= -1.0][:5]

        def fit_li(t):
            p = per[t]
            x = R.get(t) or {}
            ex_now, ex0 = p["mc"]["avg"], x.get("mex", 0.0)
            res = f'・成績の上ぶれ{sgn(p["res"], 1)}点/走(これまで{sgn(x.get("mres"), 1)})' if p.get("res") is not None else ""
            return (f'<li><b>{nm(R, t, p["name"], sub=False)}</b> {p["motor"]}号機{gch(x.get("mg"))}'
                    f'<span class="sub">展示の速さ{sgn(ex_now, 3)}秒(これまで{sgn(ex0, 3)}){res}</span></li>')
        secs.append('<section><h2>モーターとの相性<span class="h2s">このモーターのこれまでと比べて</span></h2>'
                    + '<div class="sx-two"><div><h3>手の内に入れている</h3><ul class="sx-fit">' + ("".join(fit_li(t) for t in good) or "<li class=sub>まだいません</li>")
                    + '</ul></div><div><h3>合わせきれていない</h3><ul class="sx-fit">' + ("".join(fit_li(t) for t in bad) or "<li class=sub>まだいません</li>") + "</ul></div></div>"
                    '<p class="note">このモーターの前の60日(前の選手たち)の展示の速さ・成績の上ぶれ(コースと選手の腕前から見込むより何点良かったか)と、'
                    'この節の数字の差です。走数が少ないうちは小さく見ています。</p></section>')
        # スタート
        sts = sorted([t for t in per if per[t]["st"] is not None], key=lambda t: per[t]["st"])

        def st_row(i, t):
            p = per[t]
            d = (p["st"] - p["st0"]) if p["st0"] is not None else None
            fl = " ".join(v for v in ((f"F{p['f']}" if p["f"] else ""), (f"L{p['l']}" if p["l"] else "")) if v)
            return (f'<tr{" class=sx-top" if i < 3 else ""}><td class="num">{i + 1}</td><td>{nm(R, t, p["name"])}</td>'
                    f'<td class="num"><b>{stt(p["st"])}</b><span class="small">{p["nst"]}本</span></td>'
                    f'<td class="num">{stt(p["st0"])}<span class="small">{sgn(d, 2) if d is not None else ""}</span></td>'
                    f'<td class="num">{stt(p["est"])}</td><td class="num sx-fl">{e(fl)}</td></tr>')

        def st_table(rows):
            return ('<div class="scroll"><table class="sx-tbl"><thead><tr><th class="num">順</th><th>選手</th><th class="num">今節</th><th class="num">ふだん<span class="small">差</span></th>'
                    f'<th class="num">展示ST</th><th class="num">F・L</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
        rows = [st_row(i, t) for i, t in enumerate(sts)]
        more = (f'<details class="sx-more"><summary>11位から下を見る({len(rows) - 10}人)</summary>{st_table(rows[10:])}</details>' if len(rows) > 12 else "")
        secs.append('<section><h2>スタートの平均<span class="h2s">今節の本番のST</span></h2>' + st_table(rows[:10] if more else rows) + more
                    + '<p class="note">今節はフライング・出遅れを除いた本番のSTの平均、ふだんは直近1年の平均(下の小さい数字は今節との差)です。'
                    '展示STは展示の平均(フライングはF)。</p></section>')
    # 水面
    if W:
        base = None
        rows = []
        tot = {"n": 0, "c1": 0, "man": 0}
        for w in W:
            km = w["km"]
            kms = "・".join(f"{k}{v}" for k, v in sorted(km.items(), key=lambda kv: -kv[1]))
            mx = max((r["pay"] for r in w["man"]), default=None)
            dl = "初日" if w["k"] == 1 else f"{w['k']}日目"
            mxs = f'<span class="small">最高{mx:,}円</span>' if mx else ""
            med = f"{w['med']:,}円" if w["med"] else "—"
            rows.append(f'<tr><td>{dl}<span class="small">{w["d"].month}/{w["d"].day}</span></td>'
                        f'<td class="num">{w["c1"]}/{w["n"]}</td><td class="sx-km">{e(kms)}</td><td class="num">{len(w["man"])}{mxs}</td>'
                        f'<td class="num">{med}</td><td class="num">{wind_txt(w)}</td></tr>')
            tot["n"] += w["n"]
            tot["c1"] += w["c1"]
            tot["man"] += len(w["man"])
        c1rate = tot["c1"] / tot["n"] * 100 if tot["n"] else 0
        base = A.get("c1base")
        cmp = f"(この場のふだんは{base:.0f}%)" if base else ""
        secs.append('<section><h2>水面の傾向</h2>'
                    f'<p class="sub">この節の1コースの1着は{tot["c1"]}/{tot["n"]}({c1rate:.0f}%){cmp}。万舟(3連単1万円以上)は{tot["man"]}本。</p>'
                    '<div class="scroll"><table class="sx-tbl"><thead><tr><th>日</th><th class="num">1コース<br>1着</th><th>決まり手</th><th class="num">万舟</th>'
                    f'<th class="num">3連単の<br>真ん中</th><th class="num">風・波</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')
    return "".join(secs)


def pct_small(v) -> str:
    return f'<span class="small">{v}%</span>' if v else ""


def wind_txt(w: dict) -> str:
    a = w.get("wind")
    b = w.get("wave")
    s = []
    if a:
        s.append(f"{a[0]}〜{a[1]}m" if a[0] != a[1] else f"{a[0]}m")
    if b:
        s.append(f"{b[0]}〜{b[1]}cm" if b[0] != b[1] else f"{b[0]}cm")
    return "・".join(s) or "—"


def pane_zenken(sf: dict, model: dict | None) -> str:
    R = sf["roster"]
    z = sf.get("zenken") or {}
    first = parse_ymd(sf["first"].replace("-", ""))
    p0 = {t: x.get("p0", 0.0) for t, x in R.items() if not x.get("late")}
    ev = ((model or {}).get("eval") or {}).get("pre") or {}
    when = ("前検が終わって初日の出走表が出たときの数字です。" if not sf.get("late") else
            f"このページは{e(sf.get('created', ''))}に作りましたが、数字は初日({first.month}/{first.day})の前日までの成績から出しています。")
    secs = [f'<p class="sub">{when}</p>']
    evtxt = (f'直近{ev["n"]}節で確かめると、前検の1番手が優勝したのは{ev["top1"]:.0f}%、3番手までに優勝者がいたのは{ev["top3"]:.0f}%です。' if ev.get("n") else "")
    secs.append('<section><h2>優勝候補<span class="h2s">前検の見込み</span></h2>' + cand_list(R, p0, 8)
                + '<p class="note">選手の直近1年の着順点の平均・当地(この場)の上ぶれ・引いたモーターの評価(直近60日の成績の上ぶれと展示の速さ)から、'
                f'過去1年の節で学んだ式で出した優勝の見込みです。{evtxt}</p></section>')

    def m_li(t):
        x = R[t]
        bits = [f"成績の上ぶれ{sgn(x['mres'], 1)}点/走", f"展示が平均より{abs(x['mex']):.3f}秒{'速い' if x['mex'] >= 0 else '遅い'}"]
        if x.get("motor2"):
            bits.append(f"2連率{x['motor2']:.1f}%")
        return (f'<li><span class="sx-mno">{x["motor"]}<small>号機</small></span>{gch(x.get("mg"))}<b>{nm(R, t, sub=False)}</b>'
                f'<span class="sub">{e("・".join(bits))}(直近60日・{x.get("mn", 0)}走)</span></li>')
    secs.append('<section><h2>注目モーター</h2><ul class="sx-mot">' + ("".join(m_li(t) for t in z.get("motors", [])) or "<li class=sub>評価の高いモーターはありません</li>") + "</ul>"
                + ('<h3>気になる低調機</h3><ul class="sx-mot">' + "".join(m_li(t) for t in z.get("low", [])) + "</ul>" if z.get("low") else "")
                + '<p class="note">モーター評価(S〜E)は、直近60日の成績の上ぶれ(乗った選手の腕前とコースを差し引いたもの)・展示タイムの速さ・公式の2連率を、'
                'この場のモーターの中で比べたものです。</p></section>')
    pl = "".join(f'<li><b>{nm(R, p["t"])}</b><span class="sub">{e("・".join(p["tags"]))}</span></li>' for p in z.get("players", []))
    secs.append('<section><h2>注目選手</h2><ul class="sx-fit">' + (pl or "<li class=sub>とくにいません</li>") + "</ul>"
                '<p class="note">当地巧者はこの場での着順点が自分の平均より0.5以上高い選手(12走以上)、近況好調は前検の前30日の着順点が自分の平均より1.2以上高い選手(10走以上)です。'
                '優勝候補の上位3人は除いています。</p></section>')
    rows = []
    for t in sorted(R, key=lambda t: -(R[t].get("p0") or 0)):
        x = R[t]
        rows.append(f'<tr><td>{nm(R, t)}</td><td class="num">{x.get("age") or ""}</td><td class="num">{x.get("rate") or "—"}</td>'
                    f'<td class="num">{x.get("local") or "—"}</td><td class="num">{x.get("motor") or "—"}{gch(x.get("mg"))}{pct_small(x.get("motor2"))}</td>'
                    f'<td class="num">{x.get("boat") or "—"}{pct_small(x.get("boat2"))}</td></tr>')
    secs.append('<section><h2>出場選手<span class="h2s">' + f"{len(R)}人" + "</span></h2>"
                '<div class="scroll"><table class="sx-tbl"><thead><tr><th>選手</th><th class="num">年齢</th><th class="num">勝率</th><th class="num">当地</th>'
                f'<th class="num">モーター</th><th class="num">ボート</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
                '<p class="note">勝率・当地勝率・2連率は公式の出走表の数字です。並びは前検の優勝の見込みの順です。</p></section>')
    return "".join(secs)


def pane_day(sf: dict, G: dict, day: dict, rel: str) -> str:
    R = sf["roster"]
    rs = [r for r in day["races"] if r["done"]]
    days = G["days"]
    pts = {}
    wins = {}
    sts, accs, parts, props, tilts, exs = [], [], [], [], [], {}
    for r in rs:
        for y in r["boats"]:
            if y["rank"] == 1:
                wins.setdefault(y["toban"], []).append(r["no"])
            if y["pts"] is not None:
                a = pts.setdefault(y["toban"], [0, 0])
                a[0] += y["pts"]
                a[1] += 1
            if isinstance(y["st"], (int, float)) and 0 <= y["st"] < 1 and y["status"] not in ("F", "L", "欠"):
                sts.append((y["st"], y["toban"], y["name"], r["no"]))
            if y["status"] in ACCIDENT and y["status"] != "欠":
                accs.append(f'{r["no"]}R {nm(R, y["toban"], y["name"], sub=False)}({ACCIDENT[y["status"]]})')
            if y["parts"]:
                parts.append(f'{nm(R, y["toban"], y["name"], sub=False)}({y["motor"]}号機 {e("・".join(y["parts"]))})')
            if y["prop"] == "新":
                props.append(f'{nm(R, y["toban"], y["name"], sub=False)}({y["motor"]}号機)')
            if isinstance(y["tilt"], (int, float)) and y["tilt"] >= 1.0:
                tilts.append(f'{nm(R, y["toban"], y["name"], sub=False)}(+{y["tilt"]:.1f})')
            if y["exd"] is not None:
                exs.setdefault(y["toban"], []).append(y["exd"])
    c1 = sum(1 for r in rs for y in r["boats"] if y["rank"] == 1 and y["course"] == 1)
    man = [r for r in rs if r["pay"] and r["pay"] >= MAN]
    km = {}
    for r in rs:
        if r["kim"]:
            km[r["kim"]] = km.get(r["kim"], 0) + 1
    li = [f"1コースの1着は{c1}/{len(rs)}。決まり手は" + "・".join(f"{k}{v}" for k, v in sorted(km.items(), key=lambda kv: -kv[1])) + "。"]
    if man:
        mx = max(man, key=lambda r: r["pay"])
        li.append(f'万舟は{len(man)}本(一番高いのは{mx["no"]}R {mx["pay"]:,}円)。')
    else:
        li.append("万舟はなし。")
    multi = [t for t, v in wins.items() if len(v) >= 2]
    if multi:
        li.append("この日2勝: " + "、".join(nm(R, t, sub=False) for t in multi) + "。")
    best = sorted([(v[0], t) for t, v in pts.items() if v[1] >= 2 and v[0] >= 16], reverse=True)[:4]
    if best:
        li.append("この日よく走った選手: " + "、".join(f"{nm(R, t, sub=False)}({p}点)" for p, t in best) + "。")
    if sts:
        sts.sort()
        li.append("STが早かった: " + "、".join(f"{nm(R, t, n, sub=False)}({stt(s)}・{no}R)" for s, t, n, no in sts[:3]) + "。")
    fast = sorted([(sum(v) / len(v), t) for t, v in exs.items()], reverse=True)[:3]
    if fast:
        li.append("展示タイムが速かった: " + "、".join(f"{nm(R, t, sub=False)}(平均より{v:.2f}秒)" for v, t in fast) + "。")
    if accs:
        li.append("事故・F・出遅れ: " + "、".join(accs) + "。")
    if parts:
        li.append("部品交換: " + "、".join(parts) + "。")
    if props:
        li.append("新しいプロペラ: " + "、".join(props) + "。")
    if tilts:
        li.append("チルトを+1.0以上に跳ねた: " + "、".join(tilts) + "。")
    S = S_.standings(days, day["k"])
    ph = phase_of(day)
    return (f'<section><h2>{day_label(day)}のまとめ<span class="h2s">{day["d"].month}/{day["d"].day}{f"・{ph}" if ph else ""}</span></h2>'
            '<ul class="sx-list">' + "".join(f"<li>{x}</li>" for x in li) + "</ul></section>"
            f'<section><h2>レースの結果</h2>{results_table(R, day)}'
            f'<p class="note"><a href="{rel}{day["d"]:%Y%m%d}/{sf["code"]}/index.html">この日のレース一覧へ</a>(レースのページは今日と明日の分だけあります)</p></section>'
            f'<section><h2>{day_label(day)}までの得点率の順位<span class="h2s">上位18人</span></h2>{standings_table(R, S, days, day["k"], top=18, more=False)}</section>')


# ---------------------------------------------------------------- 組み立て

def status_of(sf: dict, G: dict, A: dict, today: dt.date) -> tuple:
    days = G["days"]
    first = parse_ymd(sf["first"].replace("-", ""))
    win = A["win"]
    R = sf["roster"]
    if win["stage"] == "done":
        c = win["champ"]
        return "優勝決定", f"{days[win['k'] - 1]['d'].month}/{days[win['k'] - 1]['d'].day}の優勝戦で、{(R.get(c) or {}).get('name', '')}が優勝しました。"
    k = A["kdone"]
    nxt = next((d for d in days if not d["complete"]), None)
    if k == 0:
        return "前検", f"前検が終わりました。初日は{first.month}/{first.day}です。"
    lab = day_label(days[k - 1])
    if nxt:
        ph = phase_of(nxt)
        return f"{lab}まで", f"{lab}まで終わりました。次は{nxt['d'].month}/{nxt['d'].day}の{day_label(nxt)}{f'({ph})' if ph else ''}です。"
    return f"{lab}まで", f"{lab}まで終わりました。"


def render(sf: dict, today: dt.date, progs: dict, model: dict | None, cache: dict, cat_tag) -> dict:
    """1つの節のページの中身 {title, desc, body, finished, tag, top}。"""
    code = sf["code"]
    vname = VENUES.get(code, code)
    G = S_.gather(sf, today, progs)
    first = parse_ymd(sf["first"].replace("-", ""))
    nxt_day = next((d for d in G["days"] if not d["complete"]), None)
    nxt = ((S_.load_prog(nxt_day["d"], progs) or {}).get("venues") or {}).get(code) if nxt_day else None
    cm = S_.course_means(code, first, cache)
    A = S_.analyze(sf, G, cm, model, nxt)
    vs = (load_json(DATA / "stadiums.json", {}) or {}).get(code) or {}
    A["c1base"] = ((vs.get("place") or [[None]])[0] or [None])[0]
    W = S_.water(G["days"])
    st_tag, st_txt = status_of(sf, G, A, today)
    comp = [d for d in G["days"] if d["complete"]]
    last_d = comp[-1]["d"] if comp else first
    span = f"{first.month}/{first.day}〜" + (f"{parse_ymd(sf['last'].replace('-', '')).month}/{parse_ymd(sf['last'].replace('-', '')).day}" if sf.get("last") else "")
    # 初日が終わるまでは「前検」だけ(まとめは前検の見込みと同じになるので出さない)
    tabs = ([("sum", "まとめ")] if comp else []) + [("zen", "前検")] + [(f"d{d['k']}", day_label(d)) for d in comp]
    default = "sum" if comp else "zen"
    tab_html = "".join(f'<button type="button" role="tab" data-tab="{k}"{" class=on" if k == default else ""}>{e(t)}</button>' for k, t in tabs)
    panes = ([f'<div class="pane" id="pane-sum">{pane_summary(sf, G, A, W, model, vname)}</div>'] if comp else []) + [
        f'<div class="pane" id="pane-zen"{"" if default == "zen" else " hidden"}>{pane_zenken(sf, model)}</div>']
    for d in comp:
        panes.append(f'<div class="pane sday" id="pane-d{d["k"]}" hidden>{pane_day(sf, G, d, "../")}</div>')
    today_link = ""
    if any(d["d"] == today for d in G["days"]):
        today_link = f'<a class="chip" href="../{today:%Y%m%d}/{code}/index.html">今日のレース一覧</a>'
    elif any(d["d"] == today + dt.timedelta(days=1) for d in G["days"]):
        t2 = today + dt.timedelta(days=1)
        today_link = f'<a class="chip" href="../{t2:%Y%m%d}/{code}/index.html">明日のレース一覧</a>'
    body = (f'<nav class="crumb"><a href="../today.html">今日のレース</a>›<a href="index.html">一節まとめ</a></nav>'
            f'<h1>{e(vname)}<span class="sx-h1s">一節まとめ</span></h1>'
            f'<div class="meta">{cat_tag(sf.get("grade"))}<span class="tag">{e(span)}</span><span class="tag">{e(st_tag)}</span><span class="sub">{e(sf.get("title", ""))}</span></div>'
            f'<p class="lead">{e(st_txt)}</p>{f"<div class=chips>{today_link}</div>" if today_link else ""}'
            f'<div class="tabs stabs" role="tablist">{tab_html}</div>' + "".join(panes))
    win = A["win"]
    top = None
    if win["stage"] == "done":
        top = ("優勝", (sf["roster"].get(win["champ"]) or {}).get("name", ""), None)
    elif win["p"]:
        t = max(win["p"], key=lambda t: win["p"][t])
        top = ("優勝候補", (sf["roster"].get(t) or {}).get("name", ""), win["p"][t])
    return {"title": f"{vname} 一節まとめ {span} {sf.get('title', '')}", "body": body, "finished": win["stage"] == "done",
            "last": last_d, "tag": st_tag, "top": top, "vname": vname, "grade": sf.get("grade"), "span": span, "stxt": st_txt,
            "desc": f"{vname}の{sf.get('title', '')}({span})の一節まとめ。優勝候補、得点率の順位、モーターの変化(整備・事故)、モーターとの相性、スタートの平均、日ごとの結果。"}


NOTES = ["一節まとめは、節(開催)の前検が終わって初日の出走表が出たときに作り、その日のレースが全部終わったあとのサイトの更新で日ごとのタブを足していきます。",
         "得点率・モーターの変化・スタートなどは、その日のレースが全部終わった日の分までで数えています(今日の途中のレースは、日のタブを足すときに入ります)。"]


def build_all(today: dt.date, progs: dict, page, write, cat_tag, cache: dict) -> tuple:
    """今の節(前検が終わったもの〜最終日から KEEP_AFTER 日まで)のページと一覧を作る。戻り値: (URL の並び, {(日付, 場): ページの道筋})。"""
    model = load_json(S_.MODEL, None)
    urls, links, cards = [], {}, []
    for p in sorted(S_.SETSU.glob("*.json")):
        sf = load_json(p, None)
        if not sf or not sf.get("roster"):
            continue
        first = parse_ymd(sf["first"].replace("-", ""))
        if first > today + dt.timedelta(days=1) or (today - first).days > 12:
            continue
        try:
            pg = render(sf, today, progs, model, cache, cat_tag)
        except Exception as ex:  # noqa: BLE001  1つの節で失敗しても、ほかのページは作る
            print("一節まとめを作れませんでした:", p.stem, ex)
            continue
        if pg["finished"] and (today - pg["last"]).days > S_.KEEP_AFTER:
            continue
        path = f"setsu/{p.stem}.html"
        write(path, page(f"{pg['title']} | 水面ノート", pg["desc"], pg["body"], 1, path,
                         '<script src="../assets/setsu.js"></script>', NOTES, mode="omote"))
        urls.append(path)
        d = first
        while d <= max(pg["last"], today + dt.timedelta(days=1)):
            links[(f"{d:%Y%m%d}", sf["code"])] = path
            d += dt.timedelta(days=1)
        cards.append((pg, path, sf))
    # 一覧
    items = []
    for pg, path, sf in sorted(cards, key=lambda c: (c[0]["finished"], c[2]["code"])):
        top = pg["top"]
        tl = (f'<span class="t">{e(top[0])}: {e(top[1])}' + (f" {pc(top[2])}" if top[2] is not None else "") + "</span>") if top else ""
        items.append(f'<a class="card sx-card{" done" if pg["finished"] else ""}" href="{path.split("/")[1]}"><span class="v">{e(pg["vname"])}</span>'
                     f'<span class="sx-ct">{cat_tag(pg["grade"])}<span class="tag">{e(pg["tag"])}</span></span>'
                     f'<span class="t">{e(sf.get("title", ""))} {e(pg["span"])}</span>{tl}</a>')
    body = ('<nav class="crumb"><a href="../today.html">今日のレース</a></nav><h1>一節まとめ</h1>'
            '<p class="lead">開催中の場の、前検から優勝戦までのまとめです。優勝候補・得点率の順位・モーターの変化・スタートの平均と、日ごとの結果を見られます。</p>'
            + (f'<div class="cards">{"".join(items)}</div>' if items else '<p class="sub">いま開催中の節はありません。</p>'))
    write("setsu/index.html", page("一節まとめ | 水面ノート", "開催中のボートレース場の一節まとめ。優勝候補、モーターの変化、スタートの平均、日ごとの結果。",
                                   body, 1, "setsu/index.html", "", NOTES, mode="omote"))
    urls.append("setsu/")
    return urls, links
