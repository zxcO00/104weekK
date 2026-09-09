"""
pattern_detector.py
「邊界重塑 (Boundary Reset)」型態偵測邏輯 — 動態斜率邊界 + 滿足區回踩 + 緊縮箱型精算版。

v2 更新（依實盤人工核對修正）：
- 滿足區判斷（動態邊界±3.5%/1.5%）維持不變，這部分跟人工判讀吻合度高。
- 進場/停損不再直接用「動態邊界」與「洗盤最深點」計算，改成優先尋找進場前
  最近一段「緊縮盤整箱型」，用箱型高/低點精算進場與停損——更貼近實盤習慣的
  「盤整區間突破」邏輯，停損也更貼近進場價（不是整段型態的最深洗盤點）。
- 新增排除條件：如果這個緊縮箱型跟洗盤後的反彈高點（peak2）距離太近
  （中間沒有拉開足夠的整理時間），視為「黏在一起」的劣質型態，直接排除。
- 找不到符合條件的緊縮箱型時，退回舊版公式（動態邊界 / 洗盤低點）計算，
  避免因為箱型判定過嚴而漏掉原本能抓到的訊號。
"""

import numpy as np


def _find_tight_box(df, end_idx, min_bars=2, max_bars=6, max_range_pct=0.06):
    """
    從 end_idx（含）往前找一段「緊縮盤整箱型」——連續 N 根週K的高低波動幅度
    都在 max_range_pct 以內。會嘗試從 min_bars 逐步放大到 max_bars，回傳能維持
    在門檻內的最大範圍（箱型抓得越完整越好）。

    回傳 (box_high, box_low, box_start_idx)；完全找不到符合條件的箱型則回傳 None。
    """
    best = None
    for n in range(min_bars, max_bars + 1):
        start = end_idx - n + 1
        if start < 0:
            break
        window = df.iloc[start:end_idx + 1]
        box_high = float(window["High"].max())
        box_low = float(window["Low"].min())
        if box_low <= 0:
            continue
        box_range_pct = (box_high - box_low) / box_low
        if box_range_pct <= max_range_pct:
            best = (box_high, box_low, start)
        else:
            # 視窗只會越放越寬，範圍只會越算越大，一旦超標就不用再往下試
            break
    return best


def detect_boundary_shift(
    df,
    lookback_window=12,
    max_bars_since_sweep=12,
    min_sweep_pct=0.015,
    max_sweep_pct=0.22,
    max_slope_pct_per_bar=0.018,
    min_rr=1.05,
    box_min_bars=2,
    box_max_bars=6,
    box_max_range_pct=0.06,
    box_stop_buffer=0.005,
    min_box_gap_bars=2,
):
    """
    以線性回歸抓出微正斜率通道的動態邊界，判斷最新一根週K棒是否回踩「滿足區」；
    符合條件後，優先用「進場前的緊縮盤整箱型」精算進場/停損，找不到箱型才退回
    舊版公式。符合條件回傳下單四要素 dict，否則回傳 None。

    新增排除條件：緊縮箱型如果跟洗盤後反彈高點（peak2）距離小於 min_box_gap_bars，
    視為型態「黏在一起」，直接排除這個候選（不會退回舊公式，直接判定不合格）。
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

        peak2_local_idx = int(np.argmax(post_sweep["High"].values))
        peak2 = float(post_sweep["High"].iloc[peak2_local_idx])
        peak2_idx = s_idx + 1 + peak2_local_idx

        if peak2 < boundary_at_sweep:
            continue

        box_top = boundary_at_current * 1.035
        box_bottom = boundary_at_current * 0.985

        if not (curr_low <= box_top and curr_close >= box_bottom):
            continue

        # ---- 進場/停損精算：優先用緊縮盤整箱型，找不到才退回舊公式 ----
        tight_box = _find_tight_box(
            df, last_idx, min_bars=box_min_bars, max_bars=box_max_bars, max_range_pct=box_max_range_pct
        )

        entry_mode = "fallback"
        if tight_box:
            box_high, box_low, box_start_idx = tight_box
            gap_bars = box_start_idx - peak2_idx

            if gap_bars < min_box_gap_bars:
                # 箱型跟洗盤後反彈高點黏得太近 —— 劣質型態，直接排除這個候選
                continue

            entry_price = box_high
            stop_loss = box_low * (1 - box_stop_buffer)
            entry_mode = "tight_box"
        else:
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
            "entry_mode": entry_mode,
        }

    return None
