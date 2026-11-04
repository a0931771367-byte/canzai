"""產生測試限動圖（1080x1920 JPEG），給 verify_auth.py --story 用。放到公開網址（例如 GitHub Pages）再測。
    python3 make_test_story.py            # 輸出 ig_publish/test_story.jpg
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
from PIL import Image, ImageDraw  # noqa: E402
import canzai  # noqa: E402

W, H = 1080, 1920
img = Image.new("RGB", (W, H), "#FFF8EC")
d = ImageDraw.Draw(img)
m = canzai.draw_mascot(620, face="joy", pose="wave")
img.paste(m, ((W - m.width) // 2, 380), m)
f1, f2 = canzai.font("black", 96), canzai.font("bold", 48)
for text, f, y, col in [("罐仔開張測試中", f1, 1080, "#1E2A4A"), ("這則限動是系統測試，很快就會刪掉", f2, 1220, "#56607A")]:
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, y), text, font=f, fill=col)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_story.jpg")
img.save(out, quality=92)
print(out)
