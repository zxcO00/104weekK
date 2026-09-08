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
    ├── pattern_detector.py   # detect_boundary_shift()：動態斜率邊界 + 滿足區回踩判定
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

## 本機執行

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
