"""
position_sizing.py
依固定風險金額回推建議進場張數/股數與交割款估計，自動判定台股/美股並套用對應幣別與成本模型。
"""

import os

# ---- 預設值（可用環境變數覆寫，GitHub Actions 用這個）----
DEFAULT_RISK_AMOUNT_TWD = float(os.environ.get("POSITION_RISK_AMOUNT_TWD", 10000))
DEFAULT_USD_TWD_RATE = float(os.environ.get("USD_TWD_RATE", 32.0))

LOT_SIZE_TW = 1000       # 台股 1 張 = 1000 股
FEE_RATE = 0.001425      # 手續費率（買賣皆收，牌告費率粗估）
TAX_RATE = 0.003         # 證交稅率（僅賣出收取）
US_FLAT_COST_RATE = 0.001  # 美股交易成本粗估比例（實際依券商而定）


def is_us_ticker(ticker):
    return not (ticker.endswith(".TW") or ticker.endswith(".TWO"))


def calc_position_size(ticker, entry_price, stop_loss, risk_amount_twd=None, usd_twd_rate=None):
    """
    依固定風險金額回推建議部位。台股回傳整張（無條件捨去），美股回傳整股。

    risk_amount_twd / usd_twd_rate 可由呼叫端傳入覆寫預設值
    （例如 Streamlit 網頁讓使用者即時調整，不需要改環境變數）。

    回傳 None 代表風險無效（entry_price <= stop_loss）或風險金額不足以買進最小單位。
    """
    risk_per_share = entry_price - stop_loss
    if risk_per_share <= 0:
        return None

    risk_amount_twd = DEFAULT_RISK_AMOUNT_TWD if risk_amount_twd is None else risk_amount_twd
    usd_twd_rate = DEFAULT_USD_TWD_RATE if usd_twd_rate is None else usd_twd_rate

    is_us = is_us_ticker(ticker)

    if is_us:
        target_risk = risk_amount_twd / usd_twd_rate
        suggested_shares = int(target_risk // risk_per_share)
        actual_risk = suggested_shares * risk_per_share
        settlement_estimate = suggested_shares * entry_price
        unit_str = f"{suggested_shares} 股"
        currency = "USD"
        cost_estimate = settlement_estimate * US_FLAT_COST_RATE
    else:
        raw_shares = risk_amount_twd / risk_per_share
        suggested_lots = int(raw_shares // LOT_SIZE_TW)
        suggested_shares = suggested_lots * LOT_SIZE_TW
        actual_risk = suggested_shares * risk_per_share
        settlement_estimate = suggested_shares * entry_price
        unit_str = f"{suggested_lots} 張"
        currency = "NT$"

        buy_fee = settlement_estimate * FEE_RATE
        sell_at_stop = suggested_shares * stop_loss
        sell_fee = sell_at_stop * FEE_RATE
        sell_tax = sell_at_stop * TAX_RATE
        cost_estimate = buy_fee + sell_fee + sell_tax

    if suggested_shares <= 0:
        return None

    return {
        "is_us": is_us,
        "currency": currency,
        "unit_display": unit_str,
        "suggested_shares": suggested_shares,
        "actual_risk": actual_risk,
        "settlement_estimate": settlement_estimate,
        "total_cost_estimate": cost_estimate,
    }
