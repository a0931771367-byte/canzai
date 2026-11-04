#!/usr/bin/env python3
"""把發文需要的檔案從專案庫同步到 canzai repo（雲端 Claude 每週出新貼文後跑一次，然後 commit、push）。
    python3 sync_repo.py /home/claude/canzai
同步：內容部規格與貼文（PNG 另存 JPG，給 IG API 用）、程式部發文程式、法務部合規規則、數據部 ig_fetch.py、Actions workflow。
發文紀錄 publish_ledger.json 以 repo 裡的為正本（Actions 會寫），repo 沒有時才從專案庫複製。
"""
import glob
import os
import shutil
import sys
from PIL import Image

P = "/mnt/project-files"
REPO = sys.argv[1]
SKIP = {"__pycache__", "snapshots", "output", "examples", "publish_ledger.json", "待處理.md", "test_story.jpg"}


def ign(_dir, names):
    return [n for n in names if n in SKIP or n.startswith("授權驗證報告_") or n.endswith(".pyc")]


def mirror(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ign)


mirror(f"{P}/內容部/規格", f"{REPO}/內容部/規格")
for w in glob.glob(f"{P}/內容部/第*週"):
    dst = f"{REPO}/內容部/{os.path.basename(w)}"
    keep = {}  # Actions 寫回的查證報告保留
    for r in glob.glob(f"{dst}/*/查證報告.md"):
        keep[r] = open(r, encoding="utf-8").read()
    mirror(w, dst)
    for r, t in keep.items():
        if os.path.isdir(os.path.dirname(r)):
            open(r, "w", encoding="utf-8").write(t)
for d in ["common", "ig_publish", "factcheck", "comments"]:
    ledger = f"{REPO}/程式部/{d}/publish_ledger.json"
    saved = open(ledger, encoding="utf-8").read() if os.path.exists(ledger) else None
    mirror(f"{P}/程式部/{d}", f"{REPO}/程式部/{d}")
    if saved is not None:
        open(ledger, "w", encoding="utf-8").write(saved)
led = f"{REPO}/程式部/ig_publish/publish_ledger.json"
if not os.path.exists(led) and os.path.exists(f"{P}/程式部/ig_publish/publish_ledger.json"):
    shutil.copy(f"{P}/程式部/ig_publish/publish_ledger.json", led)
os.makedirs(f"{REPO}/法務部", exist_ok=True)
for f in ["compliance_check.py", "rules.json"]:
    shutil.copy(f"{P}/法務部/{f}", f"{REPO}/法務部/{f}")
os.makedirs(f"{REPO}/tools", exist_ok=True)
shutil.copy(f"{P}/數據部/ig_fetch.py", f"{REPO}/tools/ig_fetch.py")
os.makedirs(f"{REPO}/.github/workflows", exist_ok=True)
for y in glob.glob(f"{P}/程式部/ig_publish/github_actions/*.yml"):
    shutil.copy(y, f"{REPO}/.github/workflows/")
n = 0
for p in glob.glob(f"{REPO}/內容部/第*週/*/*.png"):
    j = p[:-4] + ".jpg"
    if not os.path.exists(j):
        Image.open(p).convert("RGB").save(j, quality=93)
        n += 1
print(f"同步完成，轉出 {n} 張 JPG → {REPO}")
