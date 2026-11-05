"""IG API 端點選擇（兩種 token 共用）。

- IG 開頭（Instagram Login）：graph.instagram.com，可以用 /me
- EAA 開頭（新版 Meta 後台「API setup with Unified login」）：graph.facebook.com，/me 不能用，
  要直接用 IG 用戶編號（罐仔 @canzai_money = 17841467330075264，環境變數 IG_USER_ID 可覆寫）
發文、留言、隱藏、回覆、發文額度的路徑兩邊一樣，只差網域和 uid。
"""
import datetime as dt
import json
import os
import urllib.parse
import urllib.request

IG_API = "https://graph.instagram.com/v23.0"
FB_API = "https://graph.facebook.com/v23.0"
CANZAI_IG_ID = "17841467330075264"


def is_fb(token):
    return (token or "").startswith("EAA")


def base(token):
    return FB_API if is_fb(token) else IG_API


def uid(token):
    """IG 用戶編號：有 IG_USER_ID 就用；EAA token 用罐仔的編號；IG token 用 me。"""
    return os.environ.get("IG_USER_ID") or (CANZAI_IG_ID if is_fb(token) else "me")


def username_fields(token):
    return "id,username" if is_fb(token) else "user_id,username"


def token_days_left(token):
    """token 還剩幾天。EAA 用 debug_token 查；永不過期回傳 inf；查不到回傳 None。
    IG 開頭的 token 沒有查詢端點，回傳 None（靠每週續期 workflow 維持 60 天）。"""
    if not is_fb(token):
        return None
    try:
        q = urllib.parse.urlencode({"input_token": token, "access_token": token})
        with urllib.request.urlopen(f"{FB_API}/debug_token?{q}", timeout=20) as r:
            d = json.load(r).get("data", {})
        exp = d.get("expires_at")
        if exp == 0:
            return float("inf")
        if not exp:
            return None
        return (dt.datetime.fromtimestamp(exp, dt.timezone.utc) - dt.datetime.now(dt.timezone.utc)).total_seconds() / 86400
    except Exception:  # noqa: BLE001
        return None
