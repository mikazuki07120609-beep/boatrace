#!/usr/bin/env python3
"""大荒れ注意になったレースを X(旧Twitter)に投稿する(リポジトリの秘密の値に X のキーを入れたときだけ)。

  秘密の値: X_API_KEY・X_API_SECRET(アプリのキー)、X_ACCESS_TOKEN・X_ACCESS_SECRET(投稿するアカウントのアクセストークン。読み書きの権限)
  1日の投稿の上限: 環境変数 X_DAILY_MAX(リポジトリの変数。ふだん 3)
  X API は使った分だけの料金(2026年10月の公式の料金表で、URL を含む投稿は1件 $0.20)。上限 × 日数 ぶんの料金がかかる

scripts/predlog.js が data/live/YYYYMMDD/ura.json の alerts に足した「展示のあとで大荒れ注意になったレース」のうち、
まだ投稿していないもの(締切前で、知らせてから15分以内)を投稿し、投稿したら alerts の x に時刻を残す。
本文には買い目を入れない(万舟の見込み・この場のふだんの万舟率・裏本線と、レースのページのURL)。
X API v2 の POST /2/tweets を、OAuth 1.0a(HMAC-SHA1)の署名で呼ぶ(標準ライブラリだけ)。
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from common import DATA, load_json, save_json

API = "https://api.x.com/2/tweets"
SITE_URL = os.environ.get("SITE_URL") or "https://suimennote.com/"
JST = dt.timezone(dt.timedelta(hours=9))
FRESH_MIN = 15


def _q(s: str) -> str:
    return urllib.parse.quote(str(s), safe="-._~")


def oauth_header(method: str, url: str, params: dict, ck: str, cs: str, tk: str, ts: str, nonce: str | None = None, stamp: str | None = None) -> str:
    """OAuth 1.0a の Authorization ヘッダー。params はクエリと(フォームのときは)本文の値(JSON の本文は署名に入れない)。"""
    oa = {"oauth_consumer_key": ck, "oauth_nonce": nonce or secrets.token_hex(16), "oauth_signature_method": "HMAC-SHA1",
          "oauth_timestamp": stamp or str(int(time.time())), "oauth_token": tk, "oauth_version": "1.0"}
    allp = {**params, **oa}
    pstr = "&".join(f"{_q(k)}={_q(allp[k])}" for k in sorted(allp))
    base = "&".join([method.upper(), _q(url), _q(pstr)])
    key = f"{_q(cs)}&{_q(ts)}"
    oa["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_q(k)}="{_q(v)}"' for k, v in sorted(oa.items()))


def keys() -> tuple | None:
    k = [os.environ.get(n, "").strip() for n in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")]
    return tuple(k) if all(k) else None


def text_of(a: dict, ymd: str) -> str:
    url = f"{SITE_URL}ura/{ymd}/{a['v']}/{a['no']:02d}.html"
    line = ""
    if a.get("ul"):
        who = (a.get("ulName") or "").split(" ")[0].split("　")[0]
        line = f"\n裏本線: {a['ul'][1]}コース{who}の{a['ul'][2]}"
    return (f"【大荒れ注意】{a.get('vn') or a['v']}{a['no']}R" + (f"({a['dl']}締切)" if a.get("dl") else "")
            + f"\n万舟の見込み {round(a['pm'] * 100)}%(この場のふだん {round(a['base'] * 100)}%){line}"
            + f"\n{url}\n#ボートレース #万舟 #{a.get('vn') or ''}")


def post(text: str, k: tuple) -> tuple[bool, str]:
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Authorization": oauth_header("POST", API, {}, *k), "Content-Type": "application/json", "User-Agent": "suimen-note/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 200 <= r.status < 300, r.read().decode("utf-8", "replace")[:200]
    except urllib.error.HTTPError as ex:
        return False, f"{ex.code} {ex.read().decode('utf-8', 'replace')[:200]}"
    except Exception as ex:  # noqa: BLE001
        return False, str(ex)[:200]


def run(day: dt.date | None = None) -> int:
    """まだ投稿していない大荒れ注意を投稿する。投稿した数を返す。キーがなければ何もしない。"""
    k = keys()
    if not k:
        return 0
    now = dt.datetime.now(JST)
    day = day or now.date()
    ymd = f"{day:%Y%m%d}"
    path = DATA / "live" / ymd / "ura.json"
    U = load_json(path, None)
    if not U or not U.get("alerts"):
        return 0
    cap = int(os.environ.get("X_DAILY_MAX") or 3)
    done = sum(1 for a in U["alerts"] if a.get("x"))
    hm = now.strftime("%H:%M")
    n = 0
    for a in U["alerts"]:
        if a.get("x") or a.get("xe", 0) >= 2 or done >= cap:
            continue
        if a.get("dl") and hm >= a["dl"]:
            continue                                   # 締切を過ぎたものは投稿しない
        try:
            t0 = dt.datetime.combine(day, dt.time.fromisoformat(a.get("at") or "00:00"), JST)
            if (now - t0).total_seconds() > FRESH_MIN * 60:
                continue
        except ValueError:
            pass
        ok, msg = post(text_of(a, ymd), k)
        if ok:
            a["x"] = hm
            done += 1
            n += 1
            print(f"X に投稿しました: {a['k']}", flush=True)
        else:
            a["xe"] = a.get("xe", 0) + 1
            print(f"X に投稿できませんでした: {a['k']} {msg}", flush=True)
    if n or any(a.get("xe") for a in U["alerts"]):
        save_json(path, U)
    return n


if __name__ == "__main__":
    sys.exit(0 if run() >= 0 else 1)
