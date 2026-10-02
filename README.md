# 利率與存款監察

每天追蹤港元及美元利率，並在有變時透過 Telegram 通知。網頁使用現有 hub 登入：

https://hub.carelogic.org/app/r_monitor/rates/

## 每日監察

Windows 排程 `\r_monitor_daily` 每日香港時間 12:00 執行 `main.py`，是銀行資料的唯一寫入者。

- 滙豐 Wealth Portfolio Lending（滙財組合貸款）：1 個月香港銀行同業拆息 + 0.5 百分點。
- 恒生 Asset Link（抵押透支）：恒生自己公布的港元最優惠利率 − 1.75 百分點。
- 香港銀行同業拆息、各銀行最優惠利率、盈透證券港元及美元融資息率。
- IB（盈透證券）孖展借款：每日核對 IBKR Pro 專業帳戶方案的港元、美元全部級別；利率、借款級別或附加條款有變時發 Telegram。網頁顯示完整分級表及借款金額加權息率／30 日利息試算；涉及大額附加費或個別條款的金額會停止試算並說明原因。
- 美國聯邦基金有效利率及目標範圍、有抵押隔夜融資利率、美國國債收益率、議息機率。
- 金管局的港元遠期匯價點子（有月度公布延遲，並非利率）。
- DBS eSaver **現有客戶**推廣。官方網頁的嵌入資料含有息率級別、比較存款餘額日期、登記截止、計息期及獎賞存入日；不能拿新客戶優惠代替。

貸款息率按操作者提供的息差計算；不讀取銀行帳戶或估算實際借款餘額。個人貸款歷史由啟用日開始，不能套用今天的息差冒充歷史帳單。

## Telegram

- 貸款息率相對上次成功通知有變才發訊息；初次取得資料建立基準。
- IB 借款通知亦以最後確認送達的全部級別為基準；首次建立基準，沒有變動不重複發送。
- 新一期現有客戶 eSaver 出現時通知一次，送達未獲確認則保留待辦。
- 資料失敗或恢復通知附上修復結果；網頁同時顯示異常。
- **已停止所有 HTML 附件及每星期報告推送**。`--weekly` 只保留舊參數兼容。

## 家人登記紀錄

`esaver schedule.xlsx` 已唯讀匯入 14 期（2025-08 至 2026-09）及 7 筆登記。原檔沒有改寫。

網頁可選推廣期、家人、登記狀態及實際日期，也可加入家人或更正紀錄。這是個人紀錄；完成 DBS app 登記後再填寫。

Hub 把已驗證身分的寫入送到自己的附加式收件箱。`\r_monitor_web_sync` 每分鐘執行 `sync_web.py`，消費收件箱、保存紀錄並原子更新網頁資料；不會呼叫銀行。每日收集也會消費一次。已收件的變更即時顯示「同步中」，其他裝置約一分鐘可見。

安裝同步排程：以管理員 PowerShell 執行 `install_web_sync.ps1`。沿用每日排程的 Windows S4U 身分（登出後仍可運作），同一時間只允許一個執行個體。

## 失敗與修復

所有來源和 Telegram 都經 `src/http_client.py` 的共用送出函式：

- 401 / 403 / 429、其他拒絕或驗證挑戰：停止同帳戶呼叫，保留資料，最少冷卻一天並遵守伺服器時間加裕量；重複事件加倍。冷卻後下一次收集只做一個受保護的驗證。
- 網絡或 5xx：GET 最多額外一次指數退避與隨機延遲；POST 不自動重送，避免不確定的重複通知。
- 400 / 404 / 422：同一個請求不重試。
- 網頁亦有同一瀏覽器分頁共用的呼叫鎖和冷卻紀錄；登入過期／拒絕會停止自動更新，保留表格。網絡或 5xx 的讀取最多額外一次，保存紀錄不自動重送。
- 每個帳戶最少間隔一秒、每日 64 次及每次執行 32 次的本機安全上限。這些是保守本機限制，**不代表供應商公布的配額**。2026-10-02 檢查其他頂層 project 的 .env，這個 Telegram token 和 FRED key 均只有本 project 使用；雲端排程已停用。
- 未知解析錯誤及重複拒絕會啟動隔離的本機 Codex 命令列修復，沿用中央模型設定，停用 connectors、shell 網絡及 git push。原有測試決定修補是否可採用；保留原檔、JSON Lines 執行事件、退出狀態及設定模型，實際服務模型沒有可信 metadata 時標示 unavailable。
- CSV 或狀態損壞不當成空白；保留損壞原檔並驗證上一份備份後復原，網頁顯示修復結果。沒有有效備份則停止寫入。拒絕呼叫的冷卻紀錄不回退備份，避免縮短冷卻。無效登記事件隔離並在網頁顯示。

## 本機操作

```
python -m pip install -r requirements.txt
python main.py                  # 收集、保存、發布、按變動通知
python main.py --no-notify      # 收集及發布，不發 Telegram
python main.py --build-only     # 只重建網頁及消費收件箱，沒有網絡呼叫
python sync_web.py              # 只同步家人紀錄
python -m pytest tests -q --basetemp logs/pytest-r-monitor
node --test tests/test_web_guard.cjs tests/test_margin.cjs
```

`.env` 需要 `FRED_API_KEY`、`TELEGRAM_BOT_TOKEN` 及 `TELEGRAM_CHAT_ID`。

## 資料與發布

- `data/*.csv`：原有公開市場數據，每日排程提交，再由機器每小時 git 同步推送。
- `data/loan_rates.csv`、`rates_latest.json`、`esaver_promotions.json`、`esaver_registrations.json`：本機個人資料，gitignored，由既有機器備份保護。
- `web/`：受版本控制的 HTML / JavaScript / CSS 原始碼。
- `reports/app/`：生成後的網頁與展示資料；hub manifest 指向此資料夾，僅 owner 可見。只改 manifest 毋須重啟 hub。
- `src/report.py` 和 `src/templates/report.html`：保留舊報告程式作參考，每日流程已不再呼叫。

GitHub Actions 已停用，並移除 cron；`workflow_dispatch` 僅供機器退役後人工移交。重新啟用前必須停止本機每日排程。
