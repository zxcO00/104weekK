"""
scanner.py
主流程編排：下載資料 -> 五階段狀態機偵測 -> 部位試算 -> 繪圖 -> 推播 -> 輸出報告
（觸發清單 + 潛在觀察名單）。

設計原則：繪圖/推播失敗絕不能讓已偵測到的訊號消失——訊號偵測與呈現分離，
即使圖表產生失敗，也要保留訊號紀錄並改用純文字通知。

重要變更：pattern_detector.detect_boundary_shift() 現在永遠回傳一個 dict
（帶 status 欄位），不再回傳 None。只有 status == STATUS_TRIGGERED 才有完整
下單四要素；其餘狀態視為「潛在觀察名單」，另外整理成報告的第二個區塊。
"""

import os
import datetime
import traceback

from data_fetcher import fetch_all_watchlist, is_us_ticker, WATCHLIST_MAPPING
from pattern_detector import (
    detect_boundary_shift,
    STATUS_TRIGGERED, STATUS_WATCHING_RECLAIM, STATUS_WAITING_RETEST, STATUS_RR_REJECTED,
)
from historical_satisfaction import historical_satisfaction_score
from visualizer import plot_and_save
from position_sizing import calc_position_size
from notifier import (
    send_telegram_alert, send_discord_alert, send_telegram_text,
    send_failure_notice, send_data_warning,
)

DATA_PERIOD = os.environ.get("DATA_PERIOD", "2y")
DATA_INTERVAL = os.environ.get("DATA_INTERVAL", "1wk")
BATCH_SIZE = int(os.environ.get("YF_BATCH_SIZE", 15))

# 歷史滿足紀錄前置濾網門檻：預設 0 代表不濾掉任何訊號，只是把統計資料附加到報告裡。
# 等回測驗證過合理門檻後，再調高這個環境變數即可啟用真正的過濾。
MIN_HISTORICAL_SATISFACTIONS = int(os.environ.get("MIN_HISTORICAL_SATISFACTIONS", 0))

# 哪些「未觸發」狀態值得列進潛在觀察名單（排除掉太早期、資訊量不足的狀態）
_WATCHLIST_STATUSES = {STATUS_WATCHING_RECLAIM, STATUS_WAITING_RETEST, STATUS_RR_REJECTED}

_STATUS_LABELS = {
    STATUS_WATCHING_RECLAIM: "等待強勢收復站回邊界",
    STATUS_WAITING_RETEST: "已收復，等待回踩滿足區",
    STATUS_RR_REJECTED: "已回踩滿足區，但風報比不足",
}


def run_scan():
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 啟動觀察池自動監控掃描...")

    stock_data = fetch_all_watchlist(period=DATA_PERIOD, interval=DATA_INTERVAL, batch_size=BATCH_SIZE)

    # 若成功載入的標的數量遠低於觀察池總數，代表 yfinance 在此環境可能被限流，
    # 掃描結果不可信——直接告警，避免誤以為「本週沒有訊號」。
    send_data_warning(len(stock_data), len(WATCHLIST_MAPPING))

    triggers = []
    watchlist = []
    plot_failures = 0

    print("\n>> 正在以五階段狀態機檢驗各標的最新週K棒...")
    for ticker, (name, df) in stock_data.items():
        # 第一階段：偵測型態（絕對不能被繪圖/推播的例外影響）
        try:
            res = detect_boundary_shift(df)
        except Exception as e:
            print(f"⚠️ 偵測 {ticker} 時發生錯誤，略過: {e}")
            continue

        status = res.get("status")

        if status in _WATCHLIST_STATUSES:
            watchlist.append({"ticker": ticker, "name": name, "status": status, "res": res})

        if status != STATUS_TRIGGERED:
            continue

        # 歷史滿足紀錄前置濾網（信任分數，非即時訊號本身）
        try:
            hist = historical_satisfaction_score(df)
        except Exception as e:
            print(f"⚠️ {ticker} 歷史滿足統計失敗，視為無資料: {e}")
            hist = {"total_patterns": 0, "satisfied_count": 0, "satisfaction_rate": None}

        if hist["satisfied_count"] < MIN_HISTORICAL_SATISFACTIONS:
            print(f"⏭️ {ticker}（{name}）歷史滿足次數 {hist['satisfied_count']} 低於門檻 {MIN_HISTORICAL_SATISFACTIONS}，略過")
            continue

        is_us = is_us_ticker(ticker)
        pos = calc_position_size(ticker, res["entry_price"], res["stop_loss"])

        # 一旦偵測到訊號，先記錄下來 —— 就算後面繪圖/推播失敗，這筆也不會消失
        trigger = {
            "ticker": ticker, "name": name, "res": res, "pos": pos,
            "is_us": is_us, "img_path": None, "hist": hist,
        }
        triggers.append(trigger)

        prefix = "[美股-週K]" if is_us else "[台股-週K]"
        print("=" * 65)
        print(f"【本週即時觸發】 {prefix} {name}（日期: {res['date']}）")
        print(f">> 入場價: {res['entry_price']:.2f} | 動態邊界: {res['boundary']:.2f}")
        if res.get("zone_too_tight"):
            print(">> ⚠️ 打擊區過窄（反彈高點才發生沒幾根K棒，回檔尚未止穩），停損已套用風險下限")
        print(f">> 防守停損: {res['stop_loss']:.2f} | 目標停利: {res['tp_adam']:.2f} | 風報比: {res['rr_ratio']:.2f}")
        if pos:
            print(
                f">> 部位建議: {pos['unit_display']}"
                f"（交割款: {pos['currency']} {pos['settlement_estimate']:,.0f}"
                f" | 風險: {pos['currency']} {pos['actual_risk']:,.0f}）"
            )
        rate_str = f"{hist['satisfaction_rate']*100:.0f}%" if hist["satisfaction_rate"] is not None else "無歷史樣本"
        print(f">> 歷史翻亞當滿足紀錄: {hist['satisfied_count']}/{hist['total_patterns']}（滿足率 {rate_str}）")
        print("=" * 65)

        # 第二階段：繪圖（失敗不影響訊號本身，改推純文字通知）
        try:
            trigger["img_path"] = plot_and_save(df, ticker, name, res)
        except Exception as e:
            plot_failures += 1
            print(f"⚠️ {ticker} 繪圖失敗（訊號仍保留）: {e}")

        # 第三階段：推播（各自獨立 try，互不影響）
        try:
            if trigger["img_path"]:
                send_telegram_alert(name, res, trigger["img_path"], pos, is_us)
            else:
                send_telegram_text(name, res, pos, is_us)
        except Exception as e:
            print(f"⚠️ {ticker} Telegram 推播失敗: {e}")

        try:
            if trigger["img_path"]:
                send_discord_alert(name, res, trigger["img_path"], pos, is_us)
        except Exception as e:
            print(f"⚠️ {ticker} Discord 推播失敗: {e}")

    if plot_failures:
        print(f"\n⚠️ 共有 {plot_failures} 檔標的繪圖失敗（可能是中文字型下載問題），但訊號已保留在報告中。")

    print(f"\n🏁 掃描完成！全市場共有 {len(triggers)} 檔標的正式觸發，{len(watchlist)} 檔進入潛在觀察名單。\n")
    write_report(triggers, watchlist)
    return triggers, watchlist


def write_report(triggers, watchlist=None, path="scan_summary.md"):
    watchlist = watchlist or []
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"## 觀察池邊界重塑掃描報告（{datetime.date.today()}）\n\n")

        if not triggers:
            f.write("本週全市場（台股0050＋中型100＋美股大型科技）無正式觸發標的。\n\n")
        else:
            sorted_triggers = sorted(triggers, key=lambda t: t["res"]["rr_ratio"], reverse=True)

            f.write("### 正式觸發清單\n\n")
            f.write("| 標的 | 入場 | 動態邊界 | 停損 | 停利 | R/R | 建議部位 | 交割款估計 | 歷史滿足 | 打擊區 | 圖表 |\n")
            f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
            for t in sorted_triggers:
                name, res, pos = t["name"], t["res"], t["pos"]
                chart_note = "✅" if t["img_path"] else "⚠️失敗"
                hist = t.get("hist") or {"satisfied_count": 0, "total_patterns": 0}
                hist_note = f"{hist['satisfied_count']}/{hist['total_patterns']}"
                zone_note = "⚠️過窄" if res.get("zone_too_tight") else "✅"
                if pos:
                    f.write(
                        f"| {name} | {res['entry_price']:.2f} | {res['boundary']:.2f} | "
                        f"{res['stop_loss']:.2f} | {res['tp_adam']:.2f} | {res['rr_ratio']:.2f} | "
                        f"{pos['unit_display']} | {pos['currency']} {pos['settlement_estimate']:,.0f} | "
                        f"{hist_note} | {zone_note} | {chart_note} |\n"
                    )
                else:
                    f.write(
                        f"| {name} | {res['entry_price']:.2f} | {res['boundary']:.2f} | "
                        f"{res['stop_loss']:.2f} | {res['tp_adam']:.2f} | {res['rr_ratio']:.2f} | - | - | "
                        f"{hist_note} | {zone_note} | {chart_note} |\n"
                    )


            f.write("\n### 適合入場精簡清單\n\n")
            for idx, t in enumerate(sorted_triggers, start=1):
                f.write(f"{idx}. {t['name']}\n")

        f.write("\n### 潛在觀察名單（尚未觸發，但已進入型態關鍵階段）\n\n")
        if not watchlist:
            f.write("本週無標的進入觀察階段。\n")
        else:
            f.write("| 標的 | 目前階段 | 診斷細節 |\n")
            f.write("| :--- | :--- | :--- |\n")
            for w in watchlist:
                label = _STATUS_LABELS.get(w["status"], w["status"])
                reason = w.get("res", {}).get("reason", "-")
                f.write(f"| {w['name']} | {label} | {reason} |\n")


def main():
    try:
        run_scan()
    except Exception:
        error_message = traceback.format_exc()
        print(f"❌ 掃描流程整體失敗:\n{error_message}")
        send_failure_notice(error_message[-500:])
        raise


if __name__ == "__main__":
    main()
