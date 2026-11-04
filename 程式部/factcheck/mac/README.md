# 官網快照：Mac 抓、GitHub 放、雲端比對

**問題：** 雲端環境有網路白名單（蝦皮、國泰、Uber 都被擋），每多一家銀行就要罐子加一次。
**做法：** 罐子的 Mac 每天 06:30、11:30 用 launchd 抓官網，推到 GitHub repo `a0931771367-byte/canzai` 的 `snapshots` 分支。雲端的 `factcheck.py` 直接抓官網失敗時，就從 raw.githubusercontent.com 讀快照。這個網址雲端本來就連得到。
**結果：** 罐子**一次白名單都不用加**。新增銀行時，雲端用 `--urls-out` 更新 urls.txt 並推上去，Mac 下一輪就會抓。

## 罐子要做的（一次）
1. GitHub 建好 public repo `canzai`（跟試算器網站共用；快照放在另一個分支，網站上看不到）
2. 把 `mac/` 這個資料夾拿到 Mac，在終端機跑 `bash install_mac.sh`

## 流程
1. 內容部寫好貼文.md 的查證欄，接著跑 `python3 factcheck.py 內容部/第X週/* --urls-out urls.txt`，然後把 urls.txt 推到 snapshots 分支（程式部處理）
2. Mac 排程：`fetch_snapshots.py` 讀 urls.txt，抓每個網址，寫進 `pages/<雜湊>.txt` 和 `index.json`，然後 push
3. 發文當天 `factcheck.py` 先直接抓官網，抓不到就讀快照。快照超過 36 小時就擋下（`FACTCHECK_SNAPSHOT_MAX_HOURS` 可調）。報告上會註明「依 Mac 快照 11-03 06:30」

## 為什麼選 Mac，不選 GitHub Actions 或情報部掃描
- 情報部的掃描也跑在雲端，一樣被白名單擋住
- GitHub Actions 的機器在國外，台灣的銀行網站常擋國外 IP。Mac 是台灣 IP，最接近一般使用者看到的頁面
- Mac 睡眠時，launchd 會在醒來後補跑。如果整天沒開機，快照就會超過 36 小時，factcheck 會擋下不發，不會用舊資料放行

## 檢查
- Mac 紀錄：`~/Library/Logs/canzai-snapshots.log`
- 手動跑一次：`python3 ~/Library/Application\ Support/canzai/fetch_snapshots.py`
- 停用：`launchctl unload ~/Library/LaunchAgents/money.canzai.snapshots.plist`
