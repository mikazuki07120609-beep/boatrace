"""共通の設定と小さな道具。"""
import datetime as dt
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"            # 公式ファイルを解凍したテキスト(リポジトリには入れない)
PROGRAM = DATA / "program"    # 番組表を読み取ったJSON(日付ごと)
RESULTS = DATA / "results"    # 競走成績を読み取ったJSON(日付ごと)
SITE = ROOT / "site"          # ページの部品(CSS・JS)
OUT = ROOT / "_site"          # できあがったサイト(公開用、リポジトリには入れない)

JST = dt.timezone(dt.timedelta(hours=9))

VENUES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島", "05": "多摩川", "06": "浜名湖",
    "07": "蒲郡", "08": "常滑", "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島", "17": "宮島", "18": "徳山",
    "19": "下関", "20": "若松", "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}

KIMARITE = ["逃げ", "捲り", "差し", "捲り差し", "抜き", "恵まれ"]


def today_jst() -> dt.date:
    return dt.datetime.now(JST).date()


def parse_ymd(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y%m%d").date()


def load_json(path: pathlib.Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def zen2han(s: str) -> str:
    """全角の英数字・記号を半角にする(全角スペースは半角に)。"""
    out = []
    for ch in s:
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        elif ch == "　":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _hm(t: str) -> str:
    h, m = t.split(":")
    return f"{int(h):02d}:{m}"


def _mins(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def parse_deadlines(page: str) -> dict:
    """公式サイトのレースのページ(出走表・直前情報・オッズ・結果)の上にある「締切予定時刻」の表から {"レース番号": "HH:MM"}。
    レースが遅れたときは、公式サイトがこの時刻を新しい締切に変える。読めなければ空。"""
    i = page.find("締切予定時刻")
    if i < 0:
        return {}
    t0, t1 = page.rfind("<table", 0, i), page.find("</table>", i)
    if t0 < 0 or t1 < 0:
        return {}
    j = i - t0
    tbl = page[t0:t1]
    nos = [int(x) for x in re.findall(r"rno=(\d+)", tbl[:j])]
    r0, r1 = tbl.rfind("<tr", 0, j), tbl.find("</tr>", j)
    times = re.findall(r"<td[^>]*>\s*(\d{1,2}:\d{2})\s*</td>", tbl[r0:r1] if r0 >= 0 and r1 > 0 else "")
    if not times or len(times) > 12:
        return {}
    if len(nos) != len(times):
        nos = list(range(1, len(times) + 1))
    return {str(n): _hm(t) for n, t in zip(nos, times)}


def merge_deadlines(prog_races: list, got: dict) -> dict:
    """読み取った締切 got のうち、番組表の締切と比べてありえる範囲(30分早い〜4時間遅い)のものだけ {"レース番号": "HH:MM"}。"""
    out = {}
    for r in prog_races:
        k, dl = str(r["no"]), r.get("deadline")
        t = got.get(k)
        if t and dl and -30 <= _mins(t) - _mins(dl) <= 240:
            out[k] = t
    return out


def deadline_of(race: dict, lv: dict | None) -> str | None:
    """そのレースの今の締切(公式サイトで変わっていればそちら。なければ番組表の締切)。"""
    return ((lv or {}).get("dl") or {}).get(str(race["no"])) or race.get("deadline")
