"""
position_sizing.py
依固定風險金額回推建議進場張數/股數與交割款估計，自動判定台股/美股並套用對應幣別與成本模型。
"""

import os

# ---- 可調參數（可用環境變數覆寫，不用改程式碼）----
POSITION_RISK_AMOUNT_TWD = float(os.environ.get("POSITION_RISK_AMOUNT_TWD", 10000))
USD_TWD_RATE = float(os.environ.get("USD_TWD_RATE", 32.0))
POSITION_RISK_AMOUNT_USD = POSITION_RISK_AMOUNT_TWD / USD_TWD_RATE

LOT_SIZE_TW = 1000       # 台股 1 張 = 1000 股
FEE_RATE = 0.001425      # 手續費率（買賣皆收，牌告費率粗估）
TAX_RATE = 0.003         # 證交稅率（僅賣出收取）
US_FLAT_COST_RATE = 0.001  # 美股交易成本粗估比例（實際依券商而定）


def is_us_ticker(ticker):
    return not (ticker.endswith(".TW") or ticker.endswith(".TWO"))


def calc_position_size(ticker, entry_price, stop_loss):
    """
    依固定風險金額回推建議部位。台股回傳整張（無條件捨去），美股回傳整股。
    回傳 None 代表 entry_price <= stop_loss（風險無效，不應該進場）。
    """
    risk_per_share = entry_price - stop_loss
    if risk_per_share <= 0:
        return None

    is_us = is_us_ticker(ticker)

    if is_us:
        target_risk = POSITION_RISK_AMOUNT_USD
        suggested_shares = int(target_risk // risk_per_share)
        actual_risk = suggested_shares * risk_per_share
        settlement_estimate = suggested_shares * entry_price
        unit_str = f"{suggested_shares} 股"
        currency = "USD"
        cost_estimate = settlement_estimate * US_FLAT_COST_RATE
    else:
        target_risk = POSITION_RISK_AMOUNT_TWD
        raw_shares = target_risk / risk_per_share
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
