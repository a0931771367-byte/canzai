"""罐仔工具共用模組：主題色、字型、中文排版、罐仔角色、圖示。

animator（短影片）與 cards（輪播圖卡）都從這裡取用，改這裡就能統一品牌視覺。
"""
import math
import os
import re
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "fonts")

# ---------------------------------------------------------------- 主題
THEMES = {
    # 品牌色（依內容部罐仔定稿）：罐身薄荷綠、金色蓋子、珊瑚橘重點、深藍線條文字、奶油白底
    "default": dict(bg_top="#FFF8EC", bg_bottom="#FDEBD3", brand="#2EC4B6", brand_dark="#1FA397",
                    brand_light="#7BE0D6", primary="#FF6B4A", primary_dark="#E2502F", accent="#FFC23C",
                    text="#1E2A4A", sub="#56607A", card="#FFFFFF", marker="#FFE08A", muted="#EFE6D6",
                    good="#2EC4B6", bad="#FF6B4A"),
    # 旅行：淡薄荷天空
    "travel": dict(bg_top="#E3F6F4", bg_bottom="#FFF8EC", brand="#2EC4B6", brand_dark="#1FA397",
                   brand_light="#7BE0D6", primary="#FF6B4A", primary_dark="#E2502F", accent="#FFC23C",
                   text="#1E2A4A", sub="#4F6075", card="#FFFFFF", marker="#FFE08A", muted="#D7ECEA",
                   good="#2EC4B6", bad="#FF6B4A"),
    # 深色：夜間 / 警告提醒
    "dark": dict(bg_top="#1E2A4A", bg_bottom="#28365E", brand="#2EC4B6", brand_dark="#1FA397",
                 brand_light="#7BE0D6", primary="#FF6B4A", primary_dark="#E2502F", accent="#FFC23C",
                 text="#FFF8EC", sub="#C9CFDF", card="#2F3D66", marker="#8A6400", muted="#3A4870",
                 good="#2EC4B6", bad="#FF6B4A"),
}

OUTLINE = "#1E2A4A"
SPRITE_DIR = os.path.join(ROOT, "assets", "canzai")


def rgb(h, a=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def get_theme(name_or_dict):
    if isinstance(name_or_dict, dict):
        base = dict(THEMES["default"])
        base.update(name_or_dict)
        return base
    return THEMES.get(name_or_dict or "default", THEMES["default"])


# ---------------------------------------------------------------- 字型
FONT_FILES = {
    "regular": "NotoSansTC-Regular.otf",
    "bold": "NotoSansTC-Bold.otf",
    "black": "NotoSansTC-Black.otf",
    "round": "Huninn.ttf",  # jf open 粉圓，圓潤可愛，適合標題
}


@lru_cache(maxsize=256)
def font(weight="bold", size=60):
    path = os.path.join(FONT_DIR, FONT_FILES.get(weight, FONT_FILES["bold"]))
    if not os.path.exists(path):
        path = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
    return ImageFont.truetype(path, size)


# ---------------------------------------------------------------- 中文排版
NO_LINE_START = set("，。！？、：；）」』】》%…,.!?:;)]}・～~")
NO_LINE_END = set("（「『【《([{$")
_UNIT = re.compile(r"[A-Za-z0-9$@#%.,+\-/:_']+|\s+|.", re.S)


def parse_rich(text):
    """把 **重點** 轉成 [(字串, 是否重點)]。"""
    out = []
    for i, part in enumerate(re.split(r"\*\*", str(text))):
        if part:
            out.append((part, i % 2 == 1))
    return out


def _units(text):
    units = []
    for seg, hl in parse_rich(text):
        for m in _UNIT.finditer(seg):
            units.append((m.group(0), hl))
    return units


def wrap_rich(text, fnt, max_w):
    """回傳 lines，每行是 [(字串, 重點)]；處理中英混排與避頭尾。"""
    lines = []
    for para in str(text).split("\n"):
        units = _units(para)
        cur, cur_w = [], 0
        for u, hl in units:
            w = fnt.getlength(u)
            if u == "\n":
                continue
            if cur and cur_w + w > max_w and not u.isspace():
                if u[0] in NO_LINE_START:  # 標點不放行首：掛在上一行
                    cur.append((u, hl)); cur_w += w
                    continue
                carry = []
                while cur and cur[-1][0] and cur[-1][0][-1] in NO_LINE_END:
                    carry.insert(0, cur.pop())
                lines.append(cur)
                cur = carry
                cur_w = sum(fnt.getlength(x) for x, _ in cur)
            if not cur and u.isspace():
                continue
            cur.append((u, hl)); cur_w += w
        while cur and cur[-1][0].isspace():
            cur.pop()
        lines.append(cur)
    # 合併相鄰同樣式片段
    merged = []
    for line in lines:
        m = []
        for s, hl in line:
            if m and m[-1][1] == hl:
                m[-1] = (m[-1][0] + s, hl)
            else:
                m.append((s, hl))
        merged.append(m)
    return merged


def line_width(line, fnt):
    return sum(fnt.getlength(s) for s, _ in line)


def render_text(text, weight="bold", size=60, max_w=900, color="#22304A", hl_color=None,
                marker=None, align="center", spacing=1.25, stroke=0, stroke_color="#FFFFFF", balance=True):
    """把一段（可含 **重點**）文字畫成透明背景 RGBA 圖。"""
    fnt = font(weight, size)
    lines = wrap_rich(text, fnt, max_w)
    if balance and len(lines) > 1 and "\n" not in str(text):
        # 縮窄寬度讓各行長度平均，避免最後一行只剩一兩個字
        lo, hi = max_w * 0.5, max_w
        for _ in range(8):
            mid = (lo + hi) / 2
            if len(wrap_rich(text, fnt, mid)) > len(lines):
                lo = mid
            else:
                hi = mid
        lines = wrap_rich(text, fnt, hi)
    lh = int(size * spacing)
    widths = [line_width(l, fnt) for l in lines]
    W = int(max(widths + [1])) + stroke * 2 + 16
    H = lh * len(lines) + int(size * 0.35) + stroke * 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    asc = fnt.getmetrics()[0]
    for i, (line, lw) in enumerate(zip(lines, widths)):
        x = {"left": stroke + 8, "right": W - lw - stroke - 8}.get(align, (W - lw) / 2)
        y = i * lh + stroke + (lh - size) / 2
        for seg, hl in line:
            sw = fnt.getlength(seg)
            if hl and marker:
                d.rounded_rectangle([x - 4, y + size * 0.55, x + sw + 4, y + size * 1.08],
                                    radius=int(size * 0.12), fill=rgb(marker, 230))
            col = hl_color if (hl and hl_color) else color
            d.text((x, y + size * 0.86 - asc + size * 0.14), seg, font=fnt, fill=rgb(col),
                   stroke_width=stroke, stroke_fill=rgb(stroke_color))
            x += sw
    return img


def fit_text(text, max_w, max_h, weight="bold", size=90, min_size=30, keep_lines=True, **kw):
    """自動縮小字級直到塞進 max_w x max_h。keep_lines：手動換行的每段盡量維持一行（標題用；內文請設 False）。"""
    s = size
    paras = len(str(text).split("\n"))
    while True:
        img = render_text(text, weight=weight, size=s, max_w=max_w, **kw)
        ok = img.height <= max_h and img.width <= max_w + 40
        if ok and paras > 1 and keep_lines:  # 有手動換行時，盡量讓每段維持一行（避免孤字）
            ok = len(wrap_rich(text, font(weight, s), max_w)) == paras or s <= size * 0.6
        if ok or s <= min_size:
            return img
        s = int(s * 0.94)


# ---------------------------------------------------------------- 背景
def gradient(w, h, top, bottom):
    t, b = rgb(top), rgb(bottom)
    col = Image.new("RGBA", (1, h))
    for y in range(h):
        k = y / max(h - 1, 1)
        col.putpixel((0, y), tuple(int(t[i] + (b[i] - t[i]) * k) for i in range(3)) + (255,))
    return col.resize((w, h))


def background(w, h, theme, seed=7):
    """漸層 + 淡淡的圓點與硬幣，品牌底圖。"""
    import random
    rnd = random.Random(seed)
    img = gradient(w, h, theme["bg_top"], theme["bg_bottom"])
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(14):
        r = rnd.randint(int(w * 0.04), int(w * 0.16))
        x, y = rnd.randint(-r, w + r), rnd.randint(-r, h + r)
        d.ellipse([x - r, y - r, x + r, y + r], fill=rgb("#FFFFFF", 70))
    img.alpha_composite(layer)
    return img


# ---------------------------------------------------------------- 圖示
def icon(name, size=160, color="#FF6F88", fg="#FFFFFF"):
    """簡單向量圖示，畫在圓形色底上。name: card plane coin gift check cross percent cart star bulb wallet calendar hotel"""
    S = 512
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, S - 8, S - 8], fill=rgb(color))
    f, o = rgb(fg), rgb(color)
    W = 26
    if name == "card":
        d.rounded_rectangle([110, 160, 402, 352], 30, fill=f)
        d.rectangle([110, 205, 402, 245], fill=o)
        d.rounded_rectangle([140, 280, 230, 315], 10, fill=o)
    elif name == "plane":
        pts = [(256, 96), (284, 140), (284, 228), (420, 300), (420, 340), (284, 300), (284, 372),
               (330, 410), (330, 436), (256, 414), (182, 436), (182, 410), (228, 372), (228, 300),
               (92, 340), (92, 300), (228, 228), (228, 140)]
        d.polygon(pts, fill=f)
    elif name == "coin":
        d.ellipse([120, 120, 392, 392], fill=rgb("#FFD24D"), outline=f, width=W)
        d.text((256, 262), "$", font=font("black", 190), fill=rgb("#B07800"), anchor="mm")
    elif name == "gift":
        d.rectangle([130, 230, 382, 400], fill=f)
        d.rectangle([110, 180, 402, 240], fill=f)
        d.rectangle([238, 180, 274, 400], fill=o)
        d.ellipse([170, 110, 256, 190], outline=f, width=W)
        d.ellipse([256, 110, 342, 190], outline=f, width=W)
    elif name == "check":
        d.line([(150, 265), (225, 340), (365, 175)], fill=f, width=50, joint="curve")
    elif name == "cross":
        d.line([(170, 170), (342, 342)], fill=f, width=50)
        d.line([(342, 170), (170, 342)], fill=f, width=50)
    elif name == "percent":
        d.ellipse([140, 140, 230, 230], outline=f, width=W)
        d.ellipse([282, 282, 372, 372], outline=f, width=W)
        d.line([(355, 150), (157, 362)], fill=f, width=W + 4)
    elif name == "cart":
        d.line([(110, 150), (165, 150), (205, 320), (370, 320), (400, 200), (180, 200)], fill=f, width=W, joint="curve")
        d.ellipse([195, 345, 245, 395], fill=f)
        d.ellipse([330, 345, 380, 395], fill=f)
    elif name == "star":
        pts = []
        for i in range(10):
            r = 160 if i % 2 == 0 else 70
            a = -math.pi / 2 + i * math.pi / 5
            pts.append((256 + r * math.cos(a), 266 + r * math.sin(a)))
        d.polygon(pts, fill=f)
    elif name == "bulb":
        d.ellipse([150, 100, 362, 312], fill=f)
        d.rectangle([205, 280, 307, 360], fill=f)
        d.rounded_rectangle([205, 370, 307, 405], 12, fill=f)
    elif name == "wallet":
        d.rounded_rectangle([110, 160, 402, 370], 36, fill=f)
        d.rounded_rectangle([300, 225, 420, 305], 24, fill=o)
        d.ellipse([330, 250, 360, 280], fill=f)
    elif name == "calendar":
        d.rounded_rectangle([120, 140, 392, 392], 30, fill=f)
        d.rectangle([120, 140, 392, 210], fill=rgb(OUTLINE))
        for i in range(3):
            for j in range(3):
                d.rounded_rectangle([160 + i * 70, 235 + j * 50, 200 + i * 70, 268 + j * 50], 6, fill=o)
    elif name == "hotel":
        d.rectangle([150, 120, 362, 400], fill=f)
        for i in range(2):
            for j in range(3):
                d.rectangle([185 + i * 85, 160 + j * 65, 240 + i * 85, 205 + j * 65], fill=o)
        d.rectangle([225, 340, 287, 400], fill=o)
    else:  # 不認得就畫一個圓點
        d.ellipse([196, 196, 316, 316], fill=f)
    return img.resize((size, size), Image.LANCZOS)


ICON_KEYWORDS = [
    ("card", ["卡", "刷", "信用"]), ("plane", ["機票", "飛", "航", "出國", "旅", "里程"]),
    ("hotel", ["飯店", "住", "訂房"]), ("percent", ["%", "回饋", "折", "優惠"]),
    ("gift", ["禮", "贈", "首刷"]), ("calendar", ["日", "月", "期限", "截止"]),
    ("cart", ["買", "購", "網購", "超市"]), ("wallet", ["省", "錢", "預算"]),
    ("coin", ["$", "元", "NT"]), ("bulb", ["技巧", "小撇步", "提醒", "注意"]),
]


def guess_icon(text):
    for name, kws in ICON_KEYWORDS:
        if any(k in str(text) for k in kws):
            return name
    return "star"


# ---------------------------------------------------------------- 罐仔（會飛的存錢罐，內容部定稿）
FACES = ["happy", "joy", "wink", "shock", "think", "sad", "smug", "love", "angry"]
POSES = ["fly", "wave", "point", "cheer", "card", "coin", "plane", "think", "calc"]
_WING_PIVOT = {"L": (277, 407.5), "R": (523, 407.5)}  # 素材圖座標（800x800）
_CROP = (70, 90, 730, 750)  # 角色所在正方形區域


@lru_cache(maxsize=64)
def _sprite(name):
    return Image.open(os.path.join(SPRITE_DIR, name + ".png")).convert("RGBA")


@lru_cache(maxsize=512)
def draw_mascot(size=400, flap=0.0, blink=False, face="happy", pose="fly"):
    """罐仔角色圖（透明背景正方形）。flap -1~1 翅膀角度；blink 眨眼。
    face: happy joy wink shock think sad smug love angry
    pose: fly wave point cheer card coin plane think calc
    素材來自 assets/canzai/（由 assets/export_sprites.js 從內容部定稿輸出）。"""
    face = face if face in FACES else "happy"
    pose = pose if pose in POSES else "fly"
    if blink and face in ("happy", "think"):
        face = "joy"
    img = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
    ang = flap * 22
    for side, sgn in (("L", -1), ("R", 1)):
        w = _sprite("wing_" + side).rotate(sgn * ang, center=_WING_PIVOT[side], resample=Image.BICUBIC)
        img.alpha_composite(w)
    img.alpha_composite(_sprite(f"body_{face}_{pose}"))
    return img.crop(_CROP).resize((size, size), Image.LANCZOS)


def load_character(path, size):
    """讀入正式的罐仔角色 PNG（建議透明背景、正方形）。"""
    im = Image.open(path).convert("RGBA")
    im.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((size - im.width) // 2, (size - im.height) // 2))
    return canvas


def fmt_number(v, decimals=0):
    if decimals:
        return f"{v:,.{decimals}f}"
    return f"{int(round(v)):,}"
