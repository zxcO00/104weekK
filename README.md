# 觀察池週線「邊界重塑（Boundary Reset）」自動監控系統

自動化量化監控工具，每週五台股收盤後透過 GitHub Actions 排程，掃描觀察池（台股0050核心權值＋
中型100精選＋美股大型科技）週線圖，偵測「邊界重塑（Boundary Reset / Liquidity Sweep & Reset）」
價格行為型態，在最新一根週K棒回踩「滿足區」時，計算下單四要素、繪製決策圖表，並推播到
Telegram / Discord。

## 型態定義（動態邊界版）

1. **動態邊界（Boundary）**：以近期低點做線性回歸，抓出微正斜率（持平~小幅上揚）的通道邊界，而非固定水平線。
2. **極深刺穿洗盤（Sweep）**：價格向下刺穿當時邊界（1.5%~22%），創出極限低點 `sweep_low`。
3. **強勢收復（Peak 2）**：拉回站上刺穿當時的邊界水位，創出第二波峰 `peak2`。
4. **滿足區（Satisfaction Zone）**：以「當前」動態邊界為中心，向上 3.5% / 向下 1.5% 的區間。
5. **最新K棒回踩進場（Entry Signal）**：當前週K棒的低點落在滿足區內、收盤守穩區間下緣。

輸出四橫線：目標停利（等距投射 `entry + (peak2 - sweep_low)`）／進場訊號／動態邊界／防守停損（`sweep_low * 0.992`）。

## 觀察池範圍

- 美股大型科技（12 檔）：AAPL、MSFT、NVDA、GOOGL、AMZN、META、TSLA、AVGO、AMD、QCOM、TSM、ASML
- 台灣 0050 核心權值（44 檔）
- 台灣中型 100 精選（約 50 檔，含上市與上櫃 `.TWO`）

完整清單見 `src/data_fetcher.py` 的 `WATCHLIST_MAPPING`。

## 專案結構

```
├── .github/workflows/weekly_scan.yml   # 每週五 15:30 台灣時間排程，可手動 workflow_dispatch 測試
├── requirements.txt                    # Python 套件（已釘版本）
└── src/
    ├── scanner.py           # 主流程：下載 -> 偵測 -> 部位試算 -> 繪圖 -> 推播 -> 產出報告
    ├── data_fetcher.py       # yfinance 批次下載、清洗、分批重試（含 WATCHLIST_MAPPING）
    ├── pattern_detector.py   # detect_boundary_shift()：動態斜率邊界 + 滿足區回踩 + 緊縮箱型進場/停損精算
    ├── historical_satisfaction.py  # 「翻亞當」歷史滿足紀錄前置濾網（信任分數，非即時訊號）
    ├── visualizer.py         # plot_and_save()：中文字型註冊 + 滿足區框 + 四橫線圖
    ├── position_sizing.py    # calc_position_size()：依台股/美股自動切換幣別與成本模型
    └── notifier.py           # Telegram / Discord webhook 推播 + 失敗告警
```

## 環境變數 / GitHub Secrets

| 變數 | 說明 | 必要性 |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 選填，缺少則跳過該推播 |
| `TELEGRAM_CHAT_ID` | 接收訊息的 chat id | 選填 |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL | 選填 |
| `POSITION_RISK_AMOUNT_TWD` | 單筆固定風險金額（新台幣，美股會依匯率換算） | 選填，預設 10000 |
| `USD_TWD_RATE` | 美元兌台幣參考匯率 | 選填，預設 32.0 |
| `MIN_HISTORICAL_SATISFACTIONS` | 歷史翻亞當滿足次數門檻（低於此門檻的訊號會被過濾掉） | 選填，預設 0（不過濾，只附加統計資訊） |

## Streamlit 網頁版（app.py）

提供兩個功能頁籤，讓你不用等每週排程就能手動辨識：
- **全市場掃描**：對整個觀察池跑一次掃描，列出符合條件的標的、可切換查看個別決策圖表
- **單一標的診斷**：輸入任意代碼（含非觀察池內的標的）立即檢查是否符合回踩條件

### 本機執行網頁版
```bash
pip install -r requirements.txt
streamlit run app.py
```

### 部署到 Streamlit Community Cloud（streamlit.io）
1. 把整個 repo push 到 GitHub（public repo，或 private + Streamlit 帳號已連結該權限）
2. 到 [share.streamlit.io](https://share.streamlit.io) → New app
3. 選擇這個 repo，**Main file path 填 `app.py`**（在 repo 根目錄，不是 `src/app.py`）
4. **點開「Advanced settings」，Python version 選 3.12**（見下方已知坑）
5. Deploy 後每次 push 到主分支會自動重新部署

網頁版跟 GitHub Actions 排程版共用同一套 `src/` 邏輯模組，改一次 `pattern_detector.py` 兩邊都會同步更新，不用維護兩份程式碼。網頁版的風險金額/匯率可以直接在側邊欄調整，不需要改環境變數。

#### ⚠️ 已知坑：Python 版本與套件編譯失敗

Streamlit Cloud 目前預設 Python 3.12，但新建 App 有時會被導向最新的 3.14——這個版本太新，pandas/pillow 等套件還沒有預編譯 wheel，會嘗試從原始碼編譯並因缺少系統函式庫（如 zlib）而失敗。

- `runtime.txt` **目前無法可靠指定 Python 版本**（Streamlit 官方已知問題，常被忽略）
- 正確做法：部署時展開「Advanced settings」，用下拉選單明確選擇 Python 版本（建議 3.12）
- 部署後無法更改 Python 版本，只能刪除該 App 重新部署
- `requirements.txt` 用 `>=` 而非 `==` 釘死版本，讓套件管理器能挑到有現成 wheel 的新版本，降低編譯失敗機率

### 本機執行（排程版 scanner.py）

```bash
pip install -r requirements.txt
cd src
python scanner.py
```

首次執行會自動下載並快取「台北思源黑體」字型（`src/fonts/`）供圖表中文標籤使用；
下載失敗時會自動退回英文字型，不影響訊號判斷本身。

## 已知限制 / TODO

- 部位試算的手續費/證交稅為牌告費率粗估，美股成本模型（0.1%）也是概估值，未反映實際券商折扣。
- 型態偵測門檻（`min_sweep_pct`、`max_slope_pct_per_bar` 等）為人工設定，尚未做參數優化或回測績效統計。
- 觀察池清單寫死在 `data_fetcher.py` 的 `WATCHLIST_MAPPING`，成分股調整需手動更新。
- 美股與台股共用同一批推播/報告格式，尚未依交易時區分開排程（目前皆在台股收盤後一次掃描）。
