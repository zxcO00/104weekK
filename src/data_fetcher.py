"""
data_fetcher.py
負責從 yfinance 批次下載觀察池（台股 0050 + 中型100精選 + 美股科技巨頭）週線資料，
並處理清洗 / 重試 / 限流問題。
"""

import time
import pandas as pd
import yfinance as yf


WATCHLIST_MAPPING = {
    # ---------------- 美股大型科技股 (US Mega-Cap Tech) ----------------
    "AAPL": "Apple (AAPL)", "MSFT": "Microsoft (MSFT)", "NVDA": "NVIDIA (NVDA)",
    "GOOGL": "Alphabet (GOOGL)", "AMZN": "Amazon (AMZN)", "META": "Meta (META)",
    "TSLA": "Tesla (TSLA)", "AVGO": "Broadcom (AVGO)", "AMD": "AMD (AMD)",
    "QCOM": "Qualcomm (QCOM)", "TSM": "TSMC ADR (TSM)", "ASML": "ASML (ASML)",

    # ---------------- 台灣 0050 核心權值 (TW50 Core) ----------------
    "2330.TW": "台積電 (2330)", "2454.TW": "聯發科 (2454)", "2317.TW": "鴻海 (2317)",
    "2308.TW": "台達電 (2308)", "2382.TW": "廣達 (2382)", "2881.TW": "富邦金 (2881)",
    "2882.TW": "國泰金 (2882)", "2891.TW": "中信金 (2891)", "3711.TW": "日月光投控 (3711)",
    "2412.TW": "中華電 (2412)", "2886.TW": "兆豐金 (2886)", "2603.TW": "長榮 (2603)",
    "3231.TW": "緯創 (3231)", "2357.TW": "華碩 (2357)", "6669.TW": "緯穎 (6669)",
    "2884.TW": "玉山金 (2884)", "2892.TW": "第一金 (2892)", "2885.TW": "元大金 (2885)",
    "5880.TW": "合庫金 (5880)", "2890.TW": "永豐金 (2890)", "2880.TW": "華南金 (2880)",
    "3008.TW": "大立光 (3008)", "3034.TW": "聯詠 (3034)", "2379.TW": "瑞昱 (2379)",
    "2303.TW": "聯電 (2303)", "2395.TW": "研華 (2395)", "3017.TW": "奇鋐 (3017)",
    "2383.TW": "台光電 (2383)", "2059.TW": "川湖 (2059)", "3661.TW": "世芯-KY (3661)",
    "3443.TW": "創意 (3443)", "3653.TW": "健策 (3653)", "2345.TW": "智邦 (2345)",
    "2327.TW": "國巨 (2327)", "2301.TW": "光寶科 (2301)", "2356.TW": "英業達 (2356)",
    "2609.TW": "陽明 (2609)", "2615.TW": "萬海 (2615)", "1216.TW": "統一 (1216)",
    "1101.TW": "台泥 (1101)", "1301.TW": "台塑 (1301)", "1303.TW": "南亞 (1303)",
    "2002.TW": "中鋼 (2002)", "2883.TW": "開發金 (2883)",

    # ---------------- 台灣中型 100 精選 (TW Mid-Cap 100 Selected) ----------------
    "2376.TW": "技嘉 (2376)", "2377.TW": "微星 (2377)", "3044.TW": "健鼎 (3044)",
    "2360.TW": "致茂 (2360)", "3583.TW": "辛耘 (3583)", "3131.TWO": "弘塑 (3131)",
    "3324.TWO": "雙鴻 (3324)", "6274.TWO": "台燿 (6274)", "8299.TWO": "群聯 (8299)",
    "3529.TWO": "力旺 (3529)", "5269.TW": "祥碩 (5269)", "6415.TW": "矽力*-KY (6415)",
    "2458.TW": "義隆 (2458)", "6488.TWO": "環球晶 (6488)", "5347.TWO": "世界 (5347)",
    "6770.TW": "力積電 (6770)", "2409.TW": "友達 (2409)", "3481.TW": "群創 (3481)",
    "2313.TW": "華通 (2313)", "3037.TW": "欣興 (3037)", "8069.TWO": "元太 (8069)",
    "1476.TW": "儒鴻 (1476)", "9910.TW": "豐泰 (9910)", "8046.TW": "南電 (8046)",
    "2408.TW": "南亞科 (2408)", "2344.TW": "華邦電 (2344)", "6531.TW": "愛普* (6531)",
    "3706.TW": "神達 (3706)", "2353.TW": "宏碁 (2353)", "2324.TW": "仁寶 (2324)",
    "2449.TW": "京元電子 (2449)", "6239.TW": "力成 (6239)", "5483.TWO": "中美晶 (5483)",
    "6472.TW": "保瑞 (6472)", "4743.TWO": "合一 (4743)", "1795.TW": "美時 (1795)",
    "9958.TW": "世紀鋼 (9958)", "1519.TW": "華城 (1519)", "1503.TW": "士電 (1503)",
    "1513.TW": "中興電 (1513)", "1514.TW": "亞力 (1514)", "2618.TW": "長榮航 (2618)",
    "2610.TW": "華航 (2610)", "9904.TW": "寶成 (9904)", "2912.TW": "統一超 (2912)",
    "8454.TW": "富邦媒 (8454)", "2887.TW": "台新金 (2887)", "2889.TW": "國票金 (2889)",
}


def is_us_ticker(ticker):
    """判斷是否為美股（非 .TW / .TWO 結尾即視為美股）"""
    return not (ticker.endswith(".TW") or ticker.endswith(".TWO"))


def clean_yf_df(data):
    """拍平 yfinance 可能回傳的 MultiIndex 欄位"""
    df = data.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def download_with_retry(tickers, batch_size=15, max_retries=3, retry_wait=2.5, **yf_kwargs):
    """分批下載 + 失敗重試，降低 yfinance 被限流或單次請求逾時的機率"""
    all_data = {}

    print(f">> 開始分批下載標的週線數據（共 {len(tickers)} 檔）...")
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        for attempt in range(1, max_retries + 1):
            try:
                data = yf.download(batch, group_by="ticker", progress=False, **yf_kwargs)
                if isinstance(data.columns, pd.MultiIndex):
                    top_level = set(data.columns.get_level_values(0))
                    for t in batch:
                        if t in top_level:
                            all_data[t] = data[t]
                else:
                    if len(batch) == 1:
                        all_data[batch[0]] = data
                break
            except Exception as e:
                print(f"⚠️ 批次下載失敗（第 {attempt}/{max_retries} 次）batch={batch}: {e}")
                if attempt < max_retries:
                    time.sleep(retry_wait * attempt)
                else:
                    print(f"❌ 批次 {batch} 最終下載失敗，略過")

        time.sleep(1.0)

    return all_data


def prepare_dataframe(raw_df, min_rows=25):
    """
    清洗單一標的原始資料，回傳附帶 DateStr / Vol_MA 的標準化 DataFrame，
    不足 min_rows 筆回傳 None。

    min_rows 預設 25（週K型態偵測需要的最小樣本數）；日K精算打擊區時
    只需要一小段最近的資料，呼叫時可以把 min_rows 降低（例如設 1）。
    """
    df = clean_yf_df(raw_df).dropna().copy()
    if len(df) < min_rows:
        return None

    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    df["DateStr"] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["Vol_MA"] = df["Volume"].rolling(window=10).mean().bfill()
    return df


def fetch_all_watchlist(period="2y", interval="1wk", batch_size=15):
    """對外主要入口：下載 + 清洗全部觀察池標的，回傳 {ticker: (name, df)}"""
    tickers = list(WATCHLIST_MAPPING.keys())
    raw_data = download_with_retry(tickers, batch_size=batch_size, period=period, interval=interval, auto_adjust=True)

    result = {}
    for ticker, name in WATCHLIST_MAPPING.items():
        if ticker not in raw_data:
            continue
        df = prepare_dataframe(raw_data[ticker])
        if df is not None:
            result[ticker] = (name, df)

    print(f">> 數據準備完成，成功載入 {len(result)} / {len(tickers)} 檔標的。")
    return result
