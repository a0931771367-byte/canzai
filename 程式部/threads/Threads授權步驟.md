# Threads 一次性授權（約 10 分鐘，做一次就好）

做完之後：IG 每篇會自動同步一份到 Threads、內容部的短文會照時間自動發、自家貼文底下的回覆會自動分類和回覆。全部免費。

1. **開 Threads 帳號**：手機打開 Threads App，用罐仔的 IG（@canzai_money）登入。已經有就跳過。
2. **建 App**：打開 https://developers.facebook.com/apps →「建立應用程式」→ 名稱填「罐仔 Threads」→ 使用案例選 **「存取 Threads API」** → 一路下一步到建立完成。
3. **勾權限**：App 左邊「使用案例」→ Threads API 的「自訂」→「權限」，把這 5 個都按「新增」：
   `threads_basic`、`threads_content_publish`、`threads_read_replies`、`threads_manage_replies`、`threads_keyword_search`
4. **加自己當測試者**：左邊「應用程式角色」→「角色」→「新增人員」→ 選 **Threads 測試人員** → 輸入 `canzai_money`。
   接著在手機 Threads App →「設定」→「帳號」→「網站權限」→「邀請」→ 按接受。
5. **產生 token**：回到「使用案例」→ Threads API 的「自訂」→「設定」，捲到「用戶權杖產生器」→ 罐仔旁邊按「產生權杖」→ 登入同意 → 複製那一長串。
6. **貼到 GitHub**：打開 https://github.com/a0931771367-byte/canzai/settings/secrets/actions/new
   名稱填 `THREADS_TOKEN`，內容貼第 5 步那串 →「Add secret」。

完成後跟 Claude 說一聲，我會先跑一次帳號核對（確認 token 是 @canzai_money），之後就全自動。
token 每週一自動續期（和 IG token 同一個排程），不用再動手。

## 已知限制
- 關鍵字搜尋：官方規定 `threads_keyword_search` 沒通過 Meta 的 App 審查前，只會搜到罐仔自己的貼文。要搜全站的公開貼文得送審（免費，但要錄一段操作影片、等幾天）；社群部決定要不要送，程式不用改。
- App 不用「上線」：只發自己的帳號，測試者身分就夠了。
