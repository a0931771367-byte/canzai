"""接上法務部的發文前合規檢查（法務部/compliance_check.py ＋ rules.json）。

規則不寫死：每次執行都重新載入法務部的 compliance_check.py 與 rules.json（法務部每月 1 日更新）。
找貼文規格的順序：
  1. 貼文資料夾裡的 post.json（單篇規格）
  2. 內容部/規格/*.json 裡 id_slug 和資料夾名稱相同的那篇
  3. 都找不到：從 貼文.md 組出文案與腳本文字來檢查（無法得知 sponsored/affiliate，從 md 裡的「業配：是」判斷）
"""
import glob
import importlib.util
import json
import os
import re

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEGAL = os.path.join(PROJECT, "法務部")
SPEC_DIR = os.path.join(PROJECT, "內容部", "規格")


def _load():
    path = os.path.join(LEGAL, "compliance_check.py")
    spec = importlib.util.spec_from_file_location("compliance_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with open(os.path.join(LEGAL, "rules.json"), encoding="utf-8") as f:
        rules = json.load(f)
    return mod, rules


def find_post(folder):
    pj = os.path.join(folder, "post.json")
    if os.path.exists(pj):
        return json.load(open(pj, encoding="utf-8")), "post.json"
    name = os.path.basename(os.path.normpath(folder))
    for sp in sorted(glob.glob(os.path.join(SPEC_DIR, "*.json"))):
        try:
            data = json.load(open(sp, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in data.get("posts", []):
            if f"{p.get('id', '')}_{p.get('slug', '')}" == name:
                return p, os.path.basename(sp)
    md_path = os.path.join(folder, "貼文.md")
    if os.path.exists(md_path):
        md = open(md_path, encoding="utf-8").read()
        cap = re.search(r"##\s*IG 文案.*?```\s*\n(.*?)```", md, re.S)
        script = re.search(r"##\s*腳本[^\n]*\n(.*?)(?=\n##\s|\Z)", md, re.S)
        post = {"title": md.splitlines()[0].lstrip("# ") if md else name,
                "caption": cap.group(1).strip() if cap else "",
                "slides": [{"body": script.group(1)}] if script else [],
                "sponsored": bool(re.search(r"業配[^\n]{0,6}[:：]\s*是", md)),
                "affiliate": bool(re.search(r"推薦連結[^\n]{0,6}[:：]\s*是", md))}
        return post, "貼文.md"
    return None, None


def check_folder(folder):
    """回傳 dict：verdict（PASS / WARN / FAIL）、fails、warns、source、rules_version。"""
    mod, rules = _load()
    post, src = find_post(folder)
    if post is None:
        return {"verdict": "FAIL", "fails": ["找不到貼文規格或 貼文.md，無法做合規檢查"], "warns": [],
                "source": None, "rules_version": rules.get("version")}
    fails, warns = mod.check(post, rules)
    v = "FAIL" if fails else ("WARN" if warns else "PASS")
    return {"verdict": v, "fails": fails, "warns": list(dict.fromkeys(warns)), "source": src,
            "rules_version": rules.get("version"), "sponsored": bool(post.get("sponsored"))}
