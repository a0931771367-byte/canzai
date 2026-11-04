#!/usr/bin/env python3
"""發文當天自動重查：依貼文.md 的「發文前查證」欄位，重新抓官網比對關鍵數字，有疑慮就擋下不發。

查證項目寫法（內容部在 posts.json 的 factcheck 或直接寫在貼文.md）：

    - [ ] 玉山 Pi 卡海外回饋 ｜來源：https://www.esunbank.com/... ｜必須出現：`3%`、`上限 500 元` ｜到期：2026-12-31

  - 來源：要抓的官網頁面（可多個網址，用空白隔開）
  - 必須出現：頁面上一定要找得到的字（回饋率、上限、活動日期），每個用反引號包起來
  - 到期：活動結束日，過了這天就擋下
  - 沒有網址的項目（例如「私訊自動回覆已設定好」）要有人確認後改成 `- [x]` 才會放行
  - 「## 發文前提」段落裡的 `- [ ]` 也一樣，沒打勾就不發

判定：
  PASS   全部項目通過，或本篇沒有引用銀行數字
  BLOCK  任何一項：頁面抓不到、必須出現的字找不到、活動已到期、未勾選的人工項目、
         或文案提到銀行／平台＋百分比卻沒有任何查證來源（安全網）

用法：
    python3 factcheck.py 貼文資料夾或貼文.md [更多…]       # 印出結果，BLOCK 時結束碼 2
    python3 factcheck.py "內容部/第1-2週"/* --report 報告.md   # 一次查整週，輸出給內容部的報告
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "snapshots")
TZ = dt.timezone(dt.timedelta(hours=8))

NO_NUMBERS = "沒有引用特定銀行數字"
BANKS = ["中信", "國泰", "台新", "玉山", "富邦", "永豐", "聯邦", "星展", "滙豐", "匯豐", "花旗", "第一銀", "華南", "兆豐",
         "合庫", "彰銀", "上海商銀", "遠東", "凱基", "元大", "新光", "台北富邦", "LINE Bank", "樂天", "將來銀行",
         "蝦皮", "momo", "PChome", "Uber Eats", "foodpanda", "街口", "全支付", "LINE Pay", "悠遊付", "Apple Pay"]


def norm(s):
    """比對前統一格式：全形轉半形、去空白與千分位逗號、統一波浪號與斜線。"""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("～", "~").replace("〜", "~").replace("－", "-").replace("／", "/")
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)
    return re.sub(r"\s+", "", s).lower()


def date_variants(v):
    """「11/1」也接受「11月1日」「2026/11/01」等寫法。"""
    out = {norm(v)}
    m = re.fullmatch(r"(?:(\d{4})[/.-])?(\d{1,2})[/.-](\d{1,2})", v.strip())
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        for f in (f"{mo}/{d}", f"{mo:02d}/{d:02d}", f"{mo}月{d}日", f"{mo:02d}月{d:02d}日", f"{mo}.{d}", f"{mo:02d}.{d:02d}"):
            out.add(norm(f))
            if y:
                out |= {norm(f"{y}/{f}"), norm(f"{y}年{f}"), norm(f"{int(y) - 1911}/{f}")}
    return out


# ---------------------------------------------------------------- 讀貼文.md
def parse_post(path):
    md = open(path, encoding="utf-8").read()
    title = md.splitlines()[0].lstrip("# ").strip() if md else path
    if not title or "undefined" in title:  # 標題沒填時用資料夾名稱
        title = os.path.basename(os.path.dirname(os.path.abspath(path)))
    sec = re.search(r"##\s*發文前查證\s*\n(.*?)(?=\n##\s|\Z)", md, re.S)
    items = []
    if sec:
        for line in sec.group(1).splitlines():
            m = re.match(r"\s*-\s*(\[( |x|X)\])?\s*(.+)", line)
            if not m or not m.group(3).strip():
                continue
            body = m.group(3)
            items.append({
                "raw": body.strip(),
                "checkbox": m.group(1) is not None,
                "checked": (m.group(2) or "").lower() == "x",
                "urls": re.findall(r"https?://[^\s｜|，,）)]+", body),
                "expect": re.findall(r"`([^`]+)`", body),
                "until": (re.search(r"到期[:：]\s*(\d{4}-\d{1,2}-\d{1,2})", body) or [None, None])[1],
            })
    # 「## 發文前提（罐子或社群部確認）」：沒打勾就不發
    pre = re.search(r"##\s*發文前提[^\n]*\n(.*?)(?=\n##\s|\Z)", md, re.S)
    if pre:
        for line in pre.group(1).splitlines():
            m = re.match(r"\s*-\s*\[( |x|X)\]\s*(.+)", line)
            if m:
                items.append({"raw": "發文前提：" + m.group(2).strip(), "checkbox": True,
                              "checked": m.group(1).lower() == "x", "urls": [], "expect": [], "until": None})
    cap = re.search(r"##\s*IG 文案.*?```\s*\n(.*?)```", md, re.S)
    caption = cap.group(1).strip() if cap else ""
    return {"path": path, "title": title, "items": items, "caption": caption, "has_section": bool(sec)}


# ---------------------------------------------------------------- 抓網頁
# 官網快照：雲端有網路白名單，抓不到的官網改讀罐子 Mac 每天抓好推到 GitHub 的快照（見 mac/README.md）
SNAP_BASE = os.environ.get("FACTCHECK_SNAPSHOT_BASE",
                           "https://raw.githubusercontent.com/a0931771367-byte/canzai/snapshots")
SNAP_MAX_HOURS = float(os.environ.get("FACTCHECK_SNAPSHOT_MAX_HOURS", "36"))
SOURCE = {}  # url → 「官網即時」或「Mac 快照 時間」，寫進報告
_IDX = None


def snapshot_key(url):
    return hashlib.sha1(url.strip().encode()).hexdigest()[:12]


def fetch_snapshot(url, timeout=20):
    """從 GitHub 讀 Mac 抓好的快照。回傳 (text, err)。超過 SNAP_MAX_HOURS 小時算太舊。"""
    global _IDX
    try:
        if _IDX is None:
            with urllib.request.urlopen(f"{SNAP_BASE}/index.json", timeout=timeout) as r:
                _IDX = json.load(r)
        ent = _IDX.get(url.strip())
        if not ent:
            return None, "Mac 快照清單裡沒有這個網址（下次 Mac 排程跑完才會有，見 --urls-out）"
        if not ent.get("fetched_at"):
            return None, f"Mac 也抓不到：{ent.get('error', '原因不明')}"
        age = (dt.datetime.now(TZ) - dt.datetime.fromisoformat(ent["fetched_at"])).total_seconds() / 3600
        if age > SNAP_MAX_HOURS:
            return None, f"Mac 快照太舊（{age:.0f} 小時前），Mac 排程可能沒跑"
        with urllib.request.urlopen(f"{SNAP_BASE}/pages/{ent['key']}.txt", timeout=timeout) as r:
            text = r.read().decode("utf-8", errors="replace")
        note = f"Mac 快照 {ent['fetched_at'][5:16].replace('T', ' ')}"
        if not ent.get("ok"):
            note += f"（最近一次重抓失敗：{ent.get('error', '')[:60]}）"
        SOURCE[url] = note
        return text, None
    except Exception as e:  # noqa: BLE001
        return None, f"讀不到 Mac 快照：{e}"


def fetch_text(url, timeout=30):
    """先直接抓官網；抓不到（雲端白名單擋住等）就讀 Mac 快照。"""
    text, err = fetch_live(url, timeout=15 if SNAP_BASE else timeout)
    if text is not None:
        SOURCE[url] = "官網即時"
        return text, None
    if SNAP_BASE:
        stext, serr = fetch_snapshot(url)
        if stext is not None:
            return stext, None
        return None, f"{err}；{serr}"
    return None, err


def fetch_live(url, timeout=30):
    """先用一般 HTTP 抓；內容太少（多半是 JavaScript 產生的頁面）就改用 Playwright 開瀏覽器抓。"""
    err, text = None, None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                   "AppleWebKit/537.36 Chrome/124 Safari/537.36",
                                                   "Accept-Language": "zh-TW,zh;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            enc = r.headers.get_content_charset() or "utf-8"
        page = raw.decode(enc, errors="replace")
        text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)))
        if len(norm(text)) > 150:
            return text, None
    except Exception as e:  # noqa: BLE001
        err = str(e)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(locale="zh-TW")
            pg.goto(url, timeout=timeout * 1000, wait_until="networkidle")
            text = pg.inner_text("body")
            b.close()
        return text, None
    except Exception as e:  # noqa: BLE001
        if text:  # 沒有 Playwright 也先用一般抓到的內容比對
            return text, None
        return None, err or str(e)


def snapshot(post_title, url, text):
    d = os.path.join(SNAP, re.sub(r"[^\w\-]+", "_", post_title)[:40])
    os.makedirs(d, exist_ok=True)
    h = hashlib.sha1(url.encode()).hexdigest()[:10]
    p = os.path.join(d, f"{dt.datetime.now(TZ):%Y%m%d}_{h}.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"{url}\n抓取時間：{dt.datetime.now(TZ).isoformat()}\n\n{text}")
    return p


# ---------------------------------------------------------------- 判定
def check_post(post, today=None):
    today = today or dt.datetime.now(TZ).date()
    results = []
    for it in post["items"]:
        r = {"項目": it["raw"], "結果": "PASS", "原因": ""}
        if NO_NUMBERS in it["raw"]:
            r["原因"] = "本篇未引用銀行數字"
        elif it["until"] and dt.date.fromisoformat(it["until"]) < today:
            r.update(結果="BLOCK", 原因=f"活動已於 {it['until']} 到期")
        elif it["urls"]:
            pages, fails = [], []
            for u in it["urls"]:
                text, err = fetch_text(u)
                if text is None:
                    fails.append(f"{u}（{err}）")
                else:
                    pages.append(norm(text))
                    r.setdefault("快照", []).append(snapshot(post["title"], u, text))
                    r.setdefault("來源", []).append(SOURCE.get(u, ""))
            if fails and not pages:
                r.update(結果="BLOCK", 原因="官網抓不到：" + "；".join(fails))
            else:
                blob = "".join(pages)
                missing = [v for v in it["expect"] if not any(x in blob for x in date_variants(v))]
                if missing:
                    r.update(結果="BLOCK", 原因="官網找不到：" + "、".join(f"「{m}」" for m in missing) + "（可能已改條件）")
                elif not it["expect"]:
                    r.update(結果="WARN", 原因="頁面抓得到，但沒有寫「必須出現」的數字，無法比對")
                else:
                    r["原因"] = "官網上找得到：" + "、".join(it["expect"])
                srcs = [x for x in r.get("來源", []) if x and x != "官網即時"]
                if srcs:
                    r["原因"] += "（依 " + "、".join(dict.fromkeys(srcs)) + "）"
                if fails:
                    r["原因"] += "；部分網址抓不到：" + "；".join(fails)
        elif it["checkbox"] and not it["checked"]:
            r.update(結果="BLOCK", 原因="沒有官網網址可自動查，需要人工確認後打勾 [x]")
        elif it["checkbox"] and it["checked"]:
            r["原因"] = "已人工確認"
        results.append(r)

    # 安全網：文案提到銀行／平台＋百分比，卻沒有任何官網來源
    cap = post["caption"]
    has_source = any(it["urls"] for it in post["items"])
    named = [b for b in BANKS if b.lower() in cap.lower()]
    if named and re.search(r"\d+(\.\d+)?\s*%", cap) and not has_source:
        demo = re.search(r"(示意|範例|舉例|假設)", cap)
        results.append({"項目": "（自動檢查）文案引用數字", "結果": "WARN" if demo else "BLOCK",
                        "原因": f"文案提到 {'、'.join(named)} 和百分比，但查證欄沒有官網網址"
                                + ("（文案有標示意／範例，先放行，請再確認）" if demo else "")})
    if not post["has_section"]:
        results.append({"項目": "（自動檢查）查證欄", "結果": "BLOCK", "原因": "貼文.md 沒有「發文前查證」段落"})
    verdict = "BLOCK" if any(r["結果"] == "BLOCK" for r in results) else "PASS"
    return {"貼文": post["title"], "檔案": post["path"], "判定": verdict, "明細": results,
            "查證時間": dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M")}


def resolve(p):
    return os.path.join(p, "貼文.md") if os.path.isdir(p) else p


def report_md(res):
    lines = [f"# 發文前自動重查報告（{dt.datetime.now(TZ):%Y-%m-%d %H:%M}）", ""]
    blocked = [r for r in res if r["判定"] == "BLOCK"]
    lines.append(f"共 {len(res)} 篇，**擋下 {len(blocked)} 篇**，放行 {len(res) - len(blocked)} 篇。")
    lines.append("")
    for r in res:
        lines.append(f"## {'⛔ 擋下' if r['判定'] == 'BLOCK' else '✅ 放行'}｜{r['貼文']}")
        for d in r["明細"]:
            mark = {"PASS": "✓", "WARN": "△", "BLOCK": "✗"}[d["結果"]]
            lines.append(f"- {mark} {d['項目']}：{d['原因']}")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="發文當天自動重查")
    ap.add_argument("posts", nargs="+", help="貼文資料夾或貼文.md")
    ap.add_argument("--report", help="輸出 Markdown 報告")
    ap.add_argument("--json", help="輸出 JSON 結果")
    ap.add_argument("--today", help="模擬日期 YYYY-MM-DD（測試用）")
    ap.add_argument("--urls-out", help="只輸出所有查證網址（給 Mac 快照排程的 urls.txt），不做檢查")
    a = ap.parse_args()
    if a.urls_out:
        urls = []
        for p in a.posts:
            f = resolve(p)
            if os.path.exists(f) and f.endswith(".md"):
                urls += [u for it in parse_post(f)["items"] for u in it["urls"]]
        old = [u.strip() for u in open(a.urls_out, encoding="utf-8")] if os.path.exists(a.urls_out) else []
        urls = sorted(set(u for u in old + urls if u.startswith("http")))
        open(a.urls_out, "w", encoding="utf-8").write("\n".join(urls) + "\n")
        print(f"{len(urls)} 個網址 → {a.urls_out}")
        return
    today = dt.date.fromisoformat(a.today) if a.today else None
    res = []
    for p in a.posts:
        f = resolve(p)
        if not os.path.exists(f):
            continue
        r = check_post(parse_post(f), today)
        res.append(r)
        print(f"{'⛔ BLOCK' if r['判定'] == 'BLOCK' else '✅ PASS '}  {r['貼文']}")
        for d in r["明細"]:
            if d["結果"] != "PASS":
                print(f"      [{d['結果']}] {d['原因']}")
    if a.report:
        open(a.report, "w", encoding="utf-8").write(report_md(res))
    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sys.exit(2 if any(r["判定"] == "BLOCK" for r in res) else 0)


if __name__ == "__main__":
    main()
