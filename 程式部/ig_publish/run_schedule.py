#!/usr/bin/env python3
"""每日自動發文排程：依 內容部/規格/第1-2週.json 的 date 欄，到時間就呼叫 ig_publish.py post 發出去。

每 10 分鐘跑一次（GitHub Actions 或罐子 Mac 的 launchd 都可以）。每次只做一件事：
  找出「已經到發文時間、還沒發、沒超過 2 小時」的那一篇 → 發。超過 2 小時沒發出去的不補發，寫進 待處理.md 等人決定。

    python3 run_schedule.py                 # 正式跑（brands.json schedule_enabled=true 才會發）
    python3 run_schedule.py --plan          # 只列出排程表和每篇狀態
    python3 run_schedule.py --dry-run       # 模擬：該發哪篇、走一次三道關卡，但不呼叫發文
    python3 run_schedule.py --mark 00 [--media-id X]   # 手動發過的（例如 00 自介）記成已發，排程就不會重發
    python3 run_schedule.py --now "2026-11-05 20:03"   # 模擬時間（測試用）
    python3 run_schedule.py --late 02       # 補發已錯過的 02（只在罐子同意後手動觸發）

環境變數：
  CANZAI_CONTENT    內容部資料夾（預設 /mnt/project-files/內容部）。會讀 規格/*.json 每一週，
                    每週的貼文資料夾在 內容部/<規格檔名>/（例如 規格/第3週.json → 第3週/）
  CANZAI_MEDIA_BASE 公開媒體網址的開頭，後面接資料夾名稱（例如 https://a0931771367-byte.github.io/canzai/media）
                    IG API 只收公開網址，所以圖檔和影片要先放到這裡（GitHub Pages）
  IG_TOKEN、IG_USER_ID  和 ig_publish.py 相同

解鎖條件（brands.json 的 schedule_enabled）：① Meta 授權完成且 verify_auth.py 全綠 ② 罐子核准封面一覽。
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # /mnt/project-files
TZ = dt.timezone(dt.timedelta(hours=8))
CONTENT = os.environ.get("CANZAI_CONTENT", os.path.join(ROOT, "內容部"))
LEDGER = os.path.join(HERE, "publish_ledger.json")
TODO = os.path.join(HERE, "待處理.md")
GRACE = dt.timedelta(hours=2)
YEAR = 2026


def slot(label):
    """「11/5（四）晚上 8 點」→ 2026-11-05 20:00。⏸ 開頭或認不得的回傳 None（不排）。"""
    if not label or label.startswith("⏸"):
        return None
    m = re.match(r"(\d{1,2})/(\d{1,2})", label)
    if not m:
        return None
    h = 12 if "中午 12" in label else 20 if "晚上 8" in label else None
    hm = re.search(r"(\d{1,2}):(\d{2})", label)
    if hm:
        h, mi = int(hm.group(1)), int(hm.group(2))
    else:
        mi = 0
    if h is None:
        return None
    return dt.datetime(YEAR, int(m.group(1)), int(m.group(2)), h, mi, tzinfo=TZ)


def folder_of(pid, week):
    d = os.path.join(CONTENT, week)
    if not os.path.isdir(d):
        return None
    for name in sorted(os.listdir(d)):
        if name.split("_")[0] == pid and os.path.isdir(os.path.join(d, name)):
            return os.path.join(d, name)
    return None


def load_ledger():
    return json.load(open(LEDGER, encoding="utf-8")) if os.path.exists(LEDGER) else {}


def save_ledger(led):
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def plan():
    import glob
    rows = []
    for spec in sorted(glob.glob(os.path.join(CONTENT, "規格", "*.json"))):
        week = os.path.splitext(os.path.basename(spec))[0]
        for p in json.load(open(spec, encoding="utf-8")).get("posts", []):
            rows.append((slot(p.get("date")), p["id"], p.get("title") or p.get("slug", ""), p.get("date", ""), week))
    return sorted([r for r in rows if r[0]], key=lambda r: r[0]), [r for r in rows if not r[0]]


def todo(msg):
    with open(TODO, "a", encoding="utf-8") as f:
        f.write(f"- [ ] {dt.datetime.now(TZ):%m/%d %H:%M} {msg}\n")
    print("📝 " + msg)


def url_live(url, tries=20):
    import time
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=15) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(15)
    return False


def main():
    ap = argparse.ArgumentParser(description="每日自動發文排程")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mark")
    ap.add_argument("--media-id", default="")
    ap.add_argument("--now")
    ap.add_argument("--late", default="", help="補發一篇已錯過 2 小時的貼文（罐子同意後手動觸發用），例如 --late 02")
    a = ap.parse_args()
    now = dt.datetime.strptime(a.now, "%Y-%m-%d %H:%M").replace(tzinfo=TZ) if a.now else dt.datetime.now(TZ)
    led = load_ledger()

    if a.mark:
        led[a.mark] = {"published_at": now.isoformat(timespec="minutes"), "media_id": a.media_id, "how": "手動"}
        save_ledger(led)
        print(f"已記錄 {a.mark} 為已發")
        return

    sched, held = plan()
    if a.plan:
        for t, pid, title, _, week in sched:
            st = "✅ 已發" if pid in led else ("⏰ 該發了" if t <= now < t + GRACE else
                                              "⚠️ 錯過" if now >= t + GRACE else "…")
            print(f"{t:%m/%d %H:%M}  {pid:4} {st:6} {title}")
        for _, pid, title, label, _w in held:
            print(f"（暫緩） {pid:4} {title}｜{label}")
        return

    cfg = json.load(open(os.path.join(HERE, "brands.json"), encoding="utf-8"))["canzai"]
    if not cfg.get("schedule_enabled") and not a.dry_run:
        print("⏸ 排程還沒解鎖：" + cfg.get("schedule_enabled_note", ""))
        return

    for t, pid, title, _, week in sched:
        if pid in led:
            continue
        if now >= t + GRACE and pid != a.late:
            if a.dry_run:
                print(f"（模擬）{pid} 已錯過 2 小時，正式跑時會寫進 待處理.md")
            elif not led.get(f"_missed_{pid}"):
                todo(f"{pid}「{title}」原定 {t:%m/%d %H:%M} 沒發出去，已超過 2 小時，排程不補發。要補發請手動跑：python3 ig_publish.py post <資料夾>")
                led[f"_missed_{pid}"] = True
                save_ledger(led)
            continue
        if now < t:
            if a.late and a.late not in led:
                continue  # 補發模式：繼續找指定的那篇
            break  # 依時間排序，後面的都還沒到
        if a.late and pid != a.late:
            continue
        folder = folder_of(pid, week)
        if not folder:
            todo(f"{pid}「{title}」找不到貼文資料夾（{CONTENT}/{week}/{pid}_*）")
            continue
        base = os.environ.get("CANZAI_MEDIA_BASE", "").rstrip("/")
        if not base and not a.dry_run:
            todo("沒設定 CANZAI_MEDIA_BASE（公開媒體網址），沒辦法發")
            return
        base_url = f"{base}/{urllib.parse.quote(week)}/{urllib.parse.quote(os.path.basename(folder))}" if base else "https://example.invalid"
        first = "reel.mp4" if os.path.exists(os.path.join(folder, "reel.mp4")) else "01.jpg"
        if base and not a.dry_run and not url_live(f"{base_url}/{first}"):
            todo(f"{pid} 的媒體還沒放上公開網址：{base_url}/{first}")
            return
        print(f"▶ {t:%m/%d %H:%M} 發 {pid}「{title}」")
        cmd = [sys.executable, os.path.join(HERE, "ig_publish.py"), "post", folder, "--base-url", base_url]
        if a.dry_run:
            cmd.append("--dry-run")
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(r.stdout[-3000:], r.stderr[-1500:])
        if a.dry_run:
            return
        if r.returncode == 0:
            mid = (re.findall(r"貼文 ID：\s*(\d+)", r.stdout) or [""])[-1]
            led[pid] = {"published_at": dt.datetime.now(TZ).isoformat(timespec="minutes"), "media_id": mid, "how": "排程"}
            save_ledger(led)
            if pid == "00":
                todo("00 自介已發，請到 IG App 手動置頂（API 不能置頂）")
        elif r.returncode == 4:  # IG 上已經有（手動或 Metricool 發過），記成已發，不再重試
            mid = (re.findall(r"貼文 ID：\s*(\d+)", r.stdout) or [""])[-1]
            led[pid] = {"published_at": dt.datetime.now(TZ).isoformat(timespec="minutes"), "media_id": mid,
                        "how": "已在 IG（手動或 Metricool）"}
            save_ledger(led)
            todo(f"{pid}「{title}」IG 上已經有了（可能是手動或 Metricool 發的），排程沒有重發")
        else:
            why = {2: "官網重查擋下（看資料夾裡的 查證報告.md）", 1: "合規或文案檢查沒過",
                   5: "品管部去 AI 感檢查沒過（看 品管部/去AI感檢查表.md）"}.get(r.returncode, "發文失敗")
            todo(f"{pid}「{title}」{why}，結束碼 {r.returncode}。修好後 2 小時內排程會自動重試")
        return  # 一次只發一篇


if __name__ == "__main__":
    main()
