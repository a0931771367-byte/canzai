#!/usr/bin/env python3
"""IG 留言抓取與回覆（Instagram API with Instagram Login，graph.instagram.com）。

權限：instagram_business_basic、instagram_business_manage_comments
環境變數：IG_TOKEN（與 ig_publish 共用同一個 App 與 token）

用法：
    python3 ig_comments.py fetch --hours 24 -o comments.json      # 抓最近 24 小時新留言
    python3 ig_comments.py send 待審.json                          # 送出「OK」欄打勾的回覆、隱藏建議隱藏的留言
    python3 ig_comments.py send 待審.json --dry-run
"""
import argparse
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import ig_api  # noqa: E402

API = "https://graph.instagram.com/v23.0"
# token 統一存放：環境變數 IG_TOKEN 優先，否則讀 數據部/.ig_token（續期由數據部每週一的排程統一處理）
_TOKEN_FILE = os.environ.get("IG_TOKEN_FILE", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "數據部", ".ig_token"))
if not os.environ.get("IG_TOKEN") and os.path.exists(_TOKEN_FILE):
    os.environ["IG_TOKEN"] = open(_TOKEN_FILE).read().strip()
# 上線時間：這之前發的舊貼文（@air_pudding 時期）留言一律不抓、不自動回覆（社群部 11/3 要求）
LAUNCH = dt.datetime.fromisoformat(os.environ.get("CANZAI_LAUNCH", "2026-11-04T01:00:00+08:00"))
OK_MARKS = {"ok", "v", "✓", "✔", "y", "yes", "true", "1", "好", "是"}


def call(method, path, **params):
    params["access_token"] = os.environ["IG_TOKEN"]
    q = urllib.parse.urlencode(params)
    url = f"{ig_api.base(os.environ['IG_TOKEN'])}/{path}" if path.startswith("http") is False else path
    req = urllib.request.Request(url + "?" + q) if method == "GET" else \
        urllib.request.Request(url, data=q.encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"API 錯誤 {e.code}：{e.read().decode()}")


def paged(path, **params):
    res = call("GET", path, **params)
    while True:
        yield from res.get("data", [])
        nxt = res.get("paging", {}).get("next")
        if not nxt:
            return
        with urllib.request.urlopen(nxt, timeout=60) as r:
            res = json.load(r)


def fetch(hours, max_posts=20):
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out = []
    for i, m in enumerate(paged(f"{ig_api.uid(os.environ['IG_TOKEN'])}/media", fields="id,caption,permalink,timestamp,comments_count", limit=25)):
        if i >= max_posts:
            break
        if dt.datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z") < LAUNCH:
            break  # 由新到舊排，碰到上線前的舊貼文就停
        if not m.get("comments_count"):
            continue
        for c in paged(f"{m['id']}/comments", fields="id,text,username,timestamp", limit=50):
            ts = dt.datetime.strptime(c["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
            if ts >= since:
                out.append(dict(c, media_id=m["id"], media_ts=m["timestamp"], permalink=m.get("permalink", ""),
                                caption=(m.get("caption") or "")[:60]))
    return out


def send(rows, dry):
    sent = hidden = 0
    for r in rows:
        if r.get("已送出"):
            continue
        cid = r["留言ID"]
        mts = r.get("media_ts") or r.get("貼文時間")
        if mts and dt.datetime.strptime(mts, "%Y-%m-%dT%H:%M:%S%z") < LAUNCH:
            print("略過舊貼文的留言", cid)
            continue
        if r.get("處理") == "建議隱藏" and str(r.get("OK", "")).strip().lower() in OK_MARKS | {""}:
            print("隱藏", cid, r["留言"][:20])
            if not dry:
                call("POST", cid, hide="true")
            r["已送出"] = "已隱藏"; hidden += 1
        elif str(r.get("OK", "")).strip().lower() in OK_MARKS and r.get("回覆草稿"):
            print("回覆", cid, "→", r["回覆草稿"])
            if not dry:
                call("POST", f"{cid}/replies", message=r["回覆草稿"])
            r["已送出"] = dt.date.today().isoformat(); sent += 1
    print(f"{'[dry-run] ' if dry else ''}回覆 {sent} 則，隱藏 {hidden} 則")
    return rows


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--hours", type=int, default=24); f.add_argument("-o", default="comments.json")
    s = sub.add_parser("send"); s.add_argument("file"); s.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.cmd == "fetch":
        cs = fetch(a.hours)
        json.dump(cs, open(a.o, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"抓到 {len(cs)} 則新留言 → {a.o}")
    else:
        rows = json.load(open(a.file, encoding="utf-8"))
        rows = send(rows, a.dry_run)
        if not a.dry_run:
            json.dump(rows, open(a.file, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
