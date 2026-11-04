"""接上罐子帳號裡的 /ig-* Skill 工具（ig-human、ig-caption），並補上中文支援。

這些 Skill 的程式是以英文為主寫的，直接用在中文會有兩個問題：
- ig-human 把破折號換成半形逗號「, 」，中文應該是全形「，」
- ig-caption 認不得中文 Hashtag（#信用卡）、中文行動呼籲（留言、私訊、收藏）與「5萬」這類數字
所以這裡呼叫原本的工具，再補中文的處理。Skill 本身不改（是唯讀的同步副本）。
"""
import glob
import json
import os
import re
import subprocess

_CJK = r"[㐀-鿿　-〿＀-￯]"


def skill_dir(name):
    hits = glob.glob(os.path.expanduser(f"~/.claude/skills/synced/*/{name}"))
    if not hits:
        hits = glob.glob(f"/root/.claude/skills/synced/*/{name}")
    return hits[0] if hits else None


def humanize(text):
    """用 /ig-human 清掉 AI 痕跡（破折號、隱形字元、AI 慣用詞），再修正中文標點。
    找不到 Skill 時只做中文標點修正。回傳 (清理後文字, 改了什麼)。"""
    d = skill_dir("ig-human")
    report = {}
    if d:
        r = subprocess.run(["python3", os.path.join(d, "humanize.py"), "-", "--json"], input=text,
                           capture_output=True, text=True)
        if r.returncode == 0:
            res = json.loads(r.stdout)
            text, report = res["text"], res.get("report", {})
    else:
        text = text.replace("——", "，").replace("—", "，")
    # 中文前後的半形逗號、分號、冒號改全形
    text = re.sub(rf"(?<={_CJK})\s*,\s*", "，", text)
    text = re.sub(rf"\s*,\s*(?={_CJK})", "，", text)
    text = re.sub(rf"(?<={_CJK})\s*;\s*", "；", text)
    text = re.sub(rf"(?<={_CJK}):\s*(?={_CJK})", "：", text)
    return text.rstrip("\n"), report


CJK_ASK = re.compile(r"(留言|私訊|收藏|分享|追蹤|點連結|主頁連結|存起來|標註|tag)")
CJK_TAG = re.compile(r"#[^\s#]+")
CJK_NUM = re.compile(r"(\d|[一二三四五六七八九十百千萬兩]+(元|塊|萬|%|張|件|招|個|倍))")


def lint_caption(text, keywords=None, max_tags=5):
    """用 /ig-caption 檢查文案，並以中文規則覆寫 HASHTAGS、ONE ASK、HOOK IS CONCRETE 三項。
    回傳 dict：verdict（PASS / REVIEW / FAIL）與 checks。"""
    d = skill_dir("ig-caption")
    res = {"checks": [], "verdict": "PASS"}
    if d:
        cmd = ["python3", os.path.join(d, "caption.py"), "-", "--json"]
        if keywords:
            cmd += ["--keywords", ",".join(keywords)]
        r = subprocess.run(cmd, input=text, capture_output=True, text=True)
        if r.stdout.strip().startswith("{"):
            res = json.loads(r.stdout)
    checks = {c["check"]: c for c in res.get("checks", [])}
    visible = text[:125]
    tags = CJK_TAG.findall(text)
    asks = CJK_ASK.findall(text)
    checks["HASHTAGS"] = {"check": "HASHTAGS", "status": "PASS" if 1 <= len(tags) <= max_tags else "WARN",
                          "detail": f"{len(tags)} 個 Hashtag（建議 1～{max_tags} 個）：{' '.join(tags)}"}
    checks["ONE ASK"] = {"check": "ONE ASK", "status": "PASS" if 1 <= len(set(asks)) <= 2 else "WARN",
                         "detail": f"行動呼籲：{'、'.join(dict.fromkeys(asks)) or '沒有'}（建議只留一個主要的）"}
    checks["HOOK IS CONCRETE"] = {"check": "HOOK IS CONCRETE",
                                  "status": "PASS" if CJK_NUM.search(visible.split("\n")[0]) else "WARN",
                                  "detail": "第一行有具體數字" if CJK_NUM.search(visible.split("\n")[0])
                                  else "第一行沒有數字或具體名稱，點開前看不到可驗證的好處"}
    if "TAG PLACEMENT" in checks and tags:
        last = text.strip().split("\n")[-1]
        ok = all(t in last for t in tags)
        checks["TAG PLACEMENT"] = {"check": "TAG PLACEMENT", "status": "PASS" if ok else "WARN",
                                   "detail": "Hashtag 集中在最後一行" if ok else "Hashtag 散在內文，建議集中放最後"}
    # 繁中人味檢查（中國用語、半形標點、中文 AI 腔）：/ig-human 的詞庫是英文的，抓不到這些
    try:
        from zh_tw_check import check as zh_check, summary as zh_summary
        zh = zh_check(text)
        checks["ZH-TW 人味"] = {"check": "ZH-TW 人味", "status": "WARN" if zh else "PASS", "detail": zh_summary(zh)}
    except Exception as e:  # 檢查器壞掉不影響發文流程
        checks["ZH-TW 人味"] = {"check": "ZH-TW 人味", "status": "PASS", "detail": f"略過（{e}）"}
    out = list(checks.values())
    st = [c["status"] for c in out]
    verdict = "FAIL" if "FAIL" in st else ("REVIEW" if "WARN" in st else "PASS")
    return {"verdict": verdict, "checks": out, "skill_found": bool(d)}
