#!/usr/bin/env python3
"""罐仔 Threads 自動化（Threads API，graph.threads.net）。社群部「零人工曝光方案」第 2～4 項。

功能：
    python3 threads.py me                                   # 核對 token 是不是罐仔的 Threads 帳號
    python3 threads.py sync <IG 貼文資料夾> --base-url URL    # IG 發完後同步一份到 Threads（排程自動呼叫）
    python3 threads.py text <短文.md>                        # 發一則純文字短文
    python3 threads.py queue                                 # 發 內容部/Threads/ 裡時間到了的短文（排程自動呼叫）
    python3 threads.py replies [--hours 48]                  # 自家貼文底下的新回覆：分類、能自動回的就回、垃圾隱藏
    python3 threads.py search 信用卡回饋 雙12 -o out.json      # 關鍵字搜尋（見下方限制）
    以上都可加 --dry-run（只印流程，不打 API 寫入）。

權限：threads_basic、threads_content_publish、threads_read_replies、threads_manage_replies、threads_keyword_search
環境變數：THREADS_TOKEN（長效 token，60 天；refresh_token.yml 每週續期）

規則（社群部 11/15）：
- 只回「自己貼文底下」的回覆，不回陌生人的貼文、不追蹤、不按讚。
- 自動回覆只用 A 稱讚感謝、F 分享經驗兩類的範本（不含「私訊」字樣，Threads 沒有選卡機器人）；
  S 垃圾自動隱藏；其他類別（問特定卡、指正、負評、合作）不自動回，只在統計裡計數，交給每日排程的 Claude 處理。
- 公開 repo 的執行紀錄任何人都看得到：程式不印出別人的帳號名稱或回覆內容，只印數量與分類。
- 關鍵字搜尋在 threads_keyword_search 通過 App 審查前，只會搜到罐仔自己的貼文（官方文件寫明）。
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
API = "https://graph.threads.net/v1.0"
USERNAME = os.environ.get("THREADS_USERNAME", "canzai_money")
CONTENT = os.environ.get("CANZAI_CONTENT", os.path.join(ROOT, "內容部"))
LEDGER = os.path.join(HERE, "threads_ledger.json")
TZ = dt.timezone(dt.timedelta(hours=8))
MAX_CHARS = 450  # 官方上限 500，留一點給 emoji 的計算差異
AUTO_CATS = {"A", "F"}
SAFE_TEMPLATES = {
    "A": ["謝謝你！有想看的卡或國家，留言跟罐仔說～", "叮～入罐 🫙 先收藏起來，要用的時候再拿出來看！",
          "省下來的都是自己的 💰 下一篇也會很實用"],
    "F": ["這招好！謝謝分享，其他罐友可以參考 💡", "有道理欸，罐仔記下來，下次整理進去", "你也是省錢高手！謝謝分享 💰"],
}
sys.path.insert(0, os.path.join(ROOT, "程式部", "comments"))
sys.path.insert(0, os.path.join(ROOT, "程式部", "common"))


class ApiError(Exception):
    pass


def call(method, path, **params):
    params["access_token"] = os.environ["THREADS_TOKEN"]
    q = urllib.parse.urlencode(params)
    url = path if path.startswith("http") else f"{API}/{path}"
    req = urllib.request.Request(url + "?" + q) if method == "GET" else \
        urllib.request.Request(url, data=q.encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body).get("error", {}).get("message", "")
        except ValueError:
            msg = body[:200]
        raise ApiError(f"Threads API 錯誤 {e.code}：{msg}")


def paged(path, **params):
    res = call("GET", path, **params)
    while True:
        yield from res.get("data", [])
        nxt = res.get("paging", {}).get("next")
        if not nxt:
            return
        with urllib.request.urlopen(nxt, timeout=60) as r:
            res = json.load(r)


def me():
    return call("GET", "me", fields="id,username")


def gate(dry):
    if dry and not os.environ.get("THREADS_TOKEN"):
        return
    u = me().get("username")
    if u != USERNAME:
        raise SystemExit(f"⛔ THREADS_TOKEN 是 @{u} 的，不是 @{USERNAME}，不動作")


def load_ledger():
    return json.load(open(LEDGER, encoding="utf-8")) if os.path.exists(LEDGER) else {}


def save_ledger(led):
    with open(LEDGER, "w", encoding="utf-8") as f:
        json.dump(led, f, ensure_ascii=False, indent=1)


# ---------- 發文 ----------

def fit(text):
    text = text.strip()
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    i = max(cut.rfind("。"), cut.rfind("\n"), cut.rfind("！"), cut.rfind("？"))
    return (cut[:i + 1] if i > MAX_CHARS // 2 else cut[:MAX_CHARS - 1] + "…").strip()


def threads_text(folder):
    """貼文.md 有「## Threads 版」就用它；否則用 IG 文案，去掉 hashtag 行。回傳 (文字, 主題標籤)。"""
    md = os.path.join(folder, "貼文.md")
    src = open(md, encoding="utf-8").read() if os.path.exists(md) else ""
    m = re.search(r"^##+\s*Threads\s*版\s*\n(.*?)(?=^##+\s|\Z)", src, re.M | re.S)
    if m:
        body = re.sub(r"^```\w*\n|```$", "", m.group(1).strip(), flags=re.M).strip()
    else:
        cap = os.path.join(folder, "caption.txt")
        if os.path.exists(cap):
            body = open(cap, encoding="utf-8").read()
        else:
            sys.path.insert(0, os.path.join(ROOT, "程式部", "factcheck"))
            import factcheck
            body = factcheck.parse_post(md)["caption"]
    tags = re.findall(r"#([^\s#]+)", body)
    body = "\n".join(ln for ln in body.splitlines() if not re.fullmatch(r"\s*(#[^\s#]+\s*)+", ln))
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return fit(body), (tags[0] if tags else "")


def wait_ready(cid, dry, tries=30):
    if dry:
        return
    time.sleep(5)
    for _ in range(tries):
        st = call("GET", cid, fields="status,error_message")
        if st.get("status") in ("FINISHED", "PUBLISHED"):
            return
        if st.get("status") in ("ERROR", "EXPIRED"):
            raise ApiError(f"容器 {st.get('status')}：{st.get('error_message', '')}")
        time.sleep(10)
    raise ApiError("容器等太久還沒好")


def publish(dry, **kw):
    fake = iter(range(1000, 9999))

    def create(**p):
        if dry:
            print("  POST /me/threads", {k: (v[:40] + "…" if k == "text" and len(v) > 40 else v) for k, v in p.items()})
            return f"container_{next(fake)}"
        return call("POST", "me/threads", **p)["id"]

    media = kw.pop("media", [])
    vids = [m for m in media if m.endswith(".mp4")]
    imgs = [m for m in media if not m.endswith(".mp4")]
    if vids:
        cid = create(media_type="VIDEO", video_url=vids[0], **kw)
    elif len(imgs) >= 2:
        kids = [create(media_type="IMAGE", image_url=u, is_carousel_item="true") for u in imgs[:20]]
        for k in kids:
            wait_ready(k, dry)
        cid = create(media_type="CAROUSEL", children=",".join(kids), **kw)
    elif imgs:
        cid = create(media_type="IMAGE", image_url=imgs[0], **kw)
    else:
        cid = create(media_type="TEXT", **kw)
    if not dry:
        time.sleep(30)  # 官方建議建立容器後等約 30 秒再發
    wait_ready(cid, dry)
    if dry:
        print(f"  POST /me/threads_publish creation_id={cid}\n[dry-run] 未實際發文")
        return "dry"
    return call("POST", "me/threads_publish", creation_id=cid)["id"]


def sync(folder, base_url, dry):
    gate(dry)
    text, tag = threads_text(folder)
    url = lambda p: base_url.rstrip("/") + "/" + urllib.parse.quote(os.path.basename(p))
    vids = sorted(glob.glob(os.path.join(folder, "*.mp4")))
    imgs = sorted(p for p in glob.glob(os.path.join(folder, "*.jpg"))
                  if not os.path.basename(p).startswith("_") and not p.endswith("_cover.jpg"))
    media = [url(vids[0])] if vids else [url(p) for p in imgs]
    kw = dict(text=text, media=media)
    if tag:
        kw["topic_tag"] = tag
    tid = publish(dry, **kw)
    print("Threads 已發布，ID：", tid)
    return tid


def parse_short(path):
    """內容部/Threads/MMDD_HHMM_標題.md：檔名決定發文時間（台灣時間），內容就是貼文（可有一行 #主題）。"""
    m = re.match(r"(\d{2})(\d{2})_(\d{2})(\d{2})_", os.path.basename(path))
    if not m:
        return None, None, None
    now = dt.datetime.now(TZ)
    t = dt.datetime(now.year, int(m[1]), int(m[2]), int(m[3]), int(m[4]), tzinfo=TZ)
    if t - now > dt.timedelta(days=180):
        t = t.replace(year=now.year - 1)
    body = open(path, encoding="utf-8").read().strip()
    body = re.sub(r"\A---\n.*?\n---\n", "", body, flags=re.S)  # 允許 front matter 備註，不發出去
    tag = ""
    lines = body.splitlines()
    if lines and re.fullmatch(r"#[^\s#]+", lines[-1].strip()):
        tag = lines.pop().strip()[1:]
    return t, fit("\n".join(lines)), tag


def queue(dry, grace_h=2):
    led = load_ledger()
    now = dt.datetime.now(TZ)
    files = sorted(glob.glob(os.path.join(CONTENT, "Threads", "*.md")))
    sent = 0
    for p in files:
        key = "short:" + os.path.basename(p)
        if key in led:
            continue
        t, text, tag = parse_short(p)
        if not t or now < t:
            continue
        if not text:
            led[key] = {"skipped": "內容是空的"}
            continue
        if now > t + dt.timedelta(hours=grace_h):
            led[key] = {"skipped": "超過 2 小時沒發，略過"}
            continue
        if sent == 0:
            gate(dry)
        print(f"▶ Threads 短文 {os.path.basename(p)}")
        try:
            tid = publish(dry, text=text, **({"topic_tag": tag} if tag else {}))
        except ApiError as e:
            print(f"  失敗：{e}")
            continue
        if not dry:
            led[key] = {"published_at": dt.datetime.now(TZ).isoformat(timespec="minutes"), "id": tid}
        sent += 1
        break  # 一輪只發一則，避免洗版
    if not dry:
        save_ledger(led)
    print(f"Threads 短文：本輪發 {sent} 則")


# ---------- 自家貼文的回覆 ----------

def replies(hours, dry, max_posts=15):
    from classify import classify
    gate(dry)
    if dry and not os.environ.get("THREADS_TOKEN"):
        print("[dry-run] 沒有 THREADS_TOKEN，略過抓回覆")
        return
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    stats = {}
    usage = {}
    for i, post in enumerate(paged("me/threads", fields="id,timestamp", limit=25)):
        if i >= max_posts:
            break
        for r in paged(f"{post['id']}/replies", fields="id,text,username,timestamp,hide_status,has_replies", limit=50):
            if r.get("username") == USERNAME or r.get("hide_status") not in (None, "NOT_HUSHED", "UNHUSHED"):
                continue
            if dt.datetime.strptime(r["timestamp"], "%Y-%m-%dT%H:%M:%S%z") < since:
                continue
            # 已經回過就跳過（看這則底下有沒有罐仔自己的回覆，不用另外存狀態）
            if r.get("has_replies") and any(x.get("username") == USERNAME for x in
                                            paged(f"{r['id']}/replies", fields="username", limit=50)):
                continue
            cat, _ = classify(r.get("text", ""))
            stats[cat] = stats.get(cat, 0) + 1
            if cat == "S":
                if not dry:
                    call("POST", f"{r['id']}/manage_reply", hide="true")
                stats["已隱藏"] = stats.get("已隱藏", 0) + 1
            elif cat in AUTO_CATS and stats.get("已回覆", 0) < 20:  # 一輪最多回 20 則，避免像機器人洗版
                opts = SAFE_TEMPLATES[cat]
                k = (post["id"], cat)
                text = opts[usage.get(k, 0) % len(opts)]
                usage[k] = usage.get(k, 0) + 1
                try:
                    publish(dry, text=text, reply_to_id=r["id"])
                    stats["已回覆"] = stats.get("已回覆", 0) + 1
                except ApiError as e:
                    print(f"  回覆失敗：{e}")
    print(f"{'[dry-run] ' if dry else ''}Threads 新回覆分類：" + (json.dumps(stats, ensure_ascii=False) if stats else "沒有"))


# ---------- 關鍵字搜尋 ----------

def search(words, out, dry):
    gate(dry)
    if dry and not os.environ.get("THREADS_TOKEN"):
        print("[dry-run] 會搜尋：", "、".join(words))
        return
    res = {}
    for w in words:
        res[w] = [{k: p.get(k) for k in ("text", "permalink", "timestamp", "has_replies")}
                  for p in call("GET", "keyword_search", q=w, search_type="RECENT",
                                fields="id,text,permalink,timestamp,has_replies", limit=50).get("data", [])]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("關鍵字搜尋：" + "、".join(f"{w} {len(v)} 則" for w, v in res.items()) + f" → {out}")


def main():
    ap = argparse.ArgumentParser(description="罐仔 Threads 自動化")
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("me")
    s = sub.add_parser("sync"); s.add_argument("folder"); s.add_argument("--base-url", required=True)
    t = sub.add_parser("text"); t.add_argument("file")
    sub.add_parser("queue")
    r = sub.add_parser("replies"); r.add_argument("--hours", type=int, default=48)
    q = sub.add_parser("search"); q.add_argument("words", nargs="+"); q.add_argument("-o", default="threads_search.json")
    a = ap.parse_args()
    if not os.environ.get("THREADS_TOKEN") and not a.dry_run:
        print("還沒設定 THREADS_TOKEN，略過")
        return
    try:
        if a.cmd == "me":
            print(me())
        elif a.cmd == "sync":
            sync(a.folder, a.base_url, a.dry_run)
        elif a.cmd == "text":
            gate(a.dry_run)
            _, text, tag = parse_short(a.file) if parse_short(a.file)[0] else (None, fit(open(a.file, encoding="utf-8").read()), "")
            print("Threads 已發布，ID：", publish(a.dry_run, text=text, **({"topic_tag": tag} if tag else {})))
        elif a.cmd == "queue":
            queue(a.dry_run)
        elif a.cmd == "replies":
            replies(a.hours, a.dry_run)
        elif a.cmd == "search":
            search(a.words, a.o, a.dry_run)
    except ApiError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
