"""
daily_refinement.py
雙時間週期精算 —— 週K負責找大格局邊界與方向（詳見 pattern_detector.py 的五階段
狀態機），這個模組負責用「日K」資料重新精算打擊區局部低點與停損。

為什麼要這樣做：週K的一根K棒壓縮了5個交易日，低點解析度比日K粗很多。
週K算出來的「打擊區局部低點」可能漏掉盤中/日內更精確的低點。改用日K在
同一段回踩期間（週K反彈高點 peak2 之後到現在）重新找低點，跟合作夥伴
「用前波高低點互換位精算打擊區/停損」的實務作法一致。

設計原則（延續整個專案一貫的容錯精神）：
- 進場價（entry_price）維持用週K的動態邊界計算，不用日K重算——這部分
  已經跟合作夥伴的手繪案例驗證過準確度，沒有理由改。
- 停利（tp_adam）維持用週K的翻亞當高度計算，同樣是已驗證過的部分。
- 只有停損（stop_loss）改用日K精算，因為這是週K解析度最不足的地方。
- 抓不到日K資料、或日K資料筆數不足時，安靜地退回週K版本的原始數值，
  不會讓整個訊號消失或報錯——多一個 "daily_refined" 欄位標示這次
  有沒有成功套用日K精算。
"""

import pandas as pd

from data_fetcher import download_with_retry, prepare_dataframe


def find_daily_strike_zone(daily_df, start_date):
    """
    在日K資料中，從 start_date（含）到最新一根日K，找出這段期間的實際
    最低/最高價 —— 這是比週K解析度更細的「打擊區局部低點」。
    """
    mask = pd.to_datetime(daily_df["DateStr"]) >= pd.to_datetime(start_date)
    zone_slice = daily_df[mask]
    if len(zone_slice) == 0:
        return None

    return {
        "zone_low": float(zone_slice["Low"].min()),
        "zone_high": float(zone_slice["High"].max()),
        "zone_start_date": str(zone_slice.iloc[0]["DateStr"]),
        "zone_end_date": str(zone_slice.iloc[-1]["DateStr"]),
        "bar_count": len(zone_slice),
    }


def refine_with_daily(ticker, weekly_df, res, local_low_buffer=0.01, min_risk_pct=0.02):
    """
    用日K資料重新精算 res（週K版 STATUS_TRIGGERED 的結果 dict）裡的停損。

    失敗時（抓不到日K資料、資料不足、或缺少 peak2_idx 定位資訊）安靜地
    回傳原本的 res 不做任何修改，並標記 res["daily_refined"] = False。
    """
    res = dict(res)  # 不修改呼叫端傳進來的原始 dict

    peak2_idx = res.get("peak2_idx")
    if peak2_idx is None or peak2_idx not in weekly_df.index:
        res["daily_refined"] = False
        res["daily_refine_reason"] = "缺少 peak2_idx，無法定位日K精算起點"
        return res

    peak2_date = weekly_df.loc[peak2_idx, "DateStr"]

    try:
        daily_raw = download_with_retry(
            [ticker], batch_size=1, start=peak2_date, interval="1d", auto_adjust=True
        )
    except Exception as e:
        res["daily_refined"] = False
        res["daily_refine_reason"] = f"日K下載失敗: {e}"
        return res

    if ticker not in daily_raw:
        res["daily_refined"] = False
        res["daily_refine_reason"] = "日K下載結果中查無此標的"
        return res

    daily_df = prepare_dataframe(daily_raw[ticker], min_rows=1)
    if daily_df is None or len(daily_df) == 0:
        res["daily_refined"] = False
        res["daily_refine_reason"] = "日K資料清洗後筆數為0"
        return res

    zone = find_daily_strike_zone(daily_df, peak2_date)
    if zone is None:
        res["daily_refined"] = False
        res["daily_refine_reason"] = "日K資料中找不到對應的回踩期間"
        return res

    entry_price = res["entry_price"]  # 進場價維持用週K計算，不變
    candidate_stop = zone["zone_low"] * (1 - local_low_buffer)
    min_stop_ceiling = entry_price * (1 - min_risk_pct)
    stop_loss = min(candidate_stop, min_stop_ceiling)
    zone_too_tight = candidate_stop > min_stop_ceiling

    tp_adam = res["tp_adam"]  # 停利維持用週K翻亞當高度，不變
    risk = entry_price - stop_loss
    reward = tp_adam - entry_price
    rr_ratio = reward / risk if risk > 0 else 0.0

    res.update({
        "daily_refined": True,
        "stop_loss": float(stop_loss),
        "risk": float(risk),
        "reward": float(reward),
        "rr_ratio": float(rr_ratio),
        "zone_too_tight": zone_too_tight,
        "strike_zone_low": zone["zone_low"],
        "strike_zone_high": zone["zone_high"],
        "daily_zone_start_date": zone["zone_start_date"],
        "daily_zone_end_date": zone["zone_end_date"],
        "daily_zone_bar_count": zone["bar_count"],
    })

    return res
