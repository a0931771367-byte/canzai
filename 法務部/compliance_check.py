#!/usr/bin/env python3
"""罐仔 發文前合規檢查（法務部）

用法：
  python3 compliance_check.py ../內容部/規格/第3週.json            # 檢查整週規格
  python3 compliance_check.py ../內容部/規格/第3週.json -o 報告.md   # 另存報告
規格中每篇可選填：
  "sponsored": true      業配（文案第一行必須有 #廣告／#合作）
  "affiliate": true      含推薦連結或折扣碼（文案必須有揭露句）
  "factcheck": [...]     有具體數字時的查證清單
結束代碼：有 FAIL 回傳 1（發文流程應停下），只有 WARN 回傳 0。
"""
import json, re, sys, argparse, pathlib

HERE = pathlib.Path(__file__).resolve().parent

def texts_of(post):
    parts = [post.get("title", ""), post.get("caption", ""), " ".join(post.get("hashtags", []))]
    for s in post.get("slides", []):
        for k in ("title", "sub", "body", "label", "say"):
            v = s.get(k)
            if isinstance(v, str): parts.append(v)
        for it in s.get("items", []) or []:
            parts.append(it if isinstance(it, str) else json.dumps(it, ensure_ascii=False))
        for row in s.get("rows", []) or []:
            parts.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(p for p in parts if p)

def strip_allowed(text, word, rules):
    for ctx in rules.get("allow_context", {}).get(word, []):
        text = text.replace(ctx, "")
    return text

def check(post, rules):
    fails, warns = [], []
    full = texts_of(post) + "\n" + (post.get("note") or "")
    cap = post.get("caption", "")
    for reason, words in rules["fail_words"].items():
        for w in words:
            if w in strip_allowed(full, w, rules):
                fails.append(f"出現「{w}」：{reason}")
    if re.search(rules["number_pattern"], full):
        if not any(d in full for d in rules["number_disclaimer_any"]) and not post.get("factcheck"):
            fails.append("有具體數字，但沒有「示意」「依銀行公告為準」或查證日")
    if post.get("sponsored"):
        first = cap.strip().splitlines()[0] if cap.strip() else ""
        if not any(t in first for t in rules["sponsored_first_line_any"]):
            fails.append("業配貼文：文案第一行必須有 #廣告 或 #合作（公平會薦證廣告規範），並開啟 IG「付費合作」標籤")
    if post.get("affiliate") or any(t in cap for t in rules["affiliate_triggers"]):
        if not any(t in cap for t in rules["affiliate_disclosure_any"]):
            fails.append("含連結／折扣碼：文案必須寫「含推薦連結，我們會拿到少量分潤」")
        elif not any(t in cap[:125] for t in rules["affiliate_disclosure_any"] + rules["sponsored_first_line_any"]):
            warns.append("揭露句在「...更多」之後，建議移到文案前 125 字內或圖卡上")
    for reason, pat in rules["warn_patterns"].items():
        if re.search(pat, full):
            warns.append(reason)
    return fails, warns

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--rules", default=str(HERE / "rules.json"))
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    rules = json.load(open(a.rules, encoding="utf-8"))
    spec = json.load(open(a.spec, encoding="utf-8"))
    lines = [f"# 合規檢查報告：{pathlib.Path(a.spec).name}", "", f"規則版本：{rules['version']}（法務部）", ""]
    nfail = 0
    for p in spec.get("posts", []):
        f, w = check(p, rules)
        nfail += len(f)
        status = "❌ FAIL" if f else ("⚠️ WARN" if w else "✅ PASS")
        lines.append(f"## {p.get('id','')} {p.get('title', p.get('slug',''))}：{status}")
        lines += [f"- ❌ {x}" for x in f] + [f"- ⚠️ {x}" for x in dict.fromkeys(w)]
        lines.append("")
    lines.append("> 這是規則比對，不是律師意見。WARN 項目由 Claude 依《合規檢查清單》再人工判斷一次。")
    report = "\n".join(lines)
    if a.out:
        pathlib.Path(a.out).write_text(report, encoding="utf-8")
    print(report)
    sys.exit(1 if nfail else 0)

if __name__ == "__main__":
    main()
