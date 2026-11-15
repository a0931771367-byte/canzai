# Threads 自動化（社群部「零人工曝光方案」第 2～4 項）

| 功能 | 什麼時候跑 | 說明 |
|---|---|---|
| IG 同步 | publish.yml 發完 IG 之後 | 同一篇發到 Threads：Reel → 影片、輪播 → 輪播。文字用 `貼文.md` 的「## Threads 版」，沒有就用 IG 文案去掉 hashtag（第一個 hashtag 變主題標籤），上限 450 字 |
| 純文字短文 | threads.yml 每 30 分鐘 | 內容部把短文放在 `內容部/Threads/MMDD_HHMM_標題.md`（檔名就是台灣發文時間）。最後一行可以放一個 `#主題`；開頭可用 `---` 包住備註，不會發出去。超過 2 小時沒發就略過，一輪只發一則 |
| 自家回覆 | threads.yml 每 30 分鐘 | 抓罐仔最近 15 篇底下 48 小時內的新回覆，用 `comments/classify.py` 分類：A 稱讚、F 分享經驗自動回（不提私訊的安全範本，一輪最多 20 則）；S 垃圾自動隱藏；其他類別只計數，由每日 Claude 處理。回過的不重複回（看底下有沒有罐仔的回覆，不另外存狀態） |
| 關鍵字搜尋 | 手動或社群部排程 | `threads.py search 信用卡回饋 雙12 -o out.json`；只存內文、連結、時間，不存帳號。App 審查通過前只搜得到自己的貼文 |

不做：回覆或追蹤陌生人的貼文、按讚。

secret：`THREADS_TOKEN`（授權步驟見 `Threads授權步驟.md`），續期在 `refresh_token.yml`。紀錄存在 `threads_ledger.json`（只有檔名、時間、貼文 ID）。
