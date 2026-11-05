#!/usr/bin/env python3
"""「選卡」自動回覆（社群部《選卡私訊_API版設計》）。GitHub Actions 每 5 分鐘跑一次。

每輪做三件事：
  ① 最近 10 篇貼文的新留言含「選卡」→ 公開回覆（3 種輪替）＋留言私訊第一則
  ② 新私訊：「選卡／幫我選卡／配卡」→ 私訊第一則（24 小時內同一人只送一次）；
     已送過第一則的人回的話 → 存「選卡待回覆」；其他 → 存「私訊待處理」
  ③ 送出 outbox 裡罐子核准過的回覆（雲端 Claude 每天 12:00、21:00 起草，核准後放進 outbox）

狀態（處理過的留言、送過的人、待回覆、outbox）存在 state/dm_state.enc：
  repo 是公開的，所以整份用 CANZAI_STATE_KEY 加密（Fernet）後才 commit。金鑰只放在 repo secret 和專案庫。

    python3 dm_bot.py               # 正式跑
    python3 dm_bot.py --dry-run     # 只印出會做什麼，不送、不寫狀態
    python3 dm_bot.py --dump        # 解密印出狀態（雲端起草用）

環境變數：IG_TOKEN（EAA 或 IG 開頭）、CANZAI_STATE_KEY、IG_USER_ID（選填）、IG_PAGE_ID（選填，留言私訊要用 Page 端點時才填）
防呆：一則留言只私訊一次；同一人 24 小時一次；略過自己；每輪最多 30 則；個資遮蔽；90 天刪除；連續 3 次 API 錯誤就停。
"""
import argparse
import datetime as dt
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

STATE_FILE = os.environ.get("CANZAI_STATE_FILE", os.path.join(os.path.dirname(os.path.dirname(HERE)), "state", "dm_state.enc"))
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


# ---------------------------------------------------------------- 狀態（加密）
def fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get("CANZAI_STATE_KEY")
    if not key:
        sys.exit("缺少 CANZAI_STATE_KEY（狀態加密金鑰）")
    return Fernet(key.encode())


_LOADED = None  # 讀進來時的內容，沒變就不重寫（Fernet 每次加密結果都不同，避免每 5 分鐘一個 commit）


def load_state():
    empty = {"comments": {}, "people": {}, "pending_card": [], "pending_other": [], "outbox": [], "errors": 0,
             "public_used": {}, "seen_msgs": {}}
    if not os.path.exists(STATE_FILE):
        return empty
    global _LOADED
    data = json.loads(fernet().decrypt(open(STATE_FILE, "rb").read()))
    st = {**empty, **data}
    _LOADED = json.dumps(st, ensure_ascii=False, sort_keys=True)
    return st


def save_state(st):
    if _LOADED == json.dumps(st, ensure_ascii=False, sort_keys=True):
        return
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    open(STATE_FILE, "wb").write(fernet().encrypt(json.dumps(st, ensure_ascii=False).encode()))


def purge(st, now):
    cut = (now - dt.timedelta(days=KEEP_DAYS)).isoformat()
    st["comments"] = {k: v for k, v in st["comments"].items() if v >= cut}
    st["seen_msgs"] = {k: v for k, v in st["seen_msgs"].items() if v >= cut}
    st["people"] = {k: v for k, v in st["people"].items() if v.get("last", "") >= cut}
    for q in ("pending_card", "pending_other", "outbox"):
        st[q] = [x for x in st[q] if x.get("time", "") >= cut]


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
            raise RuntimeError(f"{method} {path} → HTTP {e.code} {e.read().decode(errors='replace')[:300]}")

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
        return self.send(f"留言私訊 → {comment_id}", "POST", f"{self.messages_node()}/messages",
                         recipient={"comment_id": comment_id}, message={"text": FIRST_DM})

    def dm(self, igsid, text):
        return self.send(f"私訊 → {igsid}：{text[:20]}…", "POST", f"{self.messages_node()}/messages",
                         recipient={"id": igsid}, message={"text": text})


# ---------------------------------------------------------------- 主流程
def recent(ts_iso, now, hours=24):
    return ts_iso and (now - dt.datetime.fromisoformat(ts_iso)) < dt.timedelta(hours=hours)


def handle_comments(api, st, now):
    media = api.call("GET", f"{api.uid}/media", fields="id,timestamp", limit=10).get("data", [])
    for m in media:
        if dt.datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z") < LAUNCH:
            continue
        cs = api.call("GET", f"{m['id']}/comments", fields="id,text,username,timestamp,from", limit=50).get("data", [])
        for c in cs:
            if c["id"] in st["comments"] or c.get("username") == ME or not KEYWORD_COMMENT.search(c.get("text", "")):
                continue
            who = (c.get("from") or {}).get("id") or c.get("username", "")
            person = st["people"].setdefault(who, {})
            used = st["public_used"].setdefault(m["id"], {})
            pick = min(PUBLIC, key=lambda p: used.get(p, 0))
            if used.get(pick, 0) < 3:
                if api.send(f"公開回覆 {c['id']}：{pick}", "POST", f"{c['id']}/replies", message=pick) is None:
                    return
                used[pick] = used.get(pick, 0) + 1
            if recent(person.get("first_dm"), now):
                print(f"略過私訊：{c.get('username')} 24 小時內已收過第一則")
            else:
                if api.private_reply(c["id"]) is None:
                    return
                person.update(first_dm=now.isoformat(), username=c.get("username", ""), via="留言")
            person["last"] = now.isoformat()
            st["comments"][c["id"]] = now.isoformat()


def handle_dms(api, st, now):
    node = api.messages_node()
    convs = api.call("GET", f"{node}/conversations", platform="instagram",
                     fields="id,updated_time,messages.limit(5){id,message,from,created_time}", limit=20).get("data", [])
    for cv in convs:
        for msg in reversed((cv.get("messages") or {}).get("data", [])):
            mid, frm = msg["id"], msg.get("from") or {}
            if mid in st["seen_msgs"]:
                continue
            st["seen_msgs"][mid] = now.isoformat()
            if frm.get("username") == ME or frm.get("id") == api.uid:
                continue
            who, text = frm.get("id", ""), msg.get("message", "")
            person = st["people"].setdefault(who, {})
            person["last"] = now.isoformat()
            safe, masked = mask(text)
            item = {"time": msg.get("created_time") or now.isoformat(), "igsid": who, "username": frm.get("username", ""),
                    "text": safe, "masked": masked, "conversation": cv.get("id")}
            if KEYWORD_DM.search(text) and len(text) <= 12:
                if recent(person.get("first_dm"), now):
                    print(f"略過：{frm.get('username')} 24 小時內已收過第一則")
                    continue
                if api.dm(who, FIRST_DM) is None:
                    return
                person.update(first_dm=now.isoformat(), username=frm.get("username", ""), via="私訊")
            elif person.get("first_dm"):
                st["pending_card"].append(item)
            else:
                st["pending_other"].append(item)


def send_outbox(api, st, now):
    for o in st["outbox"]:
        if o.get("sent") or not o.get("approved"):
            continue
        last = o.get("their_last") or o.get("time")
        if last and not recent(last, now, 24):
            o["sent"] = "過期（超過 24 小時，不能回）"
            continue
        if api.dm(o["igsid"], o["text"]) is None:
            return
        o["sent"] = now.isoformat()


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
        sys.exit("⛔ 已連續 3 次 API 錯誤，暫停中。修好後把狀態的 errors 歸零（python3 dm_bot.py --reset-errors）")
    now = dt.datetime.now(TZ)
    api = Api(token, a.dry_run)
    ok = True
    for step in (handle_comments, handle_dms, send_outbox):
        try:
            step(api, st, now)
        except RuntimeError as e:
            ok = False
            print(f"❌ {step.__name__}：{e}")
    st["errors"] = 0 if ok else st.get("errors", 0) + 1
    late = [p for p in st["pending_card"] if not p.get("drafted") and not recent(p["time"], now, 20)]
    if late:
        print(f"⚠️ 有 {len(late)} 則選卡回覆收到超過 20 小時還沒回（24 小時後就不能回）")
    purge(st, now)
    if not a.dry_run:
        save_state(st)
    print(f"完成：送出 {api.sent} 則，待回覆 {sum(1 for p in st['pending_card'] if not p.get('drafted'))} 則，"
          f"其他私訊 {len(st['pending_other'])} 則，連續錯誤 {st['errors']} 次")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
