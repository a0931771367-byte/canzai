"""繁體中文（台灣）人味檢查：抓中國用語、半形標點、中文 AI 腔句型。只提出建議，不自動改字。

為什麼要有這支：/ig-human 的詞庫是英文的，抓不到中文的 AI 痕跡；AI 寫出來的繁體字常常
還是中國用語（視頻、質量、性價比），台灣讀者一眼就出戲。

來源（皆已讀過原始碼、確認無網路存取與可疑程式）：
- OpenCC（BYVoid/OpenCC，Apache-2.0）：簡繁與兩岸詞彙轉換，用來找出「繁體字但中國用詞」。
  安裝：pip install opencc（官方套件，純本機轉換）。沒裝時會跳過這一項，其他檢查照跑。
- 說人話 speak-human-tw（Raymondhou0917/speak-human-tw，MIT，Copyright (c) 2026 Raymond Hou）：
  中國用語替換表、全形標點規則、38 種 AI 痕跡的其中可用規則比對的部分，整理成下面的清單。

用法：
    python3 zh_tw_check.py 貼文.md            # 印出建議
    python3 zh_tw_check.py 貼文.md --json     # 給其他程式用
    python3 zh_tw_check.py 內容部/規格/第N週.json   # 圖卡、字幕、文案一次檢查
    echo "文字" | python3 zh_tw_check.py -
程式內：from zh_tw_check import check；check(text) 回傳建議清單（list of dict）。
"""
import difflib
import json
import re
import sys

_CJK = r"[㐀-鿿]"

# 信用卡、旅遊圈在台灣本來就這樣講，OpenCC 會誤判的詞（不提醒）
KEEP = {"登錄", "用戶", "數據", "帳戶", "綁定", "分期"}

# OpenCC 會換成資訊業用語、但一般貼文台灣人本來就這樣講的詞（不提醒）
OPENCC_SKIP = {"腳本", "項目", "循環", "文件", "程序", "對象", "模板", "菜單"}

# 說人話 taiwan-localization.md 的替換表（OpenCC 抓不到或抓錯的補在這裡）
TERMS = {
    "視頻": "影片", "短視頻": "短影音", "質量": "品質", "信息": "資訊", "網絡": "網路", "軟件": "軟體",
    "硬件": "硬體", "屏幕": "螢幕", "打印": "列印", "智能": "智慧", "移動端": "手機版", "博主": "創作者",
    "漲粉": "粉絲成長", "直播帶貨": "直播銷售", "水平": "水準", "立馬": "馬上", "給力": "很猛",
    "靠譜": "可靠", "接地氣": "生活化", "性價比": "CP 值", "顏值": "外型", "默認": "預設", "運營": "營運",
    "兼容": "相容", "卸載": "移除", "反饋": "回饋", "落地": "真的做出來", "打法": "做法", "抓手": "整句重寫",
    "賦能": "整句重寫，說清楚讓誰能做到什麼", "閉環": "整句重寫", "顆粒度": "細節程度", "小夥伴": "大家",
    "套路": "做法、手法（看語境）", "優惠力度": "優惠幅度", "薅羊毛": "撿便宜", "支付寶": None, "微信": None,
    "信用卡額度提升": None, "激活": "開卡", "綁定": None, "充值": "儲值", "提現": "提領", "到賬": "入帳",
    "賬戶": "帳戶", "賬單": "帳單", "分期付款": None, "積分": "點數、紅利點數",
    "返現": "現金回饋", "返利": "回饋", "外賣": "外送", "打車": "叫車", "酒店": "飯店", "機票錢": None,
}
TERMS = {k: v for k, v in TERMS.items() if v}

# 中文 AI 腔句型（說人話 patterns.md 裡能用規則比對的部分）
PATTERNS = [
    (r"不是[^。！？\n]{1,20}[，,]\s*而是", "「不是 A，而是 B」否定平行結構（第 12 種），一篇最多一次"),
    (r"不僅[^。！？\n]{1,25}(更|還|也)", "「不僅⋯更⋯」堆疊句（第 12 種）"),
    (r"首先[^。]*[。，][\s\S]{0,200}其次", "「首先／其次／最後」公文式結構，社群貼文改成直接講"),
    (r"(總的來說|綜上所述|總而言之|總結來說)", "空洞收尾（第 3、32 種），直接講結論或刪掉"),
    (r"這(意味著|代表著)", "「這意味著」解說腔（第 3 種）"),
    (r"值得(一提|注意)的是", "解說導引句（第 15 種），直接講那件事"),
    (r"(在這個|在當今|在如今)[^，。]{0,12}(時代|社會|世界)", "時代大帽子開場（第 21 種）"),
    (r"(讓我們一起|一起來看看|接下來讓我們|下面我們來)", "預告式導言（第 36 種），直接開始講"),
    (r"(希望(這篇|以上|本文)?對你有(所)?幫助|如果你有任何問題)", "AI 對話殘留（第 30 種）"),
    (r"(至關重要|不可或缺|舉足輕重|深入探討|全方位|一站式|無縫|顛覆性?|革命性|里程碑)", "誇大意義用詞（第 1、4 種）"),
    (r"(說白了|說穿了|本質上|歸根結底)", "說教深度腔（第 17 種），一篇最多一次"),
    (r"(我必須承認|說實話，我|老實說，我)", "假坦白鉤子（第 19 種）"),
    (r"——", "破折號（第 23 種），中文社群貼文改逗號或句號"),
    (r"(好的！|當然！|好問題)", "AI 對話殘留（第 30、31 種）"),
]
PATTERNS = [(re.compile(p), why) for p, why in PATTERNS]

PUNCT = [
    (re.compile(rf"(?<={_CJK})\s*,|,\s*(?={_CJK})"), "，", "中文句子用全形逗號（第 22 種）"),
    (re.compile(rf"(?<={_CJK})\s*\?"), "？", "中文句子用全形問號"),
    (re.compile(rf"(?<={_CJK})\s*!"), "！", "中文句子用全形驚嘆號"),
    (re.compile(rf"(?<={_CJK})\s*;"), "；", "中文句子用全形分號"),
    (re.compile(rf"(?<={_CJK}):(?=\s*{_CJK})"), "：", "中文句子用全形冒號"),
    (re.compile(r"[“”]"), "「」", "台灣用「」，不用彎引號"),
    (re.compile(rf"(?<={_CJK})\.\.\.+|\.\.\.+(?={_CJK})"), "⋯⋯", "刪節號用「⋯⋯」"),
]

_cc = None


def _opencc():
    global _cc
    if _cc is None:
        try:
            import opencc
            # s2tw 只換字形，s2twp 再加兩岸詞彙；兩者的差異才是「用詞」問題（不會把「台」報成「臺」）
            _cc = (opencc.OpenCC("t2s"), opencc.OpenCC("s2twp"), opencc.OpenCC("s2tw"))
        except Exception:  # 沒裝 opencc：跳過這項
            _cc = False
    return _cc


def _strip_protected(line):
    """網址、Hashtag、程式碼不檢查。"""
    return re.sub(r"https?://\S+|#[^\s#]+|`[^`]*`", lambda m: " " * len(m.group()), line)


def check(text, rhythm=True):
    out = []
    cc = _opencc()
    for n, raw in enumerate(text.splitlines(), 1):
        line = _strip_protected(raw)
        if not line.strip():
            continue
        seen = set()
        for k, v in TERMS.items():
            if k in line and k not in KEEP:
                seen.add(k)
                out.append({"type": "中國用語", "line": n, "found": k, "suggest": v, "reason": "台灣讀者會出戲"})
        if cc:
            simp = cc[0].convert(line)
            base, tw = cc[2].convert(simp), cc[1].convert(simp)
            sm = difflib.SequenceMatcher(None, base, tw, autojunk=False)
            for op, a1, a2, b1, b2 in sm.get_opcodes():
                if op != "replace":
                    continue
                # 往前後各擴一個字，避免只回報半個詞
                a1, a2 = max(0, a1 - 1), min(len(base), a2 + 1)
                found, sug = base[a1:a2], tw[max(0, b1 - 1):min(len(tw), b2 + 1)]
                if any(k in found or found in k for k in KEEP | seen | OPENCC_SKIP) or not re.search(_CJK, found):
                    continue
                out.append({"type": "中國用語", "line": n, "found": found, "suggest": sug, "reason": "OpenCC 兩岸詞彙比對"})
        for rx, why in PATTERNS:
            for m in rx.finditer(line):
                out.append({"type": "AI 腔", "line": n, "found": m.group()[:20], "suggest": "", "reason": why})
        for rx, rep, why in PUNCT:
            for m in rx.finditer(line):
                out.append({"type": "標點", "line": n, "found": m.group().strip() or m.group(), "suggest": rep, "reason": why})
    # 句長過勻（第 29 種）：連續 5 句長度差不到 4 個字
    sents = [s for s in re.split(r"[。！？\n]", text) if len(s.strip()) >= 6]
    lens = [len(s) for s in sents]
    for i in range(len(lens) - 4 if rhythm else 0):
        w = lens[i:i + 5]
        if max(w) - min(w) <= 3:
            out.append({"type": "AI 腔", "line": 0, "found": sents[i][:15], "suggest": "",
                        "reason": "連續 5 句長度幾乎一樣，節奏像機器（第 29 種），混一兩句短句"})
            break
    return out


def summary(issues):
    if not issues:
        return "沒有發現中國用語、半形標點或中文 AI 腔"
    return "；".join(f"第{i['line']}行「{i['found']}」→{i['suggest'] or i['reason']}" for i in issues[:6]) + \
        (f"⋯⋯共 {len(issues)} 處" if len(issues) > 6 else "")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    src = sys.argv[1]
    text = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    if src.endswith(".json"):  # 內容部規格檔：把圖卡、字幕、文案的所有文字攤平檢查（行號＝第幾段文字）
        def strings(o):
            if isinstance(o, str):
                yield o
            elif isinstance(o, dict):
                for k, v in o.items():
                    if k not in ("factcheck", "prereq", "file", "pose", "face", "type"):
                        yield from strings(v)
            elif isinstance(o, list):
                for v in o:
                    yield from strings(v)
        text = "\n".join(x.replace("\n", " ") for x in strings(json.loads(text)))
    issues = check(text, rhythm=not src.endswith(".json"))  # 圖卡字本來就短而整齊，不看句長
    if "--json" in sys.argv:
        print(json.dumps({"issues": issues, "opencc": bool(_opencc())}, ensure_ascii=False, indent=1))
        return
    if not _opencc():
        print("（沒裝 opencc，兩岸詞彙比對跳過；pip install opencc 可開啟）")
    if not issues:
        print("PASS：" + summary(issues))
        return
    print(f"REVIEW：{len(issues)} 處建議（只是建議，看語境決定改不改）")
    for i in issues:
        loc = f"第 {i['line']} 行" if i["line"] else "全文"
        sug = f" → {i['suggest']}" if i["suggest"] else ""
        print(f"  [{i['type']}] {loc}「{i['found']}」{sug}：{i['reason']}")


if __name__ == "__main__":
    main()
