"""公式の番組表(B)・競走成績(K)のテキストを読み取って、扱いやすい形(dict)にする。"""
import re

from common import zen2han

KIM_MAP = {"逃げ": "逃げ", "まくり": "捲り", "捲り": "捲り", "差し": "差し", "まくり差し": "捲り差し",
           "捲り差し": "捲り差し", "抜き": "抜き", "恵まれ": "恵まれ"}

RE_B_RACE = re.compile(r"^\s*(\d{1,2})R\s+(.+?)\s+H(\d{3,4})m\s+電話投票締切予定\s*(\d{1,2}:\d{2})")
RE_B_ENTRY = re.compile(
    r"^([1-6]) (\d{4})(.{4})(\d{2})(.{2})(\d{2})([AB][12])(.{5})(.{6})(.{5})(.{6})(.{3})(.{6})(.{3})(.{6})(.*)$")
RE_K_RACE = re.compile(
    r"^\s*(\d{1,2})R\s+(.+?)\s+H(\d{3,4})m\s+(\S+)\s+風\s+(\S+)\s+(\d+)m\s+波\s+(\d+)cm")
RE_K_ENTRY = re.compile(r"^\s{2}(\S{1,2})\s+([1-6])\s(\d{4})\s(.{8})\s*(\d+)\s+(\d+)\s+(.*)$")
RE_DAY = re.compile(r"第\s*(\d+)日")


def _num(s: str):
    s = s.strip()
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def _name(s: str) -> str:
    """'鎌倉　涼' -> '鎌倉 涼'、'山　口　　　　剛' -> '山口 剛' のように整える。"""
    s = s.replace("　", " ").strip()
    if "  " in s:  # 成績ファイルは1文字ずつ空白で区切られ、姓と名の間が広い
        parts = [p.replace(" ", "") for p in re.split(r" {2,}", s) if p.strip()]
        return " ".join(parts)
    return s


def _blocks(text: str, kind: str):
    """'23BBGN' ... '23BEND' の場ごとのかたまりに分ける。"""
    code, lines = None, []
    for line in text.split("\n"):
        m = re.match(rf"^(\d{{2}}){kind}BGN", line)
        if m:
            code, lines = m.group(1), []
            continue
        if code and re.match(rf"^{code}{kind}END", line):
            yield code, lines
            code = None
            continue
        if code:
            lines.append(line)


def _series(lines: list[str], marker: str):
    title, day = "", None
    for i, line in enumerate(lines):
        if marker in line:
            for nxt in lines[i + 1:i + 6]:
                if nxt.strip():
                    title = nxt.replace("　", " ").strip()
                    break
        m = RE_DAY.search(zen2han(line))
        if m and day is None:
            day = int(m.group(1))
    return zen2han(title).strip(), day


def parse_program(text: str) -> dict:
    venues = {}
    for code, lines in _blocks(text, "B"):
        title, day = _series(lines, "番組表")
        races, cur = [], None
        for line in lines:
            h = RE_B_RACE.match(zen2han(line))
            if h:
                cur = {"no": int(h.group(1)), "name": h.group(2).strip(), "distance": int(h.group(3)),
                       "deadline": h.group(4), "entries": []}
                races.append(cur)
                continue
            m = RE_B_ENTRY.match(line)
            if m and cur is not None:
                g = m.groups()
                rest = g[15]
                cur["entries"].append({
                    "waku": int(g[0]), "toban": g[1], "name": _name(g[2]), "age": int(g[3]),
                    "branch": g[4].replace("　", "").strip(), "weight": int(g[5]), "cls": g[6],
                    "rate": _num(g[7]), "rate2": _num(g[8]), "local": _num(g[9]), "local2": _num(g[10]),
                    "motor": _num(g[11]), "motor2": _num(g[12]), "boat": _num(g[13]), "boat2": _num(g[14]),
                    # 今節成績: 1日2文字(1日2走まで)×6日。例 '5 266' -> ['5', '26', '6']
                    "series": [c.strip() for c in (zen2han(rest[1:13])[i:i + 2] for i in range(0, 12, 2)) if c.strip()],
                })
        races = [r for r in races if r["entries"]]
        if races:
            venues[code] = {"title": title, "day": day, "races": races}
    return {"venues": venues}


def parse_results(text: str) -> dict:
    venues = {}
    for code, lines in _blocks(text, "K"):
        title, day = _series(lines, "競走成績")
        races, cur = [], None
        for line in lines:
            h = RE_K_RACE.match(line)
            if h:
                cur = {"no": int(h.group(1)), "name": h.group(2).replace("　", " ").strip(),
                       "distance": int(h.group(3)), "weather": h.group(4).replace("　", "").strip(),
                       "wind_dir": h.group(5).replace("　", "").strip(), "wind": int(h.group(6)),
                       "wave": int(h.group(7)), "kimarite": None, "entries": []}
                races.append(cur)
                continue
            if cur is not None and "ﾚｰｽﾀｲﾑ" in line:
                k = line.split("ﾚｰｽﾀｲﾑ", 1)[1].replace("　", "").strip()
                cur["kimarite"] = KIM_MAP.get(k, k or None)
                continue
            m = RE_K_ENTRY.match(line)
            if m and cur is not None:
                g = m.groups()
                rank_raw = g[0]
                rank = int(rank_raw) if rank_raw.isdigit() else None
                toks = g[6].split()
                ex = _num(toks[0]) if toks and re.fullmatch(r"\d\.\d{2}", toks[0]) else None
                course = int(toks[1]) if len(toks) > 1 and re.fullmatch(r"[1-6]", toks[1]) else None
                st, flying = None, False
                if len(toks) > 2:
                    sm = re.fullmatch(r"([FL])?(\d?\.\d{2})", toks[2])
                    if sm:
                        st = float("0" + sm.group(2) if sm.group(2).startswith(".") else sm.group(2))
                        flying = sm.group(1) == "F"
                time_ = toks[3] if len(toks) > 3 and re.fullmatch(r"\d\.\d{2}\.\d", toks[3]) else None
                cur["entries"].append({
                    "rank": rank, "status": None if rank else rank_raw, "waku": int(g[1]), "toban": g[2],
                    "name": _name(g[3]), "motor": int(g[4]), "boat": int(g[5]), "ex": ex,
                    "course": course, "st": st, "flying": flying, "time": time_,
                })
        races = [r for r in races if r["entries"]]
        if races:
            venues[code] = {"title": title, "day": day, "races": races}
    return {"venues": venues}


if __name__ == "__main__":
    import json
    import sys

    path, kind = sys.argv[1], sys.argv[2]
    text = open(path, encoding="utf-8").read()
    data = parse_program(text) if kind == "B" else parse_results(text)
    print(json.dumps(data, ensure_ascii=False)[:1500])
