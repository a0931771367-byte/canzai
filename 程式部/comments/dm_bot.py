#!/usr/bin/env python3
"""「選卡」自動回覆（社群部《選卡私訊_API版設計》）。GitHub Actions 每 5 分鐘跑一次。

每輪做三件事：
  ① 最近 10 篇貼文的新留言含「選卡」→ 公開回覆（3 種輪替）＋留言私訊第一則
  ② 新私訊：「選卡／幫我選卡／配卡」→ 私訊第一則（24 小時內同一人只送一次）；
     關鍵字沒對到、這人也還沒收過第一則 → 有 ANTHROPIC_API_KEY 時問 Haiku 5.5 是不是想選卡（intent.py），是就送第一則；
     已送過第一則的人回的話 → 寫進試算表「選卡待回覆」；其他 → 寫進「私訊待處理」
  ③ 試算表裡罐子勾了「核准」的回覆 → 送出，並在「送出狀態」寫上時間
     （雲端 Claude 每天 12:00、21:00 在試算表填「罐仔回覆草稿」，罐子看過勾核准）

資料放哪（法務部 11/5 審查）：
  帳號名稱、訊息內容 → 只在罐子的 Google 試算表（每天自動刪 90 天前的列）
  去重狀態 → 只有 HMAC 雜湊過的編號和時間，存在 .dm_state/state.json，由 Actions cache 帶到下一輪，不進 git

    python3 dm_bot.py               # 正式跑
    python3 dm_bot.py --dry-run     # 只印出會做什麼，不送、不寫狀態
    python3 dm_bot.py --dump        # 印出狀態（只有雜湊值和時間）

環境變數：IG_TOKEN（EAA 或 IG 開頭）、CANZAI_BOT_KEY、CANZAI_SHEET_URL、IG_USER_ID（選填）、IG_PAGE_ID（選填）
防呆：一則留言只私訊一次；同一人 24 小時一次；略過自己；每輪最多 30 則；個資遮蔽；90 天刪除；連續 3 次 API 錯誤就停。
"""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "common"))
import ig_api  # noqa: E402
from intent import Intent  # noqa: E402

STATE_FILE = os.environ.get("CANZAI_STATE_FILE", os.path.join(os.path.dirname(os.path.dirname(HERE)), ".dm_state", "state.json"))
TZ = dt.timezone(dt.timedelta(hours=8))
LAUNCH = dt.datetime.fromisoformat(os.environ.get("CANZAI_LAUNCH", "2026-11-04T01:00:00+08:00"))
ME = "canzai_money"
MAX_SENDS = 30
KEEP_DAYS = 90

FIRST_DM = """嗨，罐仔幫你排雙11 刷卡順序 🫙
先回我兩件事就好：
1. 你手上有哪幾類卡？（例如網購卡、一般回饋卡、平台聯名卡，不用給卡號）
2. 雙11 主要在哪個平台買？

這兩題只用來幫你配卡，罐仔不會存你的卡號或個資，聊完 90 天內刪除，不想回答也沒關係。"""
PUBLIC = ["私訊你了，看一下收件匣", "傳過去了，回我兩題就好", "已私訊，罐仔等你回"]
KEYWORD_COMMENT = re.compile(r"選卡")
KEYWORD_DM = re.compile(r"(幫我)?選卡|配卡")
# 個資遮蔽：信用卡號（13～19 碼，可含空白或-）、身分證字號
CARD = re.compile(r"(?:\d[ -]?){13,19}")
TWID = re.compile(r"[A-Za-z][12]\d{8}")


def mask(t):
    t2 = CARD.sub("［卡號已遮蔽］", t or "")
    t2 = TWID.sub("［身分證已遮蔽］", t2)
    return t2, t2 != (t or "")


# ---------------------------------------------------------------- 狀態（只有雜湊值，不進 git）
# 法務部《私訊狀態檔審查_2026-11-05》：去重狀態只存 HMAC-SHA256（秘密鹽值）後的編號和時間，
# 放在 GitHub Actions cache（不進 git、不公開下載）。帳號名稱和訊息內容只寫進罐子的 Google 試算表。
def _key():
    k = os.environ.get("CANZAI_BOT_KEY")
    if not k:
        sys.exit("缺少 CANZAI_BOT_KEY（試算表的 setup 會產生，貼到 repo secret）")
    return k.encode()


def h(x):
    """編號 → HMAC-SHA256（鹽值由 CANZAI_BOT_KEY 衍生），只留前 32 碼，認不回原本是誰。"""
    salt = hmac.new(_key(), b"canzai-id-salt", hashlib.sha256).digest()
    return hmac.new(salt, str(x).encode(), hashlib.sha256).hexdigest()[:32]


def load_state():
    empty = {"comments": {}, "people": {}, "errors": 0, "public_used": {}, "seen_msgs": {}}
    if not os.path.exists(STATE_FILE):
        return empty
    return {**empty, **json.load(open(STATE_FILE, encoding="utf-8"))}


def save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    json.dump(st, open(STATE_FILE, "w", encoding="utf-8"))


def purge(st, now):
    cut = (now - dt.timedelta(days=KEEP_DAYS)).isoformat()
    st["comments"] = {k: v for k, v in st["comments"].items() if v >= cut}
    st["seen_msgs"] = {k: v for k, v in st["seen_msgs"].items() if v >= cut}
    st["people"] = {k: v for k, v in st["people"].items() if v.get("last", "") >= cut}


# ---------------------------------------------------------------- 試算表（Apps Script 網頁應用程式）
class Sheet:
    """罐子的「罐仔私訊」試算表。帳號名稱、訊息只存在這裡；90 天前的資料由試算表每天自動刪。"""

    def __init__(self, dry):
        self.url, self.dry = os.environ.get("CANZAI_SHEET_URL", ""), dry
        if not self.url and not dry:
            sys.exit("缺少 CANZAI_SHEET_URL（試算表 Apps Script 部署後的網址）")

    def call(self, action, **body):
        if self.dry and action != "outbox":
            print(f"[dry-run] 試算表 {action}：{json.dumps(body, ensure_ascii=False)[:80]}")
            return {"ok": True}
        if not self.url:
            return {"ok": True, "items": [], "late": 0}
        data = json.dumps({"key": _key().decode(), "action": action, **body}, ensure_ascii=False).encode()
        req = urllib.request.Request(self.url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.load(r)
        except (urllib.error.URLError, ValueError) as e:
            raise RuntimeError(f"試算表 {action} 失敗：{e}")
        if not out.get("ok"):
            raise RuntimeError(f"試算表 {action} 回錯誤：{out.get('error')}")
        return out


# ---------------------------------------------------------------- API
class Api:
    def __init__(self, token, dry):
        self.token, self.dry, self.sent = token, dry, 0
        self.uid = ig_api.uid(token)
        self.page = os.environ.get("IG_PAGE_ID")

    def call(self, method, path, **params):
        params["access_token"] = self.token
        url = f"{ig_api.base(self.token)}/{path}"
        if method == "GET":
            req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params))
        else:
            body = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v) for k, v in params.items()}
            req = urllib.request.Request(url, data=urllib.parse.urlencode(body).encode(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            # 公開 repo 的 Actions 紀錄任何人都看得到：只印狀態碼和 Meta 錯誤碼，不印回應全文和路徑裡的編號
            try:
                err = json.loads(e.read().decode(errors="replace")).get("error", {})
            except ValueError:
                err = {}
            raise RuntimeError(f"{method} {path.split('/')[-1]} → HTTP {e.code}，錯誤碼 {err.get('code')}／{err.get('error_subcode')}")

    def send(self, what, method, path, **params):
        if self.sent >= MAX_SENDS:
            print(f"⏸ 這輪已送 {MAX_SENDS} 則，剩下的下一輪再送")
            return None
        self.sent += 1
        print(("[dry-run] " if self.dry else "") + what)
        return {"id": "dry"} if self.dry else self.call(method, path, **params)

    def messages_node(self):
        return self.page or self.uid

    def private_reply(self, comment_id):
        return self.send(f"留言私訊 1 則（{h(comment_id)[:8]}）", "POST", f"{self.messages_node()}/messages",
                         recipient={"comment_id": comment_id}, message={"text": FIRST_DM})

    def dm(self, igsid, text):
        return self.send(f"私訊 1 則（{h(igsid)[:8]}）", "POST", f"{self.messages_node()}/messages",
                         recipient={"id": igsid}, message={"text": text})


# ---------------------------------------------------------------- 主流程
def recent(ts_iso, now, hours=24):
    if not ts_iso:
        return False
    t = dt.datetime.fromisoformat(re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", str(ts_iso).replace("Z", "+00:00")))
    return (now - t) < dt.timedelta(hours=hours)


def handle_comments(api, st, sheet, now):
    media = api.call("GET", f"{api.uid}/media", fields="id,timestamp", limit=10).get("data", [])
    for m in media:
        if dt.datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z") < LAUNCH:
            continue
        cs = api.call("GET", f"{m['id']}/comments", fields="id,text,username,timestamp,from", limit=50).get("data", [])
        for c in cs:
            ck = h(c["id"])
            if ck in st["comments"] or c.get("username") == ME or not KEYWORD_COMMENT.search(c.get("text", "")):
                continue
            person = st["people"].setdefault(h((c.get("from") or {}).get("id") or c.get("username", "")), {})
            used = st["public_used"].setdefault(m["id"], {})
            pick = min(PUBLIC, key=lambda p: used.get(p, 0))
            if used.get(pick, 0) < 3:
                if api.send(f"公開回覆 1 則（{ck[:8]}）：{pick}", "POST", f"{c['id']}/replies", message=pick) is None:
                    return
                used[pick] = used.get(pick, 0) + 1
            if recent(person.get("first_dm"), now):
                print("略過私訊：這個人 24 小時內已收過第一則")
            else:
                if api.private_reply(c["id"]) is None:
                    return
                person["first_dm"] = now.isoformat()
            person["last"] = now.isoformat()
            st["comments"][ck] = now.isoformat()


def handle_dms(api, st, sheet, now, intent=None):
    node = api.messages_node()
    convs = api.call("GET", f"{node}/conversations", platform="instagram",
                     fields="id,updated_time,messages.limit(5){id,message,from,created_time}", limit=20).get("data", [])
    for cv in convs:
        for msg in reversed((cv.get("messages") or {}).get("data", [])):
            mk, frm = h(msg["id"]), msg.get("from") or {}
            if mk in st["seen_msgs"]:
                continue
            if frm.get("username") == ME or frm.get("id") == api.uid:
                st["seen_msgs"][mk] = now.isoformat()
                continue
            who, text = frm.get("id", ""), msg.get("message", "")
            person = st["people"].setdefault(h(who), {})
            safe, masked = mask(text)
            hit = bool(KEYWORD_DM.search(text) and len(text) <= 12)
            if not hit and intent and not person.get("first_dm") and intent.wants_card(safe):
                print(f"意圖判斷：選卡（{mk[:8]}）")
                hit = True
            if hit:
                if recent(person.get("first_dm"), now):
                    print("略過：這個人 24 小時內已收過第一則")
                else:
                    if api.dm(who, FIRST_DM) is None:
                        return
                    person["first_dm"] = now.isoformat()
            else:
                tab = "選卡待回覆" if person.get("first_dm") else "私訊待處理"
                # 先寫進試算表，成功才記成已處理；寫失敗下一輪會再試，不會漏
                sheet.call("append", tab=tab, row=[msg.get("created_time") or now.isoformat(), frm.get("username", ""),
                                                   who, safe, "是" if masked else ""])
                print(f"→ 試算表「{tab}」多一則")
            person["last"] = now.isoformat()
            st["seen_msgs"][mk] = now.isoformat()


def send_outbox(api, st, sheet, now):
    out = sheet.call("outbox")
    for o in out.get("items", []):
        if not recent(o.get("time"), now, 24):
            sheet.call("mark", tab=o["tab"], row=o["row"], value="過期（超過 24 小時，IG 不給回）")
            continue
        if api.dm(o["igsid"], o["text"]) is None:
            return
        sheet.call("mark", tab=o["tab"], row=o["row"], value=("（模擬）" if api.dry else "") + now.isoformat(timespec="minutes"))
    if out.get("late"):
        print(f"⚠️ 有 {out['late']} 則選卡回覆收到超過 20 小時還沒核准（24 小時後就不能回）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--reset-errors", action="store_true")
    a = ap.parse_args()
    st = load_state()
    if a.reset_errors:
        st["errors"] = 0
        save_state(st)
        print("已把連續錯誤次數歸零")
        return
    if a.dump:
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return
    token = os.environ.get("IG_TOKEN")
    if not token:
        print("還沒設定 IG_TOKEN，略過")
        return
    if st.get("errors", 0) >= 3 and not a.dry_run:
        sys.exit("⛔ 已連續 3 次錯誤，暫停中。修好後到 Actions 手動跑「選卡自動回覆」並勾 reset_errors")
    now = dt.datetime.now(TZ)
    api, sheet, intent = Api(token, a.dry_run), Sheet(a.dry_run), Intent(a.dry_run)
    ok = True
    for step in (handle_comments, handle_dms, send_outbox):
        try:
            if step is handle_dms:
                step(api, st, sheet, now, intent)
            else:
                step(api, st, sheet, now)
        except RuntimeError as e:
            ok = False
            print(f"❌ {step.__name__}：{e}")
    st["errors"] = 0 if ok else st.get("errors", 0) + 1
    purge(st, now)
    if not a.dry_run:
        save_state(st)
    print(f"完成：送出 {api.sent} 則，意圖判斷 {intent.calls} 次，連續錯誤 {st['errors']} 次")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
