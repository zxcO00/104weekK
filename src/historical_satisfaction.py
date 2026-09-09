"""
historical_satisfaction.py
「翻亞當（Second Reflection）歷史滿足紀錄」前置濾網。

核心概念：不只看「當前這根K棒」是否符合回踩滿足區，而是回頭掃描整段歷史，
找出過去所有『刺穿洗盤 + 收復邊界』的候選型態，檢查突破後一段時間內
股價是否曾經走到過 1:1 等距翻轉的滿足目標（tp_adam）。

滿足次數/滿足率可以當作這檔標的的「信任分數」——歷史上證明過這套方法在
它身上有效的標的，本次的即時訊號可信度理論上更高；反之，如果歷史上
「破底翻」後常常無法走到滿足目標（黏滯、假突破），代表這檔標的的
價格行為特性可能不適合這套策略，即便本次即時訊號成立也該打折扣看待。

跟 pattern_detector.py 的關係：
- pattern_detector.detect_boundary_shift() 只回答「當前這根K棒符不符合進場」
- 這個模組回答「這檔股票過去符不符合、成功率如何」——是輔助判斷用的
  歷史統計，不是即時訊號本身，兩者互相獨立、可以疊加使用。
"""

import numpy as np


def scan_historical_satisfactions(
    df,
    lookback_window=12,
    min_sweep_pct=0.015,
    max_sweep_pct=0.22,
    max_slope_pct_per_bar=0.018,
    confirm_window_bars=52,
    exclude_recent_bars=3,
):
    """
    掃描整段歷史，找出所有『邊界重塑』候選型態（洗盤深度、邊界斜率條件跟
    detect_boundary_shift 一致，但不要求「當前K棒回踩滿足區」），並檢查
    收復邊界（peak2）之後 confirm_window_bars 根K棒內，股價是否曾觸及
    1:1 等距翻轉滿足目標。

    exclude_recent_bars：排除最近幾根K棒，避免跟即時訊號本身重複計算
    （最新這根如果剛好也構成候選，會被 detect_boundary_shift 抓到，
    這裡只統計「已經走完、有時間驗證」的歷史事件）。

    回傳 list[dict]，每筆代表一次歷史候選型態的紀錄。
    """
    total = len(df)
    records = []

    s_idx = lookback_window
    scan_end = total - exclude_recent_bars

    while s_idx < scan_end:
        base_df = df.iloc[s_idx - lookback_window: s_idx]
        sweep_low = float(df.loc[s_idx, "Low"])

        x_base = np.arange(len(base_df))
        y_lows = base_df["Low"].values
        slope, intercept = np.polyfit(x_base, y_lows, 1)
        base_mean_price = float(np.mean(y_lows)) if len(y_lows) else 0.0

        if base_mean_price <= 0:
            s_idx += 1
            continue

        slope_pct = slope / base_mean_price
        if not (-0.005 <= slope_pct <= max_slope_pct_per_bar):
            s_idx += 1
            continue

        boundary_at_sweep = float(intercept + slope * len(base_df))
        if boundary_at_sweep <= 0:
            s_idx += 1
            continue

        sweep_depth = boundary_at_sweep - sweep_low
        sweep_pct = sweep_depth / boundary_at_sweep
        if not (min_sweep_pct <= sweep_pct <= max_sweep_pct):
            s_idx += 1
            continue

        # 往後找 peak2（收復邊界的反彈高點）
        search_end = min(s_idx + 1 + confirm_window_bars, total)
        post_sweep = df.iloc[s_idx + 1: search_end]
        if len(post_sweep) < 2:
            s_idx += 1
            continue

        peak2_local_idx = int(np.argmax(post_sweep["High"].values))
        peak2 = float(post_sweep["High"].iloc[peak2_local_idx])
        peak2_idx = s_idx + 1 + peak2_local_idx

        if peak2 < boundary_at_sweep:
            s_idx += 1
            continue

        pattern_height = peak2 - sweep_low
        tp_adam = boundary_at_sweep + pattern_height  # 以當時邊界為基準的等距翻轉目標

        # 檢查 peak2 之後 confirm_window_bars 根K棒內是否觸及 tp_adam
        confirm_start = peak2_idx + 1
        confirm_end = min(peak2_idx + 1 + confirm_window_bars, total)
        confirm_slice = df.iloc[confirm_start:confirm_end]

        satisfied = False
        bars_to_satisfy = None
        if len(confirm_slice) > 0:
            highs = confirm_slice["High"].values
            hit_indices = np.where(highs >= tp_adam)[0]
            if len(hit_indices) > 0:
                satisfied = True
                bars_to_satisfy = int(hit_indices[0]) + 1

        records.append({
            "sweep_idx": s_idx,
            "sweep_date": str(df.loc[s_idx, "DateStr"]),
            "peak2_idx": peak2_idx,
            "peak2_date": str(df.loc[peak2_idx, "DateStr"]),
            "boundary_at_sweep": boundary_at_sweep,
            "sweep_low": sweep_low,
            "peak2": peak2,
            "tp_adam": tp_adam,
            "satisfied": satisfied,
            "bars_to_satisfy": bars_to_satisfy,
        })

        # 跳過這次型態的收復/驗證期，避免同一事件被重複偵測
        s_idx = peak2_idx + 1

    return records


def historical_satisfaction_score(df, **kwargs):
    """
    對外主要入口：回傳這檔標的的歷史滿足統計摘要。

    satisfaction_rate 為 None 代表歷史上完全沒偵測到符合條件的候選型態
    （樣本數為 0，無法計算成功率，不代表「不好」，只是沒有可驗證的歷史事件）。
    """
    records = scan_historical_satisfactions(df, **kwargs)
    total = len(records)
    satisfied = sum(1 for r in records if r["satisfied"])

    return {
        "total_patterns": total,
        "satisfied_count": satisfied,
        "satisfaction_rate": (satisfied / total) if total > 0 else None,
        "records": records,
    }
