# 留言分類與回覆草稿（社群部流程 3）

依 [社群部/留言與私訊自動化流程.md](../../社群部/留言與私訊自動化流程.md) 第五節與 [口吻指南](../../社群部/罐仔回覆口吻指南與範本.md) 製作。

## 每天的流程（全部免費）

```
每天 21:00（台灣）Claude 排程自動執行
① ig_comments.py fetch     抓過去 24 小時新留言（IG 官方 API）
② classify.py              規則版先分類、套範本起草（離線、不花錢）
③ Claude 看一遍            修正分類、依口吻指南潤飾草稿、標出要罐子處理的
④ 寫進 Google 試算表「留言回覆待審」（用已連結的 Google 試算表連接器）
⑤ 罐子在 OK 欄打勾（前 2 週）
⑥ 隔天排程讀回試算表 → ig_comments.py send 送出打勾的回覆、隱藏垃圾留言
⑦ 每週日統計各類數量與常見問題 → 給內容部當題目
⑧ 每天順便清除超過 90 天的留言紀錄（purge.py 清本機檔案；試算表由 Claude 刪除超過 90 天的列）── 法務部個資最小保存要求
```

為什麼不全部塞進 GitHub Actions：分類與潤飾要用 Claude，若在 GitHub 上呼叫 Claude API 要付費；改由專案裡的 Claude 排程執行，費用 0。

## 分類

| 細類 | 大類 | 處理 |
|---|---|---|
| A 稱讚感謝、F 分享經驗、C 問國家、E 要模板 | 讚美／問題／潛在客戶 | 前 2 週勾 OK 才送，第 3 週起自動送 |
| B 問特定卡、G 負評酸言 | 問題／負評 | 一律草稿待審（金融資訊、避免吵架） |
| D 指正錯誤 | 問題 | ⚠️ 先查證再回，同步更新貼文 |
| X 退款、付款、合作、檢舉、媒體 | 潛在客戶 | 🔔 轉給罐子 |
| H 只標註朋友 | 讚美 | 不回（官方 API 不能替留言按讚） |
| S 垃圾廣告、含髒話人身攻擊的 G | 負評 | 自動隱藏（不刪除） |

另外依 **/ig-reply** 加上「優先分桶」欄（KEYWORD → LEAD → SUBSTANCE → QUESTION → SUPPORT → NOISE，照這個順序回）；同一題有 3 人以上問會標「建議用 /ig-reel 做成回覆 Reel」。所有草稿都會自動過 **/ig-human** 去 AI 痕跡。每日排程的步驟 ③ 由 Claude 依 /ig-reply 的寫法潤飾，但遵守社群部口吻指南的紅線（不給個人化金融建議）。

範本輪流使用，同一篇貼文同一範本超過 3 次會在備註提醒換說法。

## 指令

```bash
python3 classify.py --demo                      # 用 25 則範例留言測試 → output/留言回覆待審.csv
python3 classify.py comments.json -o out/
IG_TOKEN=... python3 ig_comments.py fetch --hours 24 -o comments.json
python3 purge.py output/ --days 90             # 清除 90 天以上的留言紀錄
IG_TOKEN=... python3 ig_comments.py send out/留言回覆待審.json [--dry-run]
```

## 目前狀態

- 規則版分類：範例 25 則全部分對（見 `output/留言回覆待審.csv`）。
- 抓留言、送回覆、隱藏：程式完成，已 dry-run；**等罐子完成 Meta App 一次性授權**（和 IG 自動發文共用同一個 App，多勾 `instagram_business_manage_comments` 權限）才能接真實帳號。
- 授權完成後：程式部建立 Google 試算表與每日排程，即可上線。

## 上線日界線（2026-11-03 社群部要求）
只抓 2026-11-04 01:00（00 自介實際發文時間）之後發的貼文的留言。舊帳號（@air_pudding 時期）的貼文就算沒封存，留言也不會抓、不會自動回覆；送出時也會再擋一次。要調整界線就設環境變數 `CANZAI_LAUNCH`。

## 選卡自動回覆（dm_bot.py，法務部 11/5 審查後版本）

- GitHub Actions「選卡自動回覆」排程跑 `dm_bot.py`：留言「選卡」→ 公開回覆＋私訊第一則；私訊「選卡／配卡」→ 第一則；其他私訊 → 寫進試算表；試算表勾「核准」的回覆 → 送出。
- 帳號名稱、訊息只在罐子的 Google 試算表「罐仔私訊」（分頁：選卡待回覆、私訊待處理），試算表每天 03:00 自動刪 90 天前的列。
- 去重狀態只有 HMAC-SHA256（鹽值由 CANZAI_BOT_KEY 衍生）後的編號和時間，放 Actions cache，不進 git。
- 試算表那端是 `試算表_AppsScript.gs`（Apps Script 網頁應用程式），用 CANZAI_BOT_KEY 驗證呼叫者。
- 需要的 repo secrets：IG_TOKEN、CANZAI_BOT_KEY（setup 產生）、CANZAI_SHEET_URL（部署網址）。
- 雲端 Claude 起草回覆：用 Google 試算表工具讀「選卡待回覆」，把草稿填進「罐仔回覆草稿」欄，罐子勾「核准」才會送。
