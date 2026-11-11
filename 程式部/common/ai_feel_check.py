"""品管部：去 AI 感自動檢查（發文前第四關）。FAIL 不發，WARN 進人工審稿清單。

檢查對象是一個貼文資料夾（貼文.md／caption.txt／圖卡 PNG、JPG／reel.mp4），也可以一次檢查整週資料夾。
文字的中國用語、半形標點、中文 AI 腔沿用 zh_tw_check.py（說人話規則），不重寫；
這支補上 zh_tw_check 沒管的：Markdown 殘留、隱形字元、emoji 條列、AI 對話殘留、整週模板化、
圖片的 AI 生成標記（會讓 IG 自動掛「AI 資訊」標籤）、Reel 的靜音與機械節奏。

判定原則（品管部/去AI感檢查表.md 有每條的來源與查證日期）：
- FAIL：讀者一看就知道是機器產的、或會被 IG 自動標成 AI 內容卻沒揭露，這種不能發。
- WARN：可能有 AI 感，要人看語境決定，列進人工審稿清單。

用法：
    python3 ai_feel_check.py 內容部/第1-2週/01_雙11該刷哪張卡
    python3 ai_feel_check.py 內容部/第1-2週 --week -o 品管部/審稿/第1-2週.md
    python3 ai_feel_check.py <資料夾> --json
程式內：from ai_feel_check import check_folder；check_folder(folder) 回傳 dict（verdict、fails、warns）。
只用 Python 標準函式庫＋ffprobe／ffmpeg（已在環境裡），不連網、不上傳。
"""
import glob
import json
import os
import re
import statistics
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    from zh_tw_check import check as zh_check
except Exception:  # 檢查器壞掉不影響其他項目
    zh_check = None
try:
    from compliance import find_post
except Exception:
    find_post = None

VERSION = "2026-11-05"

EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆↔-↪⤴⤵]|[0-9#*]️?⃣")
# 1️⃣ ✅ 👉 💳 這類開頭的條列行
EMOJI_LINE = re.compile("^\\s*(?:" + EMOJI.pattern + ")")

# AI 對話殘留：出現就是沒校稿，一律 FAIL
RESIDUE = [
    r"作為(一個)?\s*(AI|人工智慧|語言模型)", r"希望(這篇|以上|本文|這些)?(內容)?對你有(所)?幫助", r"如果你(還)?有(任何|其他)(問題|疑問)",
    r"^\s*(好的|當然)[！!，,]", r"以下是[^\n]{0,12}(版本|文案|內容|建議)[：:]", r"\[(插入|填入|在此)[^\]]*\]", r"【(插入|填入)[^】]*】",
    r"\bTODO\b", r"\bXXX\b", r"lorem ipsum", r"(As an AI|I hope this helps|Certainly!)",
]
RESIDUE = [re.compile(p, re.I | re.M) for p in RESIDUE]

# 空洞收尾與總結句：IG 文案出現就 FAIL（讀者最常點名的 AI 收尾）
HOLLOW_END = re.compile(r"(總的來說|綜上所述|總而言之|總結來說|總結一下)")

# 罐仔自己的固定簽名（品牌記憶點，不算模板化）
SIGNATURE_OK = [re.compile(p) for p in (r"^※", r"^#", r"依(各)?銀行公告為準")]


def _invisible(text):
    bad = [c for c in text if (unicodedata.category(c) == "Cf" and c not in "‍️⃣")
           or c in "   ㅤᅟᅠ"]
    return sorted({f"U+{ord(c):04X}" for c in bad})


def _caption_from(folder):
    cap = os.path.join(folder, "caption.txt")
    if os.path.exists(cap):
        return open(cap, encoding="utf-8").read()
    md = os.path.join(folder, "貼文.md")
    if os.path.exists(md):
        m = re.search(r"##\s*IG 文案.*?```\s*\n(.*?)```", open(md, encoding="utf-8").read(), re.S)
        if m:
            return m.group(1)
    return ""


def _slide_text(folder):
    if find_post is None:
        return ""
    try:
        post, _ = find_post(folder)
    except Exception:
        return ""
    if not post:
        return ""
    out = []
    for s in post.get("slides", []) or post.get("scenes", []) or []:
        for k in ("title", "sub", "body", "label", "text"):
            if isinstance(s.get(k), str):
                out.append(s[k])
        for it in s.get("items", []) or []:
            if isinstance(it, str):
                out.append(it)
    return "\n".join(out)


def check_text(caption, slides=""):
    fails, warns = [], []
    body = caption.strip()
    if not body:
        return ["找不到 IG 文案（caption.txt 或 貼文.md 的「IG 文案」區塊）"], []
    inv = _invisible(caption + slides)
    if inv:
        fails.append(f"T1 隱形字元 {', '.join(inv)}：鍵盤打不出來，是複製 AI 輸出的痕跡，刪掉")
    if re.search(r"\*\*[^*\n]+\*\*|^#{1,6}\s|^\s*[-*]\s+\*\*", body, re.M):
        fails.append("T2 文案有 Markdown 符號（**粗體** 或 ## 標題）：IG 不會轉換，讀者會直接看到星號")
    if "——" in body or "—" in body:
        fails.append("T3 文案有破折號「——」：中文社群貼文改逗號或句號")
    for rx in RESIDUE:
        m = rx.search(caption + "\n" + slides)
        if m:
            fails.append(f"T4 AI 對話殘留「{m.group().strip()[:20]}」：沒校稿就貼上，整句刪掉")
    m = HOLLOW_END.search(body)
    if m:
        fails.append(f"T5 空洞總結句「{m.group()}」：直接講結論或刪掉")

    # 連續幾行都用 emoji 開頭＝emoji 條列；單獨一行「👉 追蹤」這種不算
    run, best, best_lines, cur = 0, 0, [], []
    for l in body.splitlines():
        if not l.strip() or l.strip().startswith("#"):
            continue
        if EMOJI_LINE.match(l):
            run += 1
            cur.append(l)
            if run > best:
                best, best_lines = run, list(cur)
        else:
            run, cur = 0, []
    if best >= 3:
        fails.append(f"T6 emoji 當條列符號連續 {best} 行（{'／'.join(l.strip()[:6] for l in best_lines[:4])}⋯）："
                     "最常被點名的 AI 文案排版，改成一兩句話講完，或用「第一、第二」")
    elif best == 2:
        warns.append("T6 emoji 當條列符號連續 2 行：再多一行就會 FAIL，考慮改成句子")
    text_only = re.sub(r"#[^\s#]+", "", body)
    n_emo = len(EMOJI.findall(text_only))
    n_chars = len(re.findall(r"[㐀-鿿]", text_only)) or 1
    if n_emo > max(3, n_chars // 60):
        warns.append(f"T7 emoji 偏多：{n_emo} 個／{n_chars} 字（建議每 60 字最多 1 個，全篇不超過 3 個）")
    nums = re.findall(r"^\s*(?:[1-9][.、)]|[1-9]️?⃣|[一二三四五]、)", body, re.M)
    if len(nums) == 3:
        warns.append("T8 文案是剛好三點的條列：AI 最愛「三點法」，確認真的是三件事，不是湊數")
    if zh_check:
        for i in zh_check(caption) + (zh_check(slides, rhythm=False) if slides else []):
            msg = f"T9 [{i['type']}]「{i['found']}」{('→' + i['suggest']) if i['suggest'] else ''}：{i['reason']}"
            (fails if i["type"] == "AI 腔" and "破折號" in i["reason"] else warns).append(msg)
    return list(dict.fromkeys(fails)), list(dict.fromkeys(warns))


# 真的 AI 生成素材的標記（IG 依 C2PA／IPTC 自動掛「AI 資訊」）：只在檔案的中繼資料區找，不掃影像本體，避免亂碼誤判
AI_GEN_MARKERS = [
    (rb"trainedAlgorithmicMedia", "IPTC 標記為 AI 生成"),
    (rb"(?i)(stable.?diffusion|midjourney|dall.?e|adobe firefly|higgsfield|imagen|flux\.1|openai|sora|runway|kling|nano.?banana|seedance|veo)",
     "AI 生成工具名稱"),
    (rb"(?i)(negative_prompt|cfg_scale|sampler_name)", "AI 生成參數（prompt／sampler）"),
]
# Claude 交付的檔案會自動帶 Anthropic 內容憑證（C2PA，「Claude 依使用者要求提供，可能建立或修改了內容」）
CLAUDE_CRED = rb"com.anthropic.claude.provided"


def _meta_bytes(path):
    """只取中繼資料：PNG 跳過 IDAT、JPEG 取 SOS 之前、MP4 跳過 mdat。"""
    data = open(path, "rb").read()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        out, i = [], 8
        while i + 8 <= len(data):
            n, typ = int.from_bytes(data[i:i + 4], "big"), data[i + 4:i + 8]
            if typ != b"IDAT":
                out.append(typ + data[i + 8:i + 8 + n])
            i += 12 + n
        return b"".join(out)
    if data[:2] == b"\xff\xd8":
        sos = data.find(b"\xff\xda")
        return data[:sos if sos > 0 else 1 << 20]
    out, i = [], 0
    while i + 8 <= len(data):
        n, typ = int.from_bytes(data[i:i + 4], "big"), data[i + 4:i + 8]
        if n == 1:
            n = int.from_bytes(data[i + 8:i + 16], "big")
        if n < 8:
            break
        if typ != b"mdat":
            out.append(data[i:i + n])
        i += n
    return b"".join(out) or data[:1 << 20]


def check_media_meta(path):
    """回傳 (AI 生成標記清單, 是否帶 Claude 交付憑證)。"""
    blob = _meta_bytes(path)
    gen = sorted({why for rx, why in AI_GEN_MARKERS if re.search(rx, blob)})
    return gen, CLAUDE_CRED in blob


def _ff(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def _scene_secs(folder):
    """從 貼文.md 腳本的【text 3秒】讀每幕秒數（產生器照這個做，比畫面偵測準）。"""
    md = os.path.join(folder, "貼文.md")
    if not os.path.exists(md):
        return []
    return [float(x) for x in re.findall(r"【[^】]*?([\d.]+)\s*秒】", open(md, encoding="utf-8").read())]


def check_video(path, scene_secs=()):
    fails, warns = [], []
    try:
        pr = _ff(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", path])
        info = json.loads(pr.stdout or "{}")
    except Exception as e:
        return [], [f"V0 無法讀取影片（{e}），人工確認"]
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    silent = not has_audio
    if has_audio:
        vd = _ff(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-vn", "-f", "null", "-"]).stderr
        m = re.search(r"max_volume:\s*(-?[\d.]+|-inf)", vd)
        silent = bool(m and (m.group(1) == "-inf" or float(m.group(1)) < -50))
    if silent:
        warns.append("V1 影片本身沒有聲音：發文時一定要在 IG 加音樂或音效（貼文.md 的配樂建議），靜音的圖文動畫像自動產生的投影片")
    seg = list(scene_secs)
    if len(seg) >= 4 and statistics.pstdev(seg) < 0.25:
        warns.append(f"V2 每幕長度一樣（{'、'.join(f'{s:g}' for s in seg)} 秒）：節奏像機器，重點幕拉長、轉場幕縮短")
    if seg and max(seg) > 6:
        warns.append(f"V3 有一幕停 {max(seg):g} 秒：8～20 秒的 Reel 每 2～4 秒要有變化")
    if dur and not (8 <= dur <= 20):
        warns.append(f"V4 片長 {dur:g} 秒，不在內容部規定的 8～20 秒")
    return fails, warns


def check_folder(folder, ai_disclosed=None):
    """回傳 dict：verdict（PASS／WARN／FAIL）、fails、warns、version。"""
    folder = os.path.normpath(folder)
    caption, slides = _caption_from(folder), _slide_text(folder)
    fails, warns = check_text(caption, slides)
    md = os.path.join(folder, "貼文.md")
    if ai_disclosed is None:
        ai_disclosed = os.path.exists(md) and bool(re.search(r"AI\s*揭露[^\n]{0,6}[:：]\s*是", open(md, encoding="utf-8").read()))
    media = sorted(glob.glob(os.path.join(folder, "*.png")) + glob.glob(os.path.join(folder, "*.jpg"))
                   + glob.glob(os.path.join(folder, "*.mp4")))
    claude_cred = []
    for p in media:
        gen, cred = check_media_meta(p)
        if cred:
            claude_cred.append(os.path.basename(p))
        if gen:
            msg = f"M1 {os.path.basename(p)} 帶有 {'、'.join(gen)}：IG 會自動掛「AI 資訊」標籤"
            if ai_disclosed:
                warns.append(msg + "（貼文.md 已標「AI 揭露：是」，確認文案有說明）")
            else:
                fails.append(msg + "，貼文.md 沒有「AI 揭露：是」。二選一：改用非 AI 素材，或揭露後再發")
    direct = [n for n in claude_cred if n.endswith(".mp4") or n.startswith("cover")]
    if direct:
        warns.append(f"M2 {'、'.join(direct)} 帶有 Anthropic 內容憑證（C2PA：Claude 提供、可能修改過）且會原檔上傳，"
                     "IG 可能顯示「AI 資訊」。輪播圖卡轉 JPG 時不會帶過去；要不要揭露見品管部檢查表 M2")
    for v in [p for p in media if p.endswith(".mp4")]:
        f, w = check_video(v, _scene_secs(folder))
        fails += f
        warns += w
    # 例外：貼文.md 寫「品管例外：T6（理由）」，該項 FAIL 降為 WARN（理由必填，品管部週審會複核）
    if os.path.exists(md):
        for code, why in re.findall(r"品管例外[:：]\s*([A-Z]\d+)\s*[（(]([^）)]+)[）)]", open(md, encoding="utf-8").read()):
            keep = []
            for x in fails:
                if x.startswith(code + " "):
                    warns.append(f"{x}（已列例外：{why}）")
                else:
                    keep.append(x)
            fails = keep
    verdict = "FAIL" if fails else ("WARN" if warns else "PASS")
    return {"verdict": verdict, "fails": fails, "warns": warns, "version": VERSION, "folder": os.path.basename(folder)}


def check_week(week_dir):
    """整週：每篇各自檢查，再看跨篇的模板化（同一句話出現在一半以上的貼文）。"""
    folders = sorted(d for d in glob.glob(os.path.join(week_dir, "*")) if os.path.isdir(d)
                     and (os.path.exists(os.path.join(d, "貼文.md")) or os.path.exists(os.path.join(d, "caption.txt"))))
    results = [check_folder(d) for d in folders]
    seen = {}
    for d in folders:
        for line in {l.strip() for l in _caption_from(d).splitlines() if len(l.strip()) >= 6}:
            if any(rx.search(line) for rx in SIGNATURE_OK):
                continue
            key = re.sub(r"[：:].*", "", line)[:12]  # 「👉 追蹤罐仔：⋯」這種只換後半句的也算同一個模板
            seen.setdefault(key, set()).add(os.path.basename(d))
    templ = [(k, v) for k, v in seen.items() if len(v) >= max(3, len(folders) // 2)]
    week_warns = [f"W1 「{k}⋯」出現在 {len(v)}/{len(folders)} 篇：整週同一句開頭或收尾，滑過去會覺得是模板產的，"
                  "保留一兩篇、其他換說法" for k, v in templ]
    return results, week_warns


def report_md(results, week_warns=(), title="去 AI 感檢查"):
    n = {k: sum(r["verdict"] == k for r in results) for k in ("FAIL", "WARN", "PASS")}
    out = [f"# {title}", "", f"檢查表版本 {VERSION}｜FAIL {n['FAIL']} 篇、WARN {n['WARN']} 篇、PASS {n['PASS']} 篇", ""]
    if week_warns:
        out += ["## 整週", ""] + [f"- [WARN] {w}" for w in week_warns] + [""]
    for r in results:
        out += [f"## {r['folder']}：{r['verdict']}", ""]
        out += [f"- [FAIL] {x}" for x in r["fails"]] + [f"- [WARN] {x}" for x in r["warns"]]
        if r["verdict"] == "PASS":
            out.append("- 自動檢查沒有問題，仍要過人工審稿清單")
        out.append("")
    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return
    target = args[0]
    out = sys.argv[sys.argv.index("-o") + 1] if "-o" in sys.argv else None
    if "--week" in sys.argv:
        results, ww = check_week(target)
        title = f"去 AI 感檢查：{os.path.basename(os.path.normpath(target))}"
    else:
        results, ww = [check_folder(target)], []
        title = f"去 AI 感檢查：{os.path.basename(os.path.normpath(target))}"
    if "--json" in sys.argv:
        print(json.dumps({"results": results, "week_warns": ww}, ensure_ascii=False, indent=1))
    else:
        md = report_md(results, ww, title)
        print(md)
        if out:
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            open(out, "w", encoding="utf-8").write(md)
    sys.exit(1 if any(r["verdict"] == "FAIL" for r in results) else 0)


if __name__ == "__main__":
    main()
