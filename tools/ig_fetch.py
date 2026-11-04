#!/usr/bin/env python3
"""罐仔 IG 週數據抓取（Instagram API with Instagram Login，免費）。

用法：
  IG_TOKEN=<長效權杖> python3 ig_fetch.py --since 2026-11-02 --until 2026-11-09
權杖也可放在 /mnt/project-files/數據部/.ig_token（一行）。
每次執行會先嘗試延長權杖（長效權杖 60 天到期，執行時自動續期，不必再找罐子）。
輸出：週報/raw/<since>.json，並在 IG數據.csv 追加一列。
需要雲端環境網路允許 graph.instagram.com。
"""
import argparse, csv, json, os, re, sys, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://graph.instagram.com"
VER = os.environ.get("IG_API_VERSION", "v23.0")
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, ".ig_token")
OUT = os.environ.get("IG_OUT_DIR", HERE)  # GitHub Actions 時指到 repo 的 data/ig
TW = timezone(timedelta(hours=8))


def get(path, **params):
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def load_token():
    t = os.environ.get("IG_TOKEN")
    if not t and os.path.exists(TOKEN_FILE):
        t = open(TOKEN_FILE).read().strip()
    if not t:
        sys.exit("找不到 IG 權杖：設定 IG_TOKEN 或建立 .ig_token")
    return t


def refresh(token):
    try:
        new = get("refresh_access_token", grant_type="ig_refresh_token", access_token=token)["access_token"]
        with open(TOKEN_FILE, "w") as f:
            f.write(new)
        os.chmod(TOKEN_FILE, 0o600)
        return new
    except Exception as e:  # 剛建立 24 小時內的權杖不能續期，照用舊的
        print(f"權杖續期略過：{e}", file=sys.stderr)
        return token


VOTE_A = re.compile(r"^\s*[AaＡａ](\b|$|[\s!！。.~～])")
VOTE_B = re.compile(r"^\s*[BbＢｂ](\b|$|[\s!！。.~～])")


def count_votes(media_id, token):
    """統計 Reel 片尾 A/B 投票：每個帳號只算第一票。需要留言讀取權限。"""
    votes, seen, after = {"A": 0, "B": 0}, set(), None
    while True:
        params = dict(fields="text,username", limit=50, access_token=token)
        if after:
            params["after"] = after
        r = get(f"{VER}/{media_id}/comments", **params)
        for c in r.get("data", []):
            u, t = c.get("username"), c.get("text", "")
            if u in seen:
                continue
            if VOTE_A.match(t):
                votes["A"] += 1; seen.add(u)
            elif VOTE_B.match(t):
                votes["B"] += 1; seen.add(u)
        after = r.get("paging", {}).get("cursors", {}).get("after") if r.get("paging", {}).get("next") else None
        if not after:
            return votes


def ts(d):
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=TW).timestamp())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    a = ap.parse_args()
    token = load_token() if os.environ.get("IG_SKIP_REFRESH") else refresh(load_token())

    me = get(f"{VER}/me", fields="user_id,username,followers_count,media_count", access_token=token)

    acct = {}
    for m in ["reach", "views", "accounts_engaged", "profile_views", "total_interactions", "follows_and_unfollows"]:
        try:
            r = get(f"{VER}/me/insights", metric=m, period="day", metric_type="total_value",
                    since=ts(a.since), until=ts(a.until), access_token=token)
            acct[m] = r["data"][0]["total_value"]
        except Exception as e:
            acct[m] = f"無法取得：{e}"

    posts = []
    media = get(f"{VER}/me/media", limit=50, access_token=token,
                fields="id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count")
    for p in media.get("data", []):
        t = datetime.strptime(p["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(TW).strftime("%Y-%m-%d")
        if not (a.since <= t < a.until):
            continue
        ins = {}
        for metrics in ["reach,views,likes,comments,shares,saved,total_interactions,follows,profile_visits",
                        "reach,views,likes,comments,shares,saved,total_interactions"]:
            try:
                r = get(f"{VER}/{p['id']}/insights", metric=metrics, access_token=token)
                ins = {d["name"]: d["values"][0]["value"] for d in r["data"]}
                break
            except Exception as e:  # 某些格式不支援 follows／profile_visits，退回基本指標
                ins = {"error": str(e)}
        # Reels 另抓平均觀看時長與略過率（略過率 ≈ 1 − 3 秒留存）
        if p.get("media_product_type") == "REELS":
            for m in ["ig_reels_avg_watch_time", "reels_skip_rate"]:
                try:
                    r = get(f"{VER}/{p['id']}/insights", metric=m, access_token=token)
                    ins[m] = r["data"][0]["values"][0]["value"]
                except Exception:
                    ins[m] = None
            try:
                ins["votes"] = count_votes(p["id"], token)
                with open(os.path.join(OUT, "投票結果.csv"), "a", newline="") as f:
                    csv.writer(f).writerow([t, p.get("permalink", ""), ins["votes"]["A"], ins["votes"]["B"],
                                            datetime.now(TW).strftime("%Y-%m-%d %H:%M")])
            except Exception as e:
                ins["votes"] = f"無法取得：{e}"
        posts.append({**p, "date": t, "insights": ins})

    out = {"fetched_at": datetime.now(TW).isoformat(), "since": a.since, "until": a.until,
           "account": me, "account_insights": acct, "posts": posts}
    os.makedirs(os.path.join(OUT, "週報", "raw"), exist_ok=True)
    with open(os.path.join(OUT, "週報", "raw", f"{a.since}.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    def v(k):
        x = acct.get(k)
        return x.get("value", "") if isinstance(x, dict) else ""
    with open(os.path.join(OUT, "IG數據.csv"), "a", newline="") as f:
        csv.writer(f).writerow([a.since, a.until, me.get("followers_count", ""), "", v("reach"), v("views"),
                                v("accounts_engaged"), v("profile_views"), len(posts), "IG API"])
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
