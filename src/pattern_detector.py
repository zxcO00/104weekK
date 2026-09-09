"""
pattern_detector.py
老余（余適安）裸K交易體系 —— 「邊界重塑」五階段狀態機。

核心心法：「先有大格局邊界，再找小細節，吃在邊界，守在外面」，
結合 J. Welles Wilder 翻亞當（Second Reflection，1:1 等距鏡像對稱）。

五個階段：
  狀態1 Level Formation  大格局關鍵邊界確立 —— 找出至少 2 次以上測試過的支撐低點，
                          容許邊界走平或微幅向上墊高。
  狀態2 Liquidity Sweep  刺穿假跌破 —— 深 V 刺穿邊界，深度需在合理範圍。
  狀態3 Reclaim          強勢收復確認（翻亞當條件成立）—— 收盤站回邊界之上，
                          且不能在低檔盤整拖太久。
  狀態4 Retest           滿足區回踩「摸邊界」—— 絕不追高突破，只在回踩時吃單。
  狀態5 Risk/Reward      老余流風控與停利定錨 —— 進場/停損/停利定價 + 風報比濾網。

回傳格式（重要變更）：
  detect_boundary_shift() 永遠回傳一個 dict，不再回傳 None。
  每個 dict 都帶 "status" 欄位，可能是以下常數之一：
    STATUS_INSUFFICIENT_DATA / STATUS_NO_VALID_LEVEL / STATUS_WATCHING_SWEEP /
    STATUS_WATCHING_RECLAIM / STATUS_WAITING_RETEST / STATUS_RR_REJECTED /
    STATUS_TRIGGERED
  只有 status == STATUS_TRIGGERED 時，dict 才會包含完整的下單四要素
  （entry_price, stop_loss, tp_adam, boundary, box_top, box_bottom, rr_ratio 等），
  這些 key 名稱與 visualizer.py / position_sizing.py 完全相容。
  其餘狀態的 dict 只帶偵測到的中繼資訊，用來組成「潛在觀察名單」。

v3 更新（依合作夥伴實盤圖表核對修正，以欣興3037為例）：
  - 狀態5停損不再用「狀態2深洗盤最低點」計算，改用「收復邊界後、回踩打擊區
    這段期間的實際局部低點」（strike_zone_low）外側緩衝（預設1%）——貼合實盤
    「吃單守在打擊區外側」的用法，大幅縮減停損距離、拉高風報比。
  - 翻亞當高度（pattern_height）計算基準維持用深洗盤低點不變，這部分經
    合作夥伴確認已經很準確（如欣興週線滿足算出1413，跟手繪1500很接近）。
  - 新增 strike_zone_high / strike_zone_low / strike_zone_start_idx 欄位，
    供 visualizer.py 畫出真正包覆回踩K棒密集區的黃框，而非固定百分比帶。
"""

import numpy as np

# ---- 狀態常數 ----
STATUS_INSUFFICIENT_DATA = "STATUS_INSUFFICIENT_DATA"
STATUS_NO_VALID_LEVEL = "STATUS_NO_VALID_LEVEL"
STATUS_WATCHING_SWEEP = "STATUS_WATCHING_SWEEP"        # 邊界已成立，等待深洗盤出現
STATUS_WATCHING_RECLAIM = "STATUS_WATCHING_RECLAIM"    # 洗盤已現，等待強勢收復站回邊界
STATUS_WAITING_RETEST = "STATUS_WAITING_RETEST"        # 已收復，等待回踩滿足區
STATUS_RR_REJECTED = "STATUS_RR_REJECTED"              # 已回踩滿足區，但風報比不足
STATUS_TRIGGERED = "STATUS_TRIGGERED"                  # 五階段全部滿足，正式觸發進場

# 狀態的「進度排名」，數字越大代表越接近觸發，用來在多個候選洗盤點裡挑出
# 目前最值得關注的那一個（回傳給主程式當觀察名單用）。
_STATUS_RANK = {
    STATUS_NO_VALID_LEVEL: 0,
    STATUS_WATCHING_SWEEP: 1,
    STATUS_WATCHING_RECLAIM: 2,
    STATUS_WAITING_RETEST: 3,
    STATUS_RR_REJECTED: 4,
}


# ==============================================================================
# 狀態 1：大格局關鍵邊界確立（Level Formation）
# ==============================================================================
def _stage1_level_formation(df, s_idx, lookback_window, max_slope_pct_per_bar,
                             touch_tolerance_pct=0.015, min_touches=2):
    """
    回溯 s_idx 之前 lookback_window 根K棒，用線性回歸抓出動態邊界基準線。
    要求：
      - 邊界走平或微幅向上（斜率百分比落在 [-0.5%, max_slope_pct_per_bar]）。
      - 至少有 min_touches 根K棒的低點貼近邊界（視為「測試過的支撐」）。
    成立回傳 (result_dict, None)；不成立回傳 (None, reason_str) —— reason_str
    帶著具體數字，方便追查「差在哪裡」而不用每次都用資料反推猜測。
    """
    if s_idx - lookback_window < 0:
        return None, "資料不足以回溯 lookback_window"

    base_df = df.iloc[s_idx - lookback_window: s_idx]
    if len(base_df) < lookback_window:
        return None, "資料不足以回溯 lookback_window"

    x_base = np.arange(len(base_df))
    y_lows = base_df["Low"].values
    slope, intercept = np.polyfit(x_base, y_lows, 1)

    base_mean_price = float(np.mean(y_lows))
    if base_mean_price <= 0:
        return None, "基準價格無效"

    slope_pct = slope / base_mean_price
    if not (-0.005 <= slope_pct <= max_slope_pct_per_bar):
        return None, f"邊界斜率 {slope_pct*100:.2f}%/週，超出允許範圍 [-0.5%, {max_slope_pct_per_bar*100:.1f}%]"

    fitted = intercept + slope * x_base
    touches = int(np.sum(np.abs(y_lows - fitted) / fitted <= touch_tolerance_pct))
    if touches < min_touches:
        return None, f"邊界只被測試過 {touches} 次，未達最低要求 {min_touches} 次"

    return {"slope": float(slope), "intercept": float(intercept),
            "base_len": len(base_df), "touches": touches}, None


def _boundary_at(level, position_from_base_start):
    """依線性回歸結果，推算某個相對位置上的邊界價位"""
    return float(level["intercept"] + level["slope"] * position_from_base_start)


# ==============================================================================
# 狀態 2：刺穿假跌破（Liquidity Sweep）
# ==============================================================================
def _stage2_sweep(df, s_idx, level, min_sweep_pct, max_sweep_pct):
    """
    檢查 s_idx 這根K棒是否構成有效的「刺穿假跌破」：
    跌破當時邊界的深度需落在 [min_sweep_pct, max_sweep_pct] 之間
    （太淺是雜訊，太深視為真跌破/倒莊，不是假跌破）。

    回傳 (result_dict_or_None, sweep_pct)：sweep_pct 無論成功與否都會回傳，
    方便呼叫端在失敗時記錄「差多少沒過關」，不用每次都靠外部反推猜測。
    """
    boundary_at_sweep = _boundary_at(level, level["base_len"])
    if boundary_at_sweep <= 0:
        return None, None

    sweep_low = float(df.loc[s_idx, "Low"])
    sweep_pct = (boundary_at_sweep - sweep_low) / boundary_at_sweep
    if not (min_sweep_pct <= sweep_pct <= max_sweep_pct):
        return None, sweep_pct

    return {"boundary_at_sweep": boundary_at_sweep, "sweep_low": sweep_low,
            "sweep_pct": sweep_pct}, sweep_pct


# ==============================================================================
# 狀態 3：強勢收復確認（Reclaim / 翻亞當條件成立）
# ==============================================================================
def _stage3_reclaim(df, s_idx, last_idx, sweep, max_bars_to_reclaim=6):
    """
    要求刺穿後數根K棒內，收盤價要明確站回邊界之上，且不能在低檔盤整拖太久
    （超過 max_bars_to_reclaim 根都沒收復，視為破位確立、型態失敗）。
    收復後記錄波段最高點 Peak，計算翻亞當高度 pattern_height = Peak - L_sweep。

    回傳 (result_dict, None) 或 (None, reason_str)，reason_str 附上具體數字。
    """
    post_sweep = df.iloc[s_idx + 1: last_idx]
    if len(post_sweep) < 2:
        return None, "刺穿後可用K棒不足2根，無法判斷是否收復"

    closes = post_sweep["Close"].values
    reclaim_hits = np.where(closes > sweep["boundary_at_sweep"])[0]
    if len(reclaim_hits) == 0:
        return None, "到目前為止收盤價都沒有站回邊界之上"

    bars_to_reclaim = int(reclaim_hits[0]) + 1
    if bars_to_reclaim > max_bars_to_reclaim:
        return None, f"收復花了 {bars_to_reclaim} 根K棒，超過允許的 {max_bars_to_reclaim} 根（低檔盤整拖太久）"

    peak2_local_idx = int(np.argmax(post_sweep["High"].values))
    peak2 = float(post_sweep["High"].iloc[peak2_local_idx])
    peak2_idx = s_idx + 1 + peak2_local_idx

    if peak2 < sweep["boundary_at_sweep"]:
        return None, "收復後的反彈高點仍未站上邊界"

    pattern_height = peak2 - sweep["sweep_low"]

    return {"peak2": peak2, "peak2_idx": peak2_idx, "pattern_height": pattern_height,
            "bars_to_reclaim": bars_to_reclaim}, None


# ==============================================================================
# 狀態 4：滿足區回踩「摸邊界」（Retest / 綠框吃單點）
# ==============================================================================
def _stage4_retest(df, last_idx, s_idx, level):
    """
    老余核心戒律：「絕不追高突破，只在回踩邊界時吃單」。
    以「當前」動態邊界（外推到 last_idx）為基準，計算滿足區：
      Box_top    = S_current * 1.035
      Box_bottom = S_current * 0.985
    最新一根K棒必須同時滿足：最低價踩進滿足區、收盤守穩滿足區下緣。
    """
    position_from_base_start = last_idx - (s_idx - level["base_len"])
    boundary_at_current = _boundary_at(level, position_from_base_start)

    box_top = boundary_at_current * 1.035
    box_bottom = boundary_at_current * 0.985

    curr_low = float(df.loc[last_idx, "Low"])
    curr_close = float(df.loc[last_idx, "Close"])

    if not (curr_low <= box_top and curr_close >= box_bottom):
        return None

    return {
        "boundary_at_current": boundary_at_current,
        "box_top": box_top, "box_bottom": box_bottom,
        "curr_low": curr_low, "curr_close": curr_close,
    }


def _find_strike_zone(df, retest_start_idx, last_idx):
    """
    打擊區（吃單區間）的實際局部低/高點 —— 從收復邊界後的反彈高點（peak2）算起，
    到目前這根K棒為止，這段「回檔到密集支撐帶」期間的真實低點與高點。

    這是狀態5停損的基準：用這段回踩期間的局部低點，而不是狀態2那個整段型態
    最深的洗盤低點（sweep_low）——後者拿來當停損太遠，會不合理地拉大風險。
    """
    zone_slice = df.iloc[retest_start_idx: last_idx + 1]
    if len(zone_slice) == 0:
        # 邊界情況（peak2 剛好就是上一根K棒）：退回只看當前這根K棒
        curr_low = float(df.loc[last_idx, "Low"])
        curr_high = float(df.loc[last_idx, "High"])
        return {"zone_low": curr_low, "zone_high": curr_high, "zone_start_idx": last_idx}

    zone_low = float(zone_slice["Low"].min())
    zone_high = float(zone_slice["High"].max())
    return {"zone_low": zone_low, "zone_high": zone_high, "zone_start_idx": retest_start_idx}


# ==============================================================================
# 狀態 5：老余流風控與停利定錨（Risk / Reward）
# ==============================================================================
def _stage5_risk_reward(sweep, reclaim, retest, strike_zone, min_rr, local_low_buffer=0.01):
    """
    Entry = max(S_current, L_current)
    SL    = 打擊區局部低點（strike_zone.zone_low）外側緩衝（預設 1%）
            —— 不再用狀態2的深洗盤低點，改用「這次回踩打擊區時」的實際低點，
            大幅縮減停損距離、拉高風報比，貼合實盤「吃單守在區間外側」的用法。
    TP    = Entry + pattern_height（1:1 翻亞當對稱滿足，維持用 sweep_low 算高度不變）
    風報比濾網：RR >= min_rr
    """
    entry_price = max(retest["boundary_at_current"], retest["curr_low"])
    stop_loss = strike_zone["zone_low"] * (1 - local_low_buffer)
    tp_adam = entry_price + reclaim["pattern_height"]

    risk = entry_price - stop_loss
    reward = tp_adam - entry_price
    rr_ratio = reward / risk if risk > 0 else 0.0

    if rr_ratio < min_rr:
        return None, rr_ratio

    return {
        "entry_price": float(entry_price),
        "stop_loss": float(stop_loss),
        "tp_adam": float(tp_adam),
        "risk": float(risk),
        "reward": float(reward),
        "rr_ratio": float(rr_ratio),
    }, rr_ratio


# ==============================================================================
# 主流程：五階段狀態機
# ==============================================================================
def detect_boundary_shift(
    df,
    lookback_window=12,
    max_bars_since_sweep=12,
    min_sweep_pct=0.015,
    max_sweep_pct=0.22,
    max_slope_pct_per_bar=0.018,
    max_bars_to_reclaim=6,
    min_rr=1.05,
    touch_tolerance_pct=0.015,
    min_touches=2,
    local_low_buffer=0.01,
):
    """
    永遠回傳一個 dict（不再回傳 None）。
    status == STATUS_TRIGGERED 時，dict 帶完整下單四要素；
    其餘狀態的 dict 帶目前偵測到、最值得關注的中繼資訊（含 "reason" 診斷文字），
    可用來組觀察名單、或追查「為什麼這檔沒被抓到」。

    註：max_sweep_pct 預設 22%（原始規格建議 20%，但實測欣興(3037)
    的洗盤深度約 20.36%，卡在 20% 門檻外——改回 22% 較貼合實盤情況）。
    """
    total = len(df)
    if total < lookback_window + 8:
        return {"status": STATUS_INSUFFICIENT_DATA, "reason": "資料筆數不足"}

    last_idx = total - 1

    best_status = STATUS_NO_VALID_LEVEL
    best_rank = -1
    best_context = {}

    def _update_best(status, context):
        nonlocal best_status, best_rank, best_context
        rank = _STATUS_RANK.get(status, -1)
        if rank > best_rank:
            best_rank = rank
            best_status = status
            best_context = context

    scan_from = max(last_idx - max_bars_since_sweep, lookback_window)

    for s_idx in range(last_idx - 2, scan_from, -1):
        # ---- 狀態 1：大格局邊界確立 ----
        level, level_reason = _stage1_level_formation(
            df, s_idx, lookback_window, max_slope_pct_per_bar, touch_tolerance_pct, min_touches
        )
        if level is None:
            _update_best(STATUS_NO_VALID_LEVEL, {"sweep_idx": s_idx, "reason": level_reason})
            continue  # 這個候選點連邊界都立不住，看下一個候選

        # ---- 狀態 2：刺穿假跌破 ----
        sweep, sweep_pct_attempt = _stage2_sweep(df, s_idx, level, min_sweep_pct, max_sweep_pct)
        if sweep is None:
            reason = None
            if sweep_pct_attempt is not None:
                reason = (f"洗盤深度 {sweep_pct_attempt*100:.2f}%，"
                          f"超出允許範圍 [{min_sweep_pct*100:.1f}%, {max_sweep_pct*100:.1f}%]")
            _update_best(STATUS_WATCHING_SWEEP, {
                "sweep_idx": s_idx,
                "boundary": _boundary_at(level, level["base_len"]),
                "reason": reason,
            })
            continue

        # ---- 狀態 3：強勢收復確認（翻亞當條件成立）----
        reclaim, reclaim_reason = _stage3_reclaim(df, s_idx, last_idx, sweep, max_bars_to_reclaim)
        if reclaim is None:
            _update_best(STATUS_WATCHING_RECLAIM, {
                "sweep_idx": s_idx,
                "sweep_low": sweep["sweep_low"],
                "boundary_at_sweep": sweep["boundary_at_sweep"],
                "reason": reclaim_reason,
            })
            continue

        # ---- 狀態 4：滿足區回踩 ----
        retest = _stage4_retest(df, last_idx, s_idx, level)
        if retest is None:
            _update_best(STATUS_WAITING_RETEST, {
                "sweep_idx": s_idx,
                "peak2": reclaim["peak2"],
                "sweep_low": sweep["sweep_low"],
                "pattern_height": reclaim["pattern_height"],
            })
            continue

        # ---- 狀態 5：風控與停利定錨 ----
        strike_zone = _find_strike_zone(df, reclaim["peak2_idx"] + 1, last_idx)
        risk_reward, rr_ratio = _stage5_risk_reward(sweep, reclaim, retest, strike_zone, min_rr, local_low_buffer)
        if risk_reward is None:
            _update_best(STATUS_RR_REJECTED, {
                "sweep_idx": s_idx,
                "boundary": retest["boundary_at_current"],
                "box_top": retest["box_top"],
                "box_bottom": retest["box_bottom"],
                "rr_ratio": rr_ratio,
            })
            continue

        # ---- 五階段全部通過：正式觸發進場 ----
        return {
            "status": STATUS_TRIGGERED,
            "boundary": retest["boundary_at_current"],
            "boundary_slope": level["slope"],
            "sweep_low": sweep["sweep_low"],
            "peak2": reclaim["peak2"],
            "peak2_idx": reclaim["peak2_idx"],
            "entry_price": risk_reward["entry_price"],
            "stop_loss": risk_reward["stop_loss"],
            "tp_adam": risk_reward["tp_adam"],
            "box_top": retest["box_top"],
            "box_bottom": retest["box_bottom"],
            "strike_zone_high": strike_zone["zone_high"],
            "strike_zone_low": strike_zone["zone_low"],
            "strike_zone_start_idx": strike_zone["zone_start_idx"],
            "risk": risk_reward["risk"],
            "reward": risk_reward["reward"],
            "rr_ratio": risk_reward["rr_ratio"],
            "date": str(df.loc[last_idx, "DateStr"]),
            "sweep_idx": s_idx,
        }

    # 沒有任何候選點走完五階段，回傳目前停留的最遠狀態（供觀察名單使用）
    return {"status": best_status, **best_context}
