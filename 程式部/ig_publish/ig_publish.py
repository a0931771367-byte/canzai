#!/usr/bin/env python3
"""IG 自動發文腳本（Instagram API with Instagram Login，graph.instagram.com）。

尚未接上真實帳號：需要先完成 技術方案.md 的「一次性設定」，拿到 IG_USER_ID 與 IG_TOKEN。
沒有設定時加 --dry-run 可以檢查流程與檔案。

用法：
    # 發一則（資料夾內放 01.jpg 02.jpg… 為輪播；放一支 .mp4 為 Reels；caption.txt 為文案）
    python3 ig_publish.py post 貼文資料夾 --base-url https://<公開網址>/貼文資料夾
    python3 ig_publish.py post 貼文資料夾 --base-url ... --dry-run
    python3 ig_publish.py limit          # 查 24 小時內還能發幾則
    python3 ig_publish.py refresh        # 延長 token（每 50 天跑一次即可，排程自動做）

環境變數：IG_USER_ID、IG_TOKEN（放在 GitHub Actions secrets 或 .env，不要寫進程式）。
媒體必須是公開網址，IG 伺服器會自己來抓；圖片只收 JPEG（本腳本會自動把 PNG 轉 JPEG）。
"""
import argparse
import glob
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = "https://graph.instagram.com/v23.0"
# token 統一存放：環境變數 IG_TOKEN 優先，否則讀 數據部/.ig_token（續期由數據部每週一的排程統一處理）
_TOKEN_FILE = os.environ.get("IG_TOKEN_FILE", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "數據部", ".ig_token"))
if not os.environ.get("IG_TOKEN") and os.path.exists(_TOKEN_FILE):
    os.environ["IG_TOKEN"] = open(_TOKEN_FILE).read().strip()
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
from ig_skills import humanize, lint_caption  # noqa: E402  /ig-human、/ig-caption
import ig_api  # noqa: E402  IG 開頭 → graph.instagram.com；EAA 開頭 → graph.facebook.com
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "factcheck"))
import factcheck  # noqa: E402  發文當天自動重查官網
from compliance import check_folder  # noqa: E402  法務部合規檢查（規則每次重新載入）


def call(method, path, **params):
    token = os.environ.get("IG_TOKEN")
    params["access_token"] = token
    data = urllib.parse.urlencode(params).encode()
    url = f"{ig_api.base(token)}/{path}"
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"API 錯誤 {e.code}：{e.read().decode()}")


def png_to_jpg(folder):
    from PIL import Image
    for p in sorted(glob.glob(os.path.join(folder, "*.png"))):
        if os.path.basename(p).startswith("_"):
            continue
        j = os.path.splitext(p)[0] + ".jpg"
        if not os.path.exists(j):
            Image.open(p).convert("RGB").save(j, quality=93)


def wait_ready(cid, dry):
    if dry:
        return
    for _ in range(30):  # 最多等 5 分鐘（Meta 建議每分鐘查一次、不超過 5 分鐘；影片處理通常 10～60 秒）
        st = call("GET", cid, fields="status_code").get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise SystemExit(f"媒體處理失敗：{st}")
        time.sleep(10)
    raise SystemExit("等待逾時")


def account_gate(dry, manual=False):
    """發文前確認：排程已啟用（brands.json schedule_enabled），且 token 授權到的帳號就是 ig_handle。"""
    cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "brands.json"), encoding="utf-8"))["canzai"]
    if not cfg.get("schedule_enabled") and not dry and not manual:
        raise SystemExit("⏸ 排程還沒啟用（brands.json schedule_enabled=false）：" + cfg.get("schedule_enabled_note", ""))
    if dry:
        return
    tok = os.environ.get("IG_TOKEN", "")
    left = ig_api.token_days_left(tok)
    if left is not None and left <= 0:
        raise SystemExit("⛔ IG token 已過期，請到 Meta 後台重新產生，更新 secret IG_TOKEN")
    if left is not None and left < 10:
        print(f"⚠️ IG token 只剩 {left:.0f} 天，請盡快到 Meta 後台重新產生")
    me = call("GET", ig_api.uid(tok), fields="username")
    if me.get("username") != cfg["ig_handle"]:
        raise SystemExit(f"⛔ token 授權的帳號是 @{me.get('username')}，不是 @{cfg['ig_handle']}，不發文")


def _cap_key(t):
    import re
    t = re.sub(r"[#＃]\S+", "", (t or ""))  # Hashtag 不比
    return re.sub(r"\s+", "", t)[:40]


def find_duplicate(caption, hours=48):
    """IG 上最近 hours 小時內，文案開頭 40 字（去空白）相同的貼文。查不到 API 時回傳 None（不擋）。"""
    import datetime as dt
    key = _cap_key(caption)
    if not key:
        return None
    try:
        res = call("GET", f"{ig_api.uid(os.environ.get('IG_TOKEN', ''))}/media", fields="id,caption,timestamp", limit=25)
    except SystemExit as e:
        print(f"（防重複檢查略過：{e}）")
        return None
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    for m in res.get("data", []):
        ts = dt.datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        other = _cap_key(m.get("caption"))
        n = min(len(key), len(other))
        if ts >= since and n >= 15 and key[:n] == other[:n]:
            return m
    return None


def post(folder, base_url, dry=False, force=False, manual=False):
    account_gate(dry, manual)
    uid = os.environ.get("IG_USER_ID", "<IG_USER_ID>")
    cap_file = os.path.join(folder, "caption.txt")
    caption = open(cap_file, encoding="utf-8").read().strip() if os.path.exists(cap_file) else ""
    # 第一關：發文當天重查官網（貼文.md 的「發文前查證」），有疑慮就不發
    post_md = os.path.join(folder, "貼文.md")
    if os.path.exists(post_md):
        post_info = factcheck.parse_post(post_md)
        fc = factcheck.check_post(post_info)
        with open(os.path.join(folder, "查證報告.md"), "w", encoding="utf-8") as f:
            f.write(factcheck.report_md([fc]))
        print(f"官網重查：{fc['判定']}")
        for d in fc["明細"]:
            if d["結果"] != "PASS":
                print(f"  [{d['結果']}] {d['原因']}")
        if fc["判定"] == "BLOCK":
            print("⛔ 已擋下，不發文。查證報告.md 已寫入資料夾，請通知內容部。")
            sys.exit(2)
        caption = caption or post_info["caption"]
    elif not force:
        raise SystemExit("找不到 貼文.md（含「發文前查證」），不發文；確定沒有查證需求請加 --force")
    # 第二關：法務部合規檢查（FAIL 不發；WARN 印出來由排程的 Claude 依合規檢查清單判斷）
    comp = check_folder(folder)
    print(f"合規檢查：{comp['verdict']}（規則版本 {comp['rules_version']}，依據 {comp['source']}）")
    for x in comp["fails"]:
        print(f"  [FAIL] {x}")
    for x in comp["warns"]:
        print(f"  [WARN] {x}")
    if comp["verdict"] == "FAIL":
        print("⛔ 合規檢查未通過，不發文。請通知內容部修改。")
        sys.exit(1)
    # 第三關：/ig-human 去 AI 痕跡，/ig-caption 檢查文案（FAIL 就不發）
    caption, _ = humanize(caption)
    lint = lint_caption(caption)
    for c in lint["checks"]:
        if c["status"] != "PASS":
            print(f"  [{c['status']}] {c['check']}：{c['detail']}")
    print(f"文案檢查：{lint['verdict']}")
    if lint["verdict"] == "FAIL" and not force:
        raise SystemExit("文案檢查未通過，修改 caption.txt 後再發（或加 --force）")
    # 防重複：IG 上最近 48 小時已經有同一篇（例如罐子用 Metricool 或 App 手動發過）就不發，結束碼 4
    if not dry:
        dup = find_duplicate(caption)
        if dup:
            print(f"⏭ IG 上已經有這篇（{dup.get('timestamp', '')[:16]}，貼文 ID：{dup['id']}），不重複發")
            sys.exit(4)
    png_to_jpg(folder)
    vids = sorted(glob.glob(os.path.join(folder, "*.mp4")))
    imgs = sorted(p for p in glob.glob(os.path.join(folder, "*.jpg")) if not os.path.basename(p).startswith("_")
                  and not p.endswith("_cover.jpg"))
    url = lambda p: base_url.rstrip("/") + "/" + urllib.parse.quote(os.path.basename(p))
    fake = iter(range(1000, 9999))

    def create(**kw):
        if dry:
            print("  POST /media", kw)
            return f"container_{next(fake)}"
        return call("POST", f"{uid}/media", **kw)["id"]

    if vids:
        print(f"Reels：{os.path.basename(vids[0])}")
        kw = dict(media_type="REELS", video_url=url(vids[0]), caption=caption, share_to_feed="true")
        covers = glob.glob(os.path.join(folder, "*_cover.jpg"))
        if covers:
            kw["cover_url"] = url(covers[0])
        cid = create(**kw)
    elif len(imgs) == 1:
        print("單張圖片")
        cid = create(image_url=url(imgs[0]), caption=caption)
    elif imgs:
        print(f"輪播 {len(imgs)} 張")
        kids = []
        for p in imgs[:10]:  # 保守用 10 張上限（官方文件新舊版寫 10 或 20）
            k = create(image_url=url(p), is_carousel_item="true")
            wait_ready(k, dry)
            kids.append(k)
        cid = create(media_type="CAROUSEL", children=",".join(kids), caption=caption)
    else:
        raise SystemExit("資料夾裡沒有 .jpg/.png/.mp4")
    wait_ready(cid, dry)
    if dry:
        print(f"  POST /media_publish creation_id={cid}\n[dry-run] 流程檢查完成，未實際發文")
        return
    res = call("POST", f"{uid}/media_publish", creation_id=cid)
    print("已發布，貼文 ID：", res.get("id"))


def main():
    ap = argparse.ArgumentParser(description="IG 自動發文")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("post"); p.add_argument("folder"); p.add_argument("--base-url", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="文案檢查 FAIL 也照發")
    p.add_argument("--manual", action="store_true", help="罐子自己手動發（例如測試文、00 自介）：排程沒解鎖也能發，帳號核對和三道關卡照跑")
    sub.add_parser("limit")
    sub.add_parser("refresh")
    a = ap.parse_args()
    if os.environ.get("IG_TOKEN") and not os.environ.get("IG_USER_ID") and not getattr(a, "dry_run", False):
        if ig_api.is_fb(os.environ["IG_TOKEN"]):
            os.environ["IG_USER_ID"] = ig_api.CANZAI_IG_ID
        else:
            me = call("GET", "me", fields="user_id")  # IG_USER_ID 沒填就自己查
            os.environ["IG_USER_ID"] = str(me.get("user_id") or me.get("id"))
    if a.cmd != "post" or not a.dry_run:
        if not os.environ.get("IG_TOKEN") or not os.environ.get("IG_USER_ID"):
            raise SystemExit("缺少 IG_TOKEN / IG_USER_ID，請先完成 技術方案.md 的一次性設定")
    if a.cmd == "post":
        post(a.folder, a.base_url, a.dry_run, a.force, a.manual)
    elif a.cmd == "limit":
        print(call("GET", f"{os.environ['IG_USER_ID']}/content_publishing_limit", fields="config,quota_usage"))
    elif a.cmd == "refresh":
        req = urllib.request.Request("https://graph.instagram.com/refresh_access_token?" + urllib.parse.urlencode(
            dict(grant_type="ig_refresh_token", access_token=os.environ["IG_TOKEN"])))
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
        print("新 token 有效秒數：", res.get("expires_in"), "（請把新 token 存回 secrets）")
        print(res.get("access_token"))


if __name__ == "__main__":
    main()
