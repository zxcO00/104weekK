"""
pattern_detector.py
「邊界重塑 (Boundary Reset)」型態偵測邏輯 — 動態斜率邊界 + 滿足區回踩版本。
"""

import numpy as np


def detect_boundary_shift(
    df,
    lookback_window=12,
    max_bars_since_sweep=12,
    min_sweep_pct=0.015,
    max_sweep_pct=0.22,
    max_slope_pct_per_bar=0.018,
    min_rr=1.05,
):
    """
    以線性回歸抓出微正斜率通道的動態邊界，判斷最新一根週K棒是否回踩「滿足區」
    （動態邊界 ±3.5%/1.5% 的區間）。符合條件回傳下單四要素 dict，否則回傳 None。
    """
    total = len(df)
    if total < lookback_window + 8:
        return None

    last_idx = total - 1
    curr_low = float(df.loc[last_idx, "Low"])
    curr_close = float(df.loc[last_idx, "Close"])

    for s_idx in range(last_idx - 2, max(last_idx - max_bars_since_sweep, lookback_window), -1):
        base_df = df.iloc[s_idx - lookback_window: s_idx]
        sweep_low = float(df.loc[s_idx, "Low"])

        x_base = np.arange(len(base_df))
        y_lows = base_df["Low"].values
        slope, intercept = np.polyfit(x_base, y_lows, 1)

        base_mean_price = float(np.mean(y_lows))
        slope_pct = slope / base_mean_price

        # 邊界只允許持平或微幅上揚的通道（排除明顯下降趨勢的假訊號）
        if not (-0.005 <= slope_pct <= max_slope_pct_per_bar):
            continue

        boundary_at_sweep = float(intercept + slope * len(base_df))
        boundary_at_current = float(intercept + slope * (last_idx - (s_idx - lookback_window)))

        sweep_depth = boundary_at_sweep - sweep_low
        sweep_pct = sweep_depth / boundary_at_sweep
        if not (min_sweep_pct <= sweep_pct <= max_sweep_pct):
            continue

        post_sweep = df.iloc[s_idx + 1: last_idx]
        if len(post_sweep) < 2:
            continue

        peak2 = float(post_sweep["High"].max())
        if peak2 < boundary_at_sweep:
            continue

        box_top = boundary_at_current * 1.035
        box_bottom = boundary_at_current * 0.985

        if not (curr_low <= box_top and curr_close >= box_bottom):
            continue

        entry_price = float(max(boundary_at_current, curr_low))
        stop_loss = float(sweep_low * 0.992)
        pattern_height = peak2 - sweep_low
        tp_adam = float(entry_price + pattern_height)

        risk = entry_price - stop_loss
        reward = tp_adam - entry_price
        rr_ratio = reward / risk if risk > 0 else 0

        if rr_ratio < min_rr:
            continue

        return {
            "boundary": boundary_at_current,
            "boundary_slope": slope,
            "sweep_low": sweep_low,
            "peak2": peak2,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "tp_adam": tp_adam,
            "box_top": box_top,
            "box_bottom": box_bottom,
            "risk": risk,
            "reward": reward,
            "rr_ratio": rr_ratio,
            "date": str(df.loc[last_idx, "DateStr"]),
            "sweep_idx": s_idx,
        }

    return None
