#!/usr/bin/env python3
"""把 內容部/文章/*.md 轉成網站的搜尋文章頁（guide/<slug>.html），並更新 guide/index.html、sitemap.xml、robots.txt。

文章格式（內容部寫）：
    ---
    slug: subscription-cost            # 網址：guide/subscription-cost.html（英文小寫、數字、連字號）
    title: 訂閱一年花多少？3 步驟算出你每年被扣的錢
    description: 搜尋結果下面那一行，80 字內
    date: 2026-11-20                   # 發布日；未來日期的文章不會上架
    updated: 2026-11-20                # 選填
    ---
    內文用 Markdown：## 小標、### 小小標、段落、- 清單、1. 編號清單、| 表格 |、**粗體**、[連結](網址)、> 引言。
    ## 常見問題 底下用「### 問題」＋段落寫的，會另外輸出成 Google 的 FAQ 結構化資料。

每篇文末自動加：免費訂閱盤點表、年度省錢表的連結框，以及「依官方公告為準」的聲明。
用法：python3 程式部/site/build_guides.py [--today 2026-11-20]
"""
import argparse
import datetime as dt
import glob
import html
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "內容部", "文章")
OUT = os.path.join(ROOT, "guide")
SITE = "https://a0931771367-byte.github.io/canzai/"
TZ = dt.timezone(dt.timedelta(hours=8))

CSS = """:root{--bg:#FFF8EC;--card:#FFFFFF;--text:#1E2A4A;--sub:#56607A;--line:#EFE6D6;--brand:#2EC4B6;--brand-dark:#1FA397;--good-bg:#E3F6F4}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#1A2340;--card:#243055;--text:#FFF8EC;--sub:#C9CFDF;--line:#34416B;--good-bg:#1D3F4B}}
:root[data-theme="dark"]{--bg:#1A2340;--card:#243055;--text:#FFF8EC;--sub:#C9CFDF;--line:#34416B;--good-bg:#1D3F4B}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei","Heiti TC",sans-serif;line-height:1.8;-webkit-text-size-adjust:100%}
main{max-width:760px;margin:0 auto;padding:16px 16px 48px}
h1{font-size:26px;line-height:1.4;margin:12px 0 6px;font-weight:900}
h2{font-size:20px;margin:28px 0 8px;font-weight:900}
h3{font-size:17px;margin:20px 0 6px;font-weight:800}
p{margin:0 0 12px}
ul,ol{margin:0 0 12px;padding-left:1.4em}
li{margin:4px 0}
blockquote{margin:0 0 12px;padding:8px 14px;border-left:4px solid var(--brand);background:var(--card);border-radius:0 10px 10px 0}
.tbl{overflow-x:auto;margin:0 0 12px}
table{width:100%;border-collapse:collapse;font-size:15px;background:var(--card)}
th,td{border-bottom:1px solid var(--line);padding:8px 6px;text-align:left;vertical-align:top}
th{color:var(--sub);font-weight:700}
.meta,.note{color:var(--sub);font-size:14px}
.cta{background:var(--good-bg);border-radius:14px;padding:14px 16px;margin:24px 0 12px}
.cta a.buy{display:inline-block;background:var(--brand);color:#fff;text-decoration:none;font-weight:900;padding:10px 18px;border-radius:12px;margin:6px 8px 0 0}
.cta a.buy:hover{background:var(--brand-dark)}
.list a{font-weight:700}
a{color:var(--brand-dark)}
hr{border:0;border-top:1px solid var(--line);margin:20px 0}
footer{color:var(--sub);font-size:13px;margin-top:24px}"""

HEAD = """<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="{ogtype}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:locale" content="zh_TW">
{ld}<style>
{css}
</style>
</head>
<body>
<main>
"""

FOOT = """<footer>
  <p>罐仔 @canzai_money　·　<a href="../privacy.html">隱私說明</a>　·　<a href="../free.html">免費訂閱盤點表</a>　·　<a href="../sheet.html">年度省錢表</a>　·　<a href="../">免費刷卡試算器</a></p>
</footer>
</main>
</body>
</html>
"""

CTA = """<div class="cta">
  <p><b>想直接算自己的？</b>罐仔做了一張免費的訂閱盤點表，5 分鐘算出一年被扣多少；整年的預算、記帳、信用卡回饋上限追蹤，在年度省錢表裡。</p>
  <a class="buy" href="../free.html">免費訂閱盤點表</a><a class="buy" href="../sheet.html">看年度省錢表</a>
</div>
<p class="note">本文是一般資訊整理，不是個人財務建議，也沒有業配。信用卡與各項費用的條件，以銀行或官方最新公告為準。</p>
"""


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)

    def link(m):
        text, url = m.group(1), m.group(2)
        ext = url.startswith("http") and not url.startswith(SITE)
        if not re.match(r"(https?:|mailto:|/|#|\.\./)", url):
            url = "../" + url  # 文章在 guide/ 底下，free.html 這類相對連結要往上一層
        return f'<a href="{html.escape(url)}"' + (' rel="noopener nofollow"' if ext else "") + f">{text}</a>"
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)


def md_to_html(md):
    out, lines, i = [], md.splitlines(), 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1
            continue
        if re.fullmatch(r"\s*(-{3,}|\*{3,})\s*", ln):
            out.append("<hr>")
            i += 1
            continue
        m = re.match(r"(#{2,4})\s+(.*)", ln)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            i += 1
            continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            t = "<div class=\"tbl\"><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr></thead><tbody>"
            t += "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
            out.append(t + "</tbody></table></div>")
            continue
        if re.match(r"[-*]\s+|\d+[.)]\s+", ln):
            tag = "ol" if re.match(r"\d", ln) else "ul"
            items = []
            pat = r"\s*\d+[.)]\s+" if tag == "ol" else r"\s*[-*]\s+"
            while i < len(lines) and re.match(pat, lines[i]):
                items.append(re.sub(r"\s*([-*]|\d+[.)])\s+", "", lines[i], count=1))
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        if ln.startswith(">"):
            q = []
            while i < len(lines) and lines[i].startswith(">"):
                q.append(lines[i].lstrip("> ").rstrip())
                i += 1
            out.append("<blockquote>" + "<br>".join(inline(x) for x in q) + "</blockquote>")
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"(#{2,4}\s|\||[-*]\s|\d+[.)]\s|>|\s*-{3,}\s*$)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>" + "<br>".join(inline(x) for x in para) + "</p>")
    return "\n".join(out)


def faq(md):
    m = re.search(r"^##\s*常見問題\s*$(.*?)(?=^##\s|\Z)", md, re.M | re.S)
    if not m:
        return []
    qa = re.findall(r"^###\s+(.+?)\s*$\n(.*?)(?=^###\s|\Z)", m.group(1), re.M | re.S)
    return [(q.strip(), re.sub(r"\s+", " ", re.sub(r"[*`>#|]", "", a)).strip()) for q, a in qa if a.strip()]


def parse(path):
    src = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n(.*)", src, re.S)
    if not m:
        raise SystemExit(f"{path}：開頭缺少 --- 區塊")
    meta = dict(re.findall(r"^(\w+):\s*(.+?)\s*$", m.group(1), re.M))
    for k in ("slug", "title", "description", "date"):
        if not meta.get(k):
            raise SystemExit(f"{path}：缺少 {k}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["slug"]):
        raise SystemExit(f"{path}：slug 只能用英文小寫、數字、連字號")
    body = re.sub(r"\A\s*#\s+.*\n", "", m.group(2))  # 內文第一行若是 # 標題就略過（標題用 title）
    return meta, body


def page(meta, body):
    url = f"{SITE}guide/{meta['slug']}.html"
    upd = meta.get("updated", meta["date"])
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": meta["title"], "description": meta["description"],
           "datePublished": meta["date"], "dateModified": upd, "inLanguage": "zh-TW", "mainEntityOfPage": url,
           "author": {"@type": "Organization", "name": "罐仔"}, "publisher": {"@type": "Organization", "name": "罐仔"}}]
    qa = faq(body)
    if qa:
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qa]})
    ldtxt = "".join('<script type="application/ld+json">' + json.dumps(x, ensure_ascii=False).replace("</", "<\\/") + "</script>\n" for x in ld)
    h = HEAD.format(title=html.escape(meta["title"]), desc=html.escape(meta["description"]), url=url, ogtype="article", ld=ldtxt, css=CSS)
    h += '<p class="note"><a href="./">← 罐仔省錢文章</a></p>\n'
    h += f"<article>\n<h1>{html.escape(meta['title'])}</h1>\n<p class=\"meta\">罐仔整理　·　{meta['date']}" + \
         (f"（更新 {upd}）" if upd != meta["date"] else "") + "</p>\n"
    h += md_to_html(body) + "\n</article>\n" + CTA + FOOT
    return h


def build(today):
    os.makedirs(OUT, exist_ok=True)
    posts = []
    for p in sorted(glob.glob(os.path.join(SRC, "*.md"))):
        if os.path.basename(p).startswith(("_", "README")):
            continue
        meta, body = parse(p)
        if meta["date"] > today:
            print(f"（{meta['date']} 才上架）{meta['slug']}")
            continue
        with open(os.path.join(OUT, meta["slug"] + ".html"), "w", encoding="utf-8") as f:
            f.write(page(meta, body))
        posts.append(meta)
        print(f"✓ guide/{meta['slug']}.html　{meta['title']}")
    posts.sort(key=lambda m: m["date"], reverse=True)
    idx = HEAD.format(title="罐仔省錢文章", desc="罐仔整理的上班族省錢解答：訂閱、記帳、信用卡回饋上限、年費、年終獎金。",
                      url=SITE + "guide/", ogtype="website", ld="", css=CSS)
    idx += '<p class="note"><a href="../">← 回免費試算器</a></p>\n<h1>罐仔省錢文章</h1>\n<ul class="list">\n'
    idx += "".join(f'  <li><a href="{m["slug"]}.html">{html.escape(m["title"])}</a><br><span class="note">{html.escape(m["description"])}</span></li>\n' for m in posts)
    idx += "</ul>\n" + FOOT
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(idx)
    pages = [("", None), ("sheet.html", None), ("free.html", None), ("guide/", None)] + \
            [(f"guide/{m['slug']}.html", m.get("updated", m["date"])) for m in posts]
    with open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for loc, mod in pages:
            f.write(f"  <url><loc>{SITE}{loc}</loc>" + (f"<lastmod>{mod}</lastmod>" if mod else "") + "</url>\n")
        f.write("</urlset>\n")
    print(f"guide/index.html、sitemap.xml 已更新（{len(posts)} 篇）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=dt.datetime.now(TZ).strftime("%Y-%m-%d"))
    build(ap.parse_args().today)
