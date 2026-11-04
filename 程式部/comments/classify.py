#!/usr/bin/env python3
"""留言分類＋回覆草稿（規則版）。依 社群部/罐仔回覆口吻指南與範本.md 的 A～H 分類與範本。

輸入：ig_comments.py fetch 產生的 comments.json（或 --demo 範例）
輸出：待審 CSV（可直接匯入 Google 試算表）＋ JSON

規則版不花錢、可離線跑，負責「先分好、先起草」。每日排程裡 Claude 會再看一遍、
修正分類與潤飾草稿後才寫進試算表（見 README）。

用法：
    python3 classify.py comments.json -o out/
    python3 classify.py --demo -o out/
"""
import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
import sys  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "common"))
from ig_skills import humanize  # noqa: E402  /ig-human 去 AI 痕跡（含中文標點修正）
from zh_tw_check import check as zh_check, summary as zh_summary  # noqa: E402  繁中人味檢查

# /ig-reply 的六個分桶：決定回覆優先順序與長度
BUCKET = {"E": "KEYWORD", "X": "LEAD", "B": "QUESTION", "C": "QUESTION", "D": "SUBSTANCE", "F": "SUBSTANCE",
          "A": "SUPPORT", "H": "SUPPORT", "G": "NOISE", "S": "NOISE", "O": "SUPPORT"}
BUCKET_ORDER = ["KEYWORD", "LEAD", "SUBSTANCE", "QUESTION", "SUPPORT", "NOISE"]

# 細類 → (名稱, 大類, 處理方式)
CATS = {
    "A": ("稱讚感謝", "讚美", "auto_after_2w"),
    "B": ("問特定卡", "問題", "review"),
    "C": ("問國家刷卡", "問題", "auto_after_2w"),
    "D": ("指正錯誤", "問題", "urgent"),
    "E": ("要模板", "潛在客戶", "auto_after_2w"),
    "F": ("分享經驗", "讚美", "auto_after_2w"),
    "G": ("負評酸言", "負評", "review"),
    "H": ("標註朋友", "讚美", "like_only"),
    "X": ("轉給罐子", "潛在客戶", "owner"),  # 退款、付款、合作報價、檢舉法律、媒體
    "S": ("垃圾留言", "負評", "hide"),
    "O": ("其他", "其他", "review"),
}

COUNTRIES = ["日本", "韓國", "泰國", "越南", "新加坡", "香港", "澳門", "美國", "歐洲", "英國", "法國", "德國",
             "義大利", "澳洲", "紐西蘭", "加拿大", "馬來西亞", "菲律賓", "印尼", "峇里島", "沖繩", "大阪", "東京",
             "首爾", "釜山", "曼谷", "京都", "北海道", "福岡", "中國", "大陸"]

RULES = [  # 由上往下比對，先中先贏
    ("S", r"(加我|私我賺|日賺|月入|投資群|兼職|代操|飆股|追蹤互讚|互追|點我主頁|免費領取.*(幣|USDT)|t\.me/|line\.me/ti)"),
    ("X", r"(退款|退費|付款|扣款|刷不過|沒收到(信|檔案|連結)|合作|業配邀約|報價|商務|檢舉|告你|律師|法律|侵權|採訪|媒體)"),
    ("G", r"(幹|靠北|垃圾|白癡|智障|很蠢|好蠢|騙|詐騙|業配吧|業配文|收錢|置入|廣告吧|沒用|廢文|割韭菜|呵呵)"),
    ("D", r"(結束了|已經結束|過期|不是這樣|寫錯|錯了|有誤|更正|已經改|改成|調降|下修|沒有了|取消了|不對吧)"),
    ("E", r"(試算表|模板|範本|表格|檔案|怎麼(買|拿|下載|取得)|哪裡(買|拿|下載)|連結在哪|求連結|想要|\+1|＋1|求)"),
    ("F", r"(我都(刷|用)|我自己|我是用|我用|我上次|親測|實測|我也是|分享一下|我的經驗|我覺得.{0,6}(好用|不錯|划算))"),
    ("C", r"(去(" + "|".join(COUNTRIES) + r")|(" + "|".join(COUNTRIES) + r").{0,10}(刷|卡|回饋|推薦|哪張|嗎|呢|\?|？|做一篇|出一篇|篇))"),
    ("B", r"(值得辦|值不值得|好辦嗎|能辦嗎|要辦嗎|推薦.{0,4}卡|哪張(卡)?(好|比較|適合)|這張.{0,6}(\?|？|嗎)|.{1,8}卡.{0,6}(嗎|呢|\?|？)|回饋.{0,6}(多少|上限|怎麼算))"),
    ("A", r"(實用|感謝|謝謝|感恩|收藏|存起來|好棒|好讚|讚|太強|有用|清楚|好懂|學到|受用|厲害|愛了|推推|必收|可愛|❤|👍|🙏|😍)"),
]

QUESTION = re.compile(r"(\?|？|嗎|呢|請問|怎麼|如何|哪|多少|可以.{0,6}(嗎|呢))")

TEMPLATES = {
    "A": ["叮～入罐 🫙 先收藏，出國前再拿出來看！",
          "謝謝你！有想看的卡或國家，留言跟罐仔說～",
          "省下來的都是自己的 💰 下一篇也會很實用，記得追蹤喔"],
    "B": ["要看你平常刷哪裡最多！私訊罐仔「選卡」，我傳比較表給你",
          "好問題！每張卡強項不同，私訊罐仔「選卡」，我幫你對一下 💳",
          "罐仔有整理在前面的貼文，可以往前翻看看～細節依銀行公告為準"],
    "C": ["罐仔有整理{國家}的刷卡比較！私訊我「{國家}」直接傳給你 ✈️",
          "先看有沒有海外回饋加碼，再看上限；私訊「{國家}」給你重點整理～",
          "好問題，{國家}篇已經排進清單！先追蹤才不會錯過"],
    "D": ["謝謝你提醒！罐仔馬上查證更新 🙏",
          "感謝罐友提醒，罐仔去銀行官網確認後會更新貼文！",
          "謝謝留言！罐仔查證後回覆你，也會修正貼文 🙏"],
    "E": ["私訊罐仔「試算表」，自動傳給你 🫙",
          "主頁連結就有喔！有問題再私訊我",
          "在主頁第一個連結，買了有任何問題都可以問罐仔"],
    "F": ["這招好！謝謝分享，其他罐友可以參考 💡",
          "有道理欸，罐仔記下來，下次整理進去",
          "你也是省錢高手！謝謝分享 💰"],
    "G": ["每個人習慣不同啦，罐仔只是整理資訊給需要的人參考～",
          "這篇不是業配；如果有合作，罐仔一定會標示清楚",
          "謝謝你的意見，罐仔會繼續把資訊整理得更清楚"],
    "H": ["快拉朋友一起省 💰", "一起出國一起拿回饋 ✈️", ""],
    "X": ["收到！罐仔請負責人處理，會在 3 天內私訊回覆你 🙏"] * 3,
    "S": [""] * 3,
    "O": ["謝謝留言！罐仔看到囉 🫙", "收到～有問題都可以私訊罐仔", "謝謝你的留言 💰"],
}


def classify(text):
    t = text.strip()
    if re.fullmatch(r"(@[\w.]+\s*)+", t) or (t.count("@") >= 1 and len(re.sub(r"@[\w.]+", "", t).strip()) <= 6):
        return "H", "只有標註朋友"
    for cat, pat in RULES:
        m = re.search(pat, t)
        if m:
            if cat == "A" and QUESTION.search(t):  # 「好實用！請問…？」先算問題
                continue
            return cat, f"關鍵字「{m.group(0)}」"
    if QUESTION.search(t):
        return "B", "疑問句（未命中特定規則）"
    return "O", "未命中規則"


INSULT = re.compile(r"(幹|靠北|白癡|智障|垃圾|去死|腦殘)")
SPONSOR = re.compile(r"(業配|置入|收錢|廣告)")
TOPIC_REQ = re.compile(r"(做一篇|出一篇|也做|求.{0,4}篇)")


def draft(cat, text, post_id, usage):
    if cat == "G" and INSULT.search(text):
        return "", False  # 人身攻擊、髒話：不回，建議隱藏
    if cat == "G" and SPONSOR.search(text):
        return TEMPLATES["G"][1], False
    if cat == "C" and TOPIC_REQ.search(text):
        c = next((c for c in COUNTRIES if c in text), "這個國家")
        return f"好問題，{c}篇已經排進清單！先追蹤才不會錯過", False
    opts = TEMPLATES.get(cat, TEMPLATES["O"])
    if cat == "G":
        opts = [opts[0], opts[2]]
    # 同一篇貼文同一範本最多 3 次，輪流使用
    idx = min(range(len(opts)), key=lambda i: usage[(post_id, cat, i)])
    usage[(post_id, cat, idx)] += 1
    out = opts[idx]
    if "{國家}" in out:
        c = next((c for c in COUNTRIES if c in text), "這個國家")
        out = out.replace("{國家}", c)
    return out, usage[(post_id, cat, idx)] > 3


ACTION_TEXT = {
    "auto_after_2w": "勾 OK 才送（第 3 週起自動送）",
    "review": "草稿待審",
    "urgent": "⚠️ 先查證再回",
    "like_only": "不回（API 無法替留言按讚）",
    "owner": "🔔 轉給罐子",
    "hide": "建議隱藏",
}


def run(comments, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    usage = defaultdict(int)
    rows = []
    for c in comments:
        cat, why = classify(c.get("text", ""))
        name, big, action = CATS[cat]
        reply, overused = draft(cat, c.get("text", ""), c.get("media_id", ""), usage)
        if cat == "G" and not reply:
            action, why = "hide", why + "；含人身攻擊或髒話"
        zh_note = ""
        if reply:
            reply, _ = humanize(reply)
            zh = zh_check(reply)  # 中國用語、半形標點、中文 AI 腔，只提醒不改字
            zh_note = "人味檢查：" + zh_summary(zh) if zh else ""
        rows.append({
            "留言ID": c.get("id", ""), "時間": c.get("timestamp", ""), "貼文": c.get("permalink", c.get("media_id", "")),
            "帳號": c.get("username", ""), "留言": c.get("text", ""), "大類": big, "細類": f"{cat} {name}", "優先分桶": BUCKET[cat],
            "判斷依據": why, "處理": ACTION_TEXT[action], "回覆草稿": reply,
            "備註": "；".join(x for x in ["範本已用超過 3 次，請換說法" if overused else "", zh_note] if x), "OK": "", "已送出": "",
        })
    # /ig-reply：很多人問的同一題，改用 Reel 回覆（交給 /ig-reel 公式 #16）
    def qkey(r):
        t = r["留言"]
        if r["優先分桶"] != "QUESTION":
            return None
        c = next((c for c in COUNTRIES if c in t), None)
        if c:
            return "國家:" + c
        m = re.search(r"(年費|上限|值得辦|過件|門檻|回饋率|手續費|里程)", t)
        return "主題:" + m.group(1) if m else None
    groups = Counter(k for k in map(qkey, rows) if k)
    for r in rows:
        k = qkey(r)
        if k and groups[k] >= 3:
            r["備註"] = (r["備註"] + "；" if r["備註"] else "") + f"同一題 {groups[k]} 人問，建議用 /ig-reel 做成回覆 Reel"
    order = {"🔔 轉給罐子": 0, "⚠️ 先查證再回": 1}
    rows.sort(key=lambda r: (order.get(r["處理"], 2), BUCKET_ORDER.index(r["優先分桶"])))
    csv_path = os.path.join(out_dir, "留言回覆待審.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["留言ID"])
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(out_dir, "留言回覆待審.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    stats = Counter(r["大類"] for r in rows)
    bk = Counter(r["優先分桶"] for r in rows)
    print(f"共 {len(rows)} 則：" + "、".join(f"{k} {v}" for k, v in stats.most_common()))
    print("  /ig-reply 分桶：" + ", ".join(f"{b} {bk[b]}" for b in BUCKET_ORDER if bk[b]))
    print("輸出", csv_path)
    return rows


def main():
    ap = argparse.ArgumentParser(description="留言分類＋回覆草稿")
    ap.add_argument("comments", nargs="?", help="comments.json")
    ap.add_argument("--demo", action="store_true", help="用 examples/demo_comments.json")
    ap.add_argument("-o", "--out", default=os.path.join(HERE, "output"))
    a = ap.parse_args()
    path = os.path.join(HERE, "examples", "demo_comments.json") if a.demo or not a.comments else a.comments
    with open(path, encoding="utf-8") as f:
        run(json.load(f), a.out)


if __name__ == "__main__":
    main()
