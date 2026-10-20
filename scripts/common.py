"""共通の設定と小さな道具。"""
import datetime as dt
import json
import pathlib

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
