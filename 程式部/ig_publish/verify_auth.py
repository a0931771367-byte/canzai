"""IG 授權後一鍵驗證：帳號開通、Meta App 授權完成後跑一次，一小時內確認發文、抓數據、讀留言都通。

    python3 verify_auth.py                         # 只讀：token、帳號、發文額度、抓數據、讀留言
    python3 verify_auth.py --story URL             # 再加測試限動的發文前檢查＋建立容器（不會發出去）
    python3 verify_auth.py --story URL --publish   # 真的發一則測試限動（24 小時後自動消失）

URL 是公開的 JPEG 網址（例如放在 GitHub Pages 的 test_story.jpg，用 make_test_story.py 產生）。
token：環境變數 IG_TOKEN 優先，否則讀 數據部/.ig_token（和 ig_publish.py 同一份）。
結果印在畫面上，也寫成 ig_publish/授權驗證報告_YYYYMMDD-HHMM.md。任何一項失敗結束碼是 1。

注意：這個雲端環境連不到 graph.instagram.com，要在罐子的電腦或 GitHub Actions 跑。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://graph.instagram.com/v23.0"
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.environ.get("IG_TOKEN_FILE", os.path.join(os.path.dirname(os.path.dirname(HERE)), "數據部", ".ig_token"))
EXPECTED_USER = "canzai.money"

# 常見錯誤碼 → 怎麼修（Meta 錯誤訊息是英文，這裡翻成要做的事）
FIX = {
    190: "token 無效或過期：到 Meta 開發者後台重新產生長效 token，存回 數據部/.ig_token",
    10: "缺權限：App 授權時沒勾到這個權限，重新授權並勾選 instagram_business_basic、content_publish、manage_comments、manage_insights",
    200: "缺權限：同上，重新授權並勾齊四個權限",
    100: "參數或欄位不支援：多半是帳號還不是專業帳號（商業或創作者），到 IG 設定切換",
    4: "呼叫太頻繁：等一小時再跑",
    9004: "圖片網址抓不到：確認是公開的 https 網址、JPEG 格式",
    36003: "圖片比例不符：限動用 9:16（1080x1920）",
}


class ApiError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body
        try:
            err = json.loads(body).get("error", {})
        except ValueError:
            err = {}
        self.code, self.msg = err.get("code"), err.get("message", body[:200])
        super().__init__(f"HTTP {status}／code {self.code}：{self.msg}")

    def hint(self):
        return FIX.get(self.code, "看上面的錯誤訊息，或把報告貼給程式部")


def call(method, path, token, **params):
    params["access_token"] = token
    data = urllib.parse.urlencode(params)
    url = f"{API}/{path}"
    req = urllib.request.Request(url + "?" + data) if method == "GET" else \
        urllib.request.Request(url, data=data.encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode(errors="replace"))


def list_all_media(uid, token, cap=500):
    out, after = [], None
    while len(out) < cap:
        kw = dict(fields="id,timestamp", limit=100)
        if after:
            kw["after"] = after
        r = call("GET", f"{uid}/media", token, **kw)
        out += r.get("data", [])
        after = (r.get("paging") or {}).get("cursors", {}).get("after")
        if not (r.get("paging") or {}).get("next"):
            break
    return out


class Report:
    def __init__(self):
        self.rows, self.failed = [], False

    def add(self, name, ok, detail, hint=""):
        mark = {True: "✅", False: "❌", None: "⚠️"}[ok]
        if ok is False:
            self.failed = True
        self.rows.append((mark, name, detail, hint))
        print(f"{mark} {name}：{detail}" + (f"\n   → {hint}" if hint else ""))

    def write(self):
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        path = os.path.join(HERE, f"授權驗證報告_{ts}.md")
        lines = [f"# IG 授權驗證報告 {ts}", "", f"結果：{'❌ 有項目失敗' if self.failed else '✅ 全部通過'}", "",
                 "| | 項目 | 結果 | 怎麼修 |", "|---|---|---|---|"]
        lines += [f"| {m} | {n} | {d.replace('|', '／')} | {h} |" for m, n, d, h in self.rows]
        open(path, "w").write("\n".join(lines) + "\n")
        print(f"\n報告：{path}")


def step(rep, name, fn):
    """跑一項檢查；API 錯誤記成失敗並附修法。回傳 fn 的結果或 None。"""
    try:
        return fn()
    except ApiError as e:
        rep.add(name, False, str(e), e.hint())
    except urllib.error.URLError as e:
        rep.add(name, False, f"連不到 Instagram：{e.reason}", "這台機器的網路擋住 graph.instagram.com，換罐子的電腦或 GitHub Actions 跑")
    return None


def check_image_url(url):
    """測試限動的發文前檢查：公開、https、JPEG、8MB 以內、9:16。"""
    problems = []
    if not url.startswith("https://"):
        problems.append("要用 https 網址")
    req = urllib.request.Request(url, headers={"User-Agent": "canzai-verify/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        ctype = r.headers.get("Content-Type", "")
        body = r.read(9 * 1024 * 1024)
    if "jpeg" not in ctype and not body[:3] == b"\xff\xd8\xff":
        problems.append(f"不是 JPEG（{ctype or '沒有 Content-Type'}），IG API 只收 JPEG")
    if len(body) > 8 * 1024 * 1024:
        problems.append("超過 8MB")
    try:
        from io import BytesIO
        from PIL import Image
        w, h = Image.open(BytesIO(body)).size
        if abs(w / h - 9 / 16) > 0.02:
            problems.append(f"尺寸 {w}x{h} 不是 9:16，限動會被裁切")
        size = f"{w}x{h}"
    except ImportError:
        size = "（沒裝 Pillow，略過尺寸）"
    return problems, f"{ctype}，{len(body) // 1024}KB，{size}"


def main():
    ap = argparse.ArgumentParser(description="IG 授權後一鍵驗證")
    ap.add_argument("--story", metavar="URL", help="測試限動用的公開 JPEG 網址")
    ap.add_argument("--publish", action="store_true", help="真的發出測試限動（沒加只建立容器、不發）")
    ap.add_argument("--user", default=EXPECTED_USER, help=f"預期的帳號（預設 {EXPECTED_USER}）")
    a = ap.parse_args()
    rep = Report()

    # 1. token
    token = os.environ.get("IG_TOKEN") or (open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else "")
    if not token:
        rep.add("token", False, "找不到 token", f"設定環境變數 IG_TOKEN，或存到 {TOKEN_FILE}")
        rep.write()
        sys.exit(1)
    if not token.startswith("IG"):
        rep.add("token", None, "token 不是 IG 開頭，可能是 Facebook 登入的 token", "本專案用 Instagram 登入（graph.instagram.com），要用 IG 開頭的 token")
    else:
        rep.add("token", True, f"已讀到（{token[:6]}…，{len(token)} 字元）")

    # 2. 帳號
    me = step(rep, "帳號", lambda: call("GET", "me", token, fields="user_id,username,account_type,media_count,followers_count"))
    if me is None:
        rep.write()
        sys.exit(1)
    uid = me.get("user_id") or me.get("id")
    ok_user = me.get("username") == a.user
    rep.add("帳號", ok_user, f"@{me.get('username')}（{me.get('account_type')}），{me.get('media_count', 0)} 則貼文、"
            f"{me.get('followers_count', 0)} 位粉絲", "" if ok_user else f"授權到的不是 @{a.user}，重新授權時選對帳號")
    if me.get("account_type") not in ("BUSINESS", "MEDIA_CREATOR"):
        rep.add("專業帳號", False, f"帳號類型是 {me.get('account_type')}", "到 IG 設定 → 帳號類型與工具 → 切換為專業帳號")

    # 3. 發文權限與額度（content_publish）
    lim = step(rep, "發文額度", lambda: call("GET", f"{uid}/content_publishing_limit", token, fields="config,quota_usage"))
    if lim is not None:
        d = (lim.get("data") or [{}])[0]
        total = (d.get("config") or {}).get("quota_total", 100)
        rep.add("發文額度", True, f"24 小時內已用 {d.get('quota_usage', 0)}／{total} 則（content_publish 權限正常）")

    # 4. 抓數據（basic＋insights）
    media = step(rep, "抓貼文", lambda: call("GET", f"{uid}/media", token, limit=5,
                                            fields="id,caption,media_type,timestamp,like_count,comments_count,permalink"))
    items = (media or {}).get("data", [])
    if media is not None:
        rep.add("抓貼文", True, f"抓到 {len(items)} 則" + (f"，最新 {items[0]['timestamp'][:10]}" if items else "（帳號還沒有貼文，正常）"))
    ins = step(rep, "帳號洞察", lambda: call("GET", f"{uid}/insights", token, metric="reach,follower_count", period="day"))
    if ins is not None:
        vals = {m["name"]: (m.get("values") or [{}])[-1].get("value") for m in ins.get("data", [])}
        rep.add("帳號洞察", True, f"manage_insights 權限正常：{vals or '新帳號還沒有數據'}")

    # 4b. 舊貼文清理（社群部：上線前舊貼文全部封存；封存的貼文 API 不會列出）
    launch = datetime.fromisoformat(os.environ.get("CANZAI_LAUNCH", "2026-11-04T01:00:00+08:00"))
    allm = step(rep, "舊貼文封存", lambda: list_all_media(uid, token))
    if allm is not None:
        old = [m for m in allm if datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z") < launch]
        rep.add("舊貼文封存", None if old else True,
                f"還有 {len(old)} 則上線前的舊貼文沒封存" + (f"（最舊 {old[-1]['timestamp'][:10]}）" if old else "，清理完成"),
                "到 IG App 逐則按「⋯」→「封存」（社群部/上線準備/舊帳號整理建議.md）。沒封存也不會自動回覆它們的留言" if old else "")
        items = [m for m in items if datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z") >= launch] or items

    # 5. 讀留言（manage_comments）
    with_c = next((m for m in items if m.get("comments_count")), items[0] if items else None)
    if with_c is None:
        rep.add("讀留言", None, "還沒有貼文可以測，發第一則後再跑一次", "")
    else:
        cm = step(rep, "讀留言", lambda: call("GET", f"{with_c['id']}/comments", token, fields="id,text,username,timestamp"))
        if cm is not None:
            n = len(cm.get("data", []))
            rep.add("讀留言", True, f"manage_comments 權限正常，{with_c['id']} 讀到 {n} 則留言"
                    + ("" if n else "（這則沒有留言，權限沒報錯就算通）"))

    # 6. 測試限動
    if a.story:
        try:
            problems, info = check_image_url(a.story)
            rep.add("限動圖片檢查", not problems, info + ("；" + "；".join(problems) if problems else ""),
                    "換一張 1080x1920 JPEG（make_test_story.py 產生）" if problems else "")
        except Exception as e:  # noqa: BLE001 網址抓不到等
            problems = [str(e)]
            rep.add("限動圖片檢查", False, f"抓不到圖片：{e}", "確認網址公開（無痕視窗打得開）")
        if not problems:
            c = step(rep, "限動容器", lambda: call("POST", f"{uid}/media", token, image_url=a.story, media_type="STORIES"))
            if c is not None:
                cid, st = c["id"], None
                for _ in range(12):
                    st = call("GET", cid, token, fields="status_code").get("status_code")
                    if st in ("FINISHED", "ERROR", "EXPIRED"):
                        break
                    time.sleep(5)
                rep.add("限動容器", st == "FINISHED", f"容器 {cid} 狀態 {st}",
                        "" if st == "FINISHED" else "IG 處理失敗，多半是圖片格式或比例問題")
                if st == "FINISHED" and a.publish:
                    pub = step(rep, "發出限動", lambda: call("POST", f"{uid}/media_publish", token, creation_id=cid))
                    if pub is not None:
                        rep.add("發出限動", True, f"已發出（media id {pub.get('id')}），24 小時後自動消失，要早點刪請在 IG App 手動刪")
                elif st == "FINISHED":
                    rep.add("發出限動", None, "只建立容器沒發出（加 --publish 才會真的發）", "")
    else:
        rep.add("測試限動", None, "這次沒測（加 --story 公開圖片網址）", "")

    rep.write()
    sys.exit(1 if rep.failed else 0)


if __name__ == "__main__":
    main()
