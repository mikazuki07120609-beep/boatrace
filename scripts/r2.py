#!/usr/bin/env python3
"""Cloudflare R2(S3互換のファイル置き場)へ、ページが読みに来るデータを送る。

直前情報・結果(data/live)・締切の変更(dl.json)・オッズ(odds ブランチ)は、これまでページを見ている人のブラウザが
GitHub のファイル置き場(raw.githubusercontent.com)から直接読んでいた。そこはサイトの配信用ではなく、
ログインしていない人のアクセスに回数制限があるので、見る人が増えても読めるよう、同じものを R2 にも置く
(ページは先に R2 を読み、だめなときだけ GitHub を読む)。

  - 秘密の値(R2_ACCOUNT_ID・R2_ACCESS_KEY_ID・R2_SECRET_ACCESS_KEY)がないときは何もしない(手元・設定前)
  - 中身が前に送ったものと同じファイルは送らない(実行中は送ったものの指紋を覚えておく)
  - 送れなくても取り込みは止めない(GitHub の方には今までどおり入る)。続けて失敗したら10分休む
  - 署名(AWS Signature Version 4)は標準ライブラリだけで作る

  python3 scripts/r2.py --check     # 秘密の値があれば、確かめ用の小さなファイルを1つ送ってみる
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import http.client
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

BUCKET = os.environ.get("R2_BUCKET") or "suimen-data"
REGION = "auto"
CACHE_CONTROL = "public, max-age=15"          # 見る人のブラウザは毎回読み直す(no-store)。Cloudflare の中継は15秒まで使い回す
CONTENT_TYPE = "application/json; charset=utf-8"
TIMEOUT = 20
PAUSE_AFTER = 3                                # 続けて何回失敗したら休むか
PAUSE_SEC = 600

_sent: dict[str, str] = {}                     # 送ったファイルの指紋(キー → sha256)
_fail = {"n": 0, "until": 0.0}
_last_err = [""]
_notes = {"ok": 0, "ng": 0}


def _annotate(level: str, msg: str) -> None:
    """GitHub Actions の中では、実行の注記(annotation)にも残す(実行の記録を読めないときも API で確かめられる)。
    うまくいったことは1回の実行で1度だけ、失敗は3度まで。"""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    kind = "ok" if level == "notice" else "ng"
    if _notes[kind] >= (1 if kind == "ok" else 3):
        return
    _notes[kind] += 1
    msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level} title=Cloudflare R2::{msg}", flush=True)


def enabled() -> bool:
    return all(os.environ.get(k) for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"))


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sign(method: str, host: str, path: str, headers: dict, payload_hash: str, access_key: str, secret_key: str,
         when: dt.datetime, region: str = REGION, service: str = "s3", query: str = "") -> str:
    """Authorization ヘッダーの値(AWS Signature Version 4)。headers には host と x-amz-date も入れておく。
    path はそのまま使う(S3 はパスを1回だけ符号化したものを署名する)。"""
    amz_date = when.strftime("%Y%m%dT%H%M%SZ")
    day = when.strftime("%Y%m%d")
    h = {k.lower().strip(): " ".join(str(v).strip().split()) for k, v in headers.items()}
    names = sorted(h)
    canonical = "\n".join([method, path, query, "".join(f"{k}:{h[k]}\n" for k in names), ";".join(names), payload_hash])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    k = _hmac(("AWS4" + secret_key).encode("utf-8"), day)
    for part in (region, service, "aws4_request"):
        k = _hmac(k, part)
    sig = hmac.new(k, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={';'.join(names)}, Signature={sig}"


def _host() -> str:
    return f"{os.environ['R2_ACCOUNT_ID'].strip()}.r2.cloudflarestorage.com"


def _secret() -> str:
    """Secret Access Key(64けたの16進)。Cloudflare の「Token value」が入っていたときは、
    その SHA-256 が Secret Access Key になる(Cloudflare の説明書どおり)ので、そこから作る。"""
    s = os.environ["R2_SECRET_ACCESS_KEY"].strip()
    if len(s) == 64 and all(c in "0123456789abcdef" for c in s):
        return s
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def shapes() -> str:
    """秘密の値の形(文字数と、16進かどうか)。値そのものは出さない。"""
    out = []
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        v = (os.environ.get(k) or "").strip()
        hexy = bool(v) and all(c in "0123456789abcdefABCDEF" for c in v)
        out.append(f"{k} {len(v)}文字・{'16進' if hexy else '16進以外もあり'}")
    return " / ".join(out)


def _put(conn: http.client.HTTPSConnection, key: str, body: bytes) -> tuple[bool, str]:
    host = _host()
    path = "/" + urllib.parse.quote(BUCKET, safe="") + "/" + urllib.parse.quote(key, safe="/-_.~")
    when = dt.datetime.now(dt.timezone.utc)
    ph = hashlib.sha256(body).hexdigest()
    ctype = "application/rss+xml; charset=utf-8" if key.endswith(".xml") else CONTENT_TYPE
    headers = {"host": host, "x-amz-date": when.strftime("%Y%m%dT%H%M%SZ"), "x-amz-content-sha256": ph,
               "content-type": ctype, "cache-control": "public, max-age=60" if key.endswith(".xml") else CACHE_CONTROL}
    headers["authorization"] = sign("PUT", host, path, headers, ph, os.environ["R2_ACCESS_KEY_ID"].strip(), _secret(), when)
    headers["content-length"] = str(len(body))
    conn.request("PUT", path, body=body, headers=headers)
    r = conn.getresponse()
    text = r.read().decode("utf-8", "replace")
    return 200 <= r.status < 300, f"{r.status} {text[:200]}"


def put_many(items: list[tuple[str, bytes]]) -> list[str]:
    """(キー, 中身) をまとめて送る(つなぎっぱなしで)。送れたキーの並びを返す。"""
    done: list[str] = []
    if not items:
        return done
    conn = None
    for key, body in items:
        for attempt in range(2):
            try:
                if conn is None:
                    conn = http.client.HTTPSConnection(_host(), timeout=TIMEOUT)
                ok, msg = _put(conn, key, body)
                if ok:
                    done.append(key)
                else:
                    _last_err[0] = f"{key} {msg}"
                    print(f"Cloudflare に送れませんでした: {key} {msg}", flush=True)
                break
            except (OSError, http.client.HTTPException) as ex:    # 切れたら1回だけつなぎ直す
                try:
                    conn and conn.close()
                except Exception:  # noqa: BLE001
                    pass
                conn = None
                if attempt:
                    _last_err[0] = f"{key} {ex}"
                    print(f"Cloudflare に送れませんでした: {key} {ex}", flush=True)
    try:
        conn and conn.close()
    except Exception:  # noqa: BLE001
        pass
    return done


def mirror(pairs: list[tuple[str, Path | bytes]]) -> int:
    """(キー, ファイルか中身) のうち、前に送ったものから変わったものだけ送る。送った数を返す。"""
    if not enabled() or time.time() < _fail["until"]:
        return 0
    todo, marks = [], {}
    for key, src in pairs:
        try:
            body = src if isinstance(src, bytes) else Path(src).read_bytes()
        except OSError:
            continue
        mark = hashlib.sha256(body).hexdigest()
        if _sent.get(key) != mark:
            todo.append((key, body))
            marks[key] = mark
    if not todo:
        return 0
    if len(todo) > 8:                          # 多いとき(実行の始めなど)は、4本に分けて並べて送る
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            done = [k for part in ex.map(put_many, [todo[i::4] for i in range(4)]) for k in part]
    else:
        done = put_many(todo)
    for key in done:
        _sent[key] = marks[key]
    if done:
        _annotate("notice", f"送れています(はじめの{len(done)}件。例: {done[0]})")
    if len(done) < len(todo):
        _annotate("warning", f"{len(todo) - len(done)}件を送れませんでした: {_last_err[0]}")
        _fail["n"] += 1
        if _fail["n"] >= PAUSE_AFTER:
            _fail["until"] = time.time() + PAUSE_SEC
            _fail["n"] = 0
            print(f"Cloudflare に続けて送れないので、{PAUSE_SEC // 60}分休みます(GitHub の方には入っています)", flush=True)
    else:
        _fail["n"] = 0
    if done:
        print(f"Cloudflare に{len(done)}件送りました", flush=True)
    return len(done)


def ensure(key: str, body: bytes) -> None:
    """まだ一度も送っていないキーに、中身を置いておく(ないファイルを読みに来られたときに、GitHub まで探しに行かせないため)。"""
    if key not in _sent:
        mirror([(key, body)])


def main() -> int:
    if "--check" in sys.argv:
        if not enabled():
            print("R2 の秘密の値がありません(R2_ACCOUNT_ID・R2_ACCESS_KEY_ID・R2_SECRET_ACCESS_KEY)")
            return 1
        print(("::notice title=Cloudflare R2 秘密の値の形::" if os.environ.get("GITHUB_ACTIONS") == "true" else "秘密の値の形: ") + shapes(), flush=True)
        body = json.dumps({"ok": True, "at": dt.datetime.now(dt.timezone.utc).isoformat()}).encode("utf-8")
        done = put_many([("check.json", body)])
        print("送れました: check.json" if done else "送れませんでした")
        _annotate("notice" if done else "error", "check.json を送れました" if done else f"送れませんでした: {_last_err[0]}")
        return 0 if done else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
