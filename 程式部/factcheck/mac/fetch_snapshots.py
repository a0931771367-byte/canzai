#!/usr/bin/env python3
"""在罐子的 Mac 上抓銀行／平台官網快照，推到 GitHub，雲端的 factcheck.py 從 GitHub 讀快照比對。

為什麼：雲端環境有網路白名單，每多一家銀行就要加一次；GitHub 本來就連得到，所以只要 Mac 把頁面抓好放上去，
雲端就不用再加任何白名單。Mac 是台灣 IP，也比較不會被銀行網站擋掉國外連線。

流程（launchd 每天 06:30、11:30 各跑一次，install_mac.sh 會設定好）：
  1. git pull 快照 repo 的 snapshots 分支（裡面的 urls.txt 是雲端依貼文.md 查證欄自動產生的網址清單）
  2. 一個一個抓（一般 HTTP，內容太少就用 Playwright，沒裝就略過）
  3. 寫 pages/<網址雜湊>.txt 和 index.json，commit 後 push

只用 Python 內建模組；Playwright 可選（pip3 install playwright && python3 -m playwright install chromium）。
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = os.path.expanduser(os.environ.get("CANZAI_SNAP_DIR", "~/canzai-snapshots"))
TZ = dt.timezone(dt.timedelta(hours=8))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def key(url):
    return hashlib.sha1(url.strip().encode()).hexdigest()[:12]


def fetch(url, timeout=30):
    text, err = None, None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            page = r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")
        text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)))
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n", text)
        if len(re.sub(r"\s", "", text)) > 150:
            return text, "http"
    except Exception as e:  # noqa: BLE001
        err = str(e)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(locale="zh-TW", user_agent=UA)
            pg.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            text = pg.inner_text("body")
            b.close()
        return text, "browser"
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        err = err or str(e)
    if text:
        return text, "http"
    raise RuntimeError(err or "抓不到內容")


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)


def main():
    if not os.path.isdir(os.path.join(REPO, ".git")):
        sys.exit(f"找不到快照 repo：{REPO}（先跑 install_mac.sh）")
    git("pull", "--rebase", "-q", "origin", "snapshots")
    urls_file = os.path.join(REPO, "urls.txt")
    urls = []
    if os.path.exists(urls_file):
        urls = [u.strip() for u in open(urls_file, encoding="utf-8") if u.strip().startswith("http")]
    urls = list(dict.fromkeys(urls))
    idx_path = os.path.join(REPO, "index.json")
    idx = json.load(open(idx_path, encoding="utf-8")) if os.path.exists(idx_path) else {}
    os.makedirs(os.path.join(REPO, "pages"), exist_ok=True)
    now = dt.datetime.now(TZ).isoformat(timespec="seconds")
    ok = bad = 0
    for u in urls:
        k = key(u)
        try:
            text, how = fetch(u)
            with open(os.path.join(REPO, "pages", f"{k}.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            idx[u] = {"key": k, "fetched_at": now, "ok": True, "how": how, "chars": len(text)}
            ok += 1
        except Exception as e:  # noqa: BLE001
            prev = idx.get(u, {})
            idx[u] = {**prev, "key": k, "last_try": now, "ok": False, "error": str(e)[:300]}
            bad += 1
        print(("✅ " if idx[u]["ok"] else "❌ ") + u)
    json.dump(idx, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode:
        git("commit", "-q", "-m", f"快照 {now}：{ok} 成功、{bad} 失敗")
        r = git("push", "-q", "origin", "HEAD:snapshots")
        print("已推到 GitHub" if r.returncode == 0 else f"push 失敗：{r.stderr.strip()}")
    print(f"完成：{ok} 成功、{bad} 失敗")


if __name__ == "__main__":
    main()
