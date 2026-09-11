"""
app.py
Streamlit 網頁版：邊界重塑（Boundary Reset）訊號辨識工具 —— 老余裸K五階段狀態機。

兩個功能頁籤：
1. 全市場掃描：對觀察池全部標的跑一次掃描，列出正式觸發的標的、可查看圖表，
   並列出「潛在觀察名單」（尚未觸發但已進入型態關鍵階段）。
2. 單一標的診斷：輸入任意代碼，立即檢查目前停在五階段的哪一關。

部署到 Streamlit Community Cloud（streamlit.io）時，Main file path 設為 app.py 即可。

重要變更：pattern_detector.detect_boundary_shift() 現在永遠回傳一個 dict
（帶 status 欄位），不再回傳 None，所以這裡一律用 res["status"] 判斷，
不能再用 `if res:` 這種真假值判斷。
"""

import os
import sys
import tempfile

import pandas as pd
import streamlit as st

# 讓 app.py（repo 根目錄）能 import src/ 底下的模組
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from data_fetcher import (  # noqa: E402
    fetch_all_watchlist, WATCHLIST_MAPPING, download_with_retry, prepare_dataframe,
)
from pattern_detector import (  # noqa: E402
    detect_boundary_shift,
    STATUS_TRIGGERED, STATUS_WATCHING_RECLAIM, STATUS_WAITING_RETEST, STATUS_RR_REJECTED,
)
from historical_satisfaction import historical_satisfaction_score  # noqa: E402
from daily_refinement import refine_with_daily  # noqa: E402
from position_sizing import calc_position_size  # noqa: E402
from visualizer import plot_and_save, plot_daily_chart  # noqa: E402

CHART_DIR = os.path.join(tempfile.gettempdir(), "boundary_reset_charts")

_STATUS_LABELS = {
    STATUS_WATCHING_RECLAIM: "⏳ 等待強勢收復站回邊界",
    STATUS_WAITING_RETEST: "🎯 已收復，等待回踩滿足區",
    STATUS_RR_REJECTED: "⚠️ 已回踩滿足區，但風報比不足",
}
_WATCHLIST_STATUSES = set(_STATUS_LABELS.keys())

st.set_page_config(page_title="邊界重塑訊號掃描器", page_icon="📈", layout="wide")
st.title("📈 邊界重塑（Boundary Reset）訊號掃描器")
st.caption("台股0050核心＋中型100精選＋美股大型科技，老余裸K五階段狀態機辨識")

with st.sidebar:
    st.header("⚙️ 參數設定")
    risk_amount = st.number_input("單筆風險金額（新台幣）", min_value=1000, value=10000, step=1000)
    usd_rate = st.number_input("美元兌台幣參考匯率", min_value=1.0, value=32.0, step=0.5)
    period = st.selectbox("資料回看區間", ["1y", "2y", "3y"], index=1)
    only_lower_zone = st.checkbox("只顯示下緣型態（低於長期趨勢線）", value=False)
    only_good_zone = st.checkbox("只顯示打擊區品質良好的型態（排除過窄）", value=False)
    enable_daily_refinement = st.checkbox("啟用日K精算停損（週K定方向，日K定打擊區）", value=True)
    show_daily_chart = st.checkbox("顯示日K圖表（可選，需先啟用日K精算）", value=False)
    st.divider()
    st.caption("⚠️ 本工具僅供型態研究參考，非投資建議。")
    st.caption("全市場掃描約需 1-3 分鐘，視 Yahoo Finance 回應速度而定。")

tab_scan, tab_single = st.tabs(["🔍 全市場掃描", "🔎 單一標的診斷"])

# ============================================================
# Tab 1：全市場掃描
# ============================================================
with tab_scan:
    if st.button("🚀 開始掃描全市場", type="primary"):
        with st.spinner("下載資料中，請稍候..."):
            stock_data = fetch_all_watchlist(period=period, interval="1wk")

        loaded, total = len(stock_data), len(WATCHLIST_MAPPING)
        if loaded < total * 0.5:
            st.warning(f"⚠️ 僅成功載入 {loaded}/{total} 檔標的，疑似被 Yahoo Finance 限流，結果可能不完整")
        else:
            st.info(f"成功載入 {loaded}/{total} 檔標的")

        results = []
        watchlist = []
        progress = st.progress(0.0)
        for i, (ticker, (name, df)) in enumerate(stock_data.items()):
            res = detect_boundary_shift(df)
            status = res.get("status")

            if status in _WATCHLIST_STATUSES:
                watchlist.append({"ticker": ticker, "name": name, "status": status})

            if status == STATUS_TRIGGERED:
                if enable_daily_refinement:
                    try:
                        res = refine_with_daily(ticker, df, res)
                    except Exception:
                        res["daily_refined"] = False

                pos = calc_position_size(ticker, res["entry_price"], res["stop_loss"],
                                          risk_amount_twd=risk_amount, usd_twd_rate=usd_rate)
                try:
                    hist = historical_satisfaction_score(df)
                except Exception:
                    hist = {"total_patterns": 0, "satisfied_count": 0, "satisfaction_rate": None}
                results.append({"ticker": ticker, "name": name, "df": df, "res": res, "pos": pos, "hist": hist})

            progress.progress((i + 1) / max(loaded, 1))
        progress.empty()

        st.session_state["scan_results"] = results
        st.session_state["watchlist"] = watchlist

    results = st.session_state.get("scan_results")
    watchlist = st.session_state.get("watchlist", [])

    if results is None:
        st.info("按上方按鈕開始掃描。")
    else:
        display_results = results
        if only_lower_zone:
            display_results = [r for r in display_results if r["res"].get("zone_label") == "下緣"]
        if only_good_zone:
            display_results = [r for r in display_results if not r["res"].get("zone_too_tight")]

        applied_filters = []
        if only_lower_zone:
            applied_filters.append("下緣型態")
        if only_good_zone:
            applied_filters.append("打擊區品質良好")
        filter_note = f"，已篩選：{' + '.join(applied_filters)}" if applied_filters else ""

        if not results:
            st.warning("本次掃描全市場無正式觸發的標的。")
        elif not display_results:
            st.warning(f"本次掃描共 {len(results)} 檔觸發，但沒有標的同時符合篩選條件（{' + '.join(applied_filters)}）。")
        else:
            sorted_results = sorted(display_results, key=lambda r: r["res"]["rr_ratio"], reverse=True)
            st.success(f"共找到 {len(sorted_results)} 檔正式觸發的標的（依風報比排序）{filter_note}")

            table_rows = [
                {
                    "標的": r["name"],
                    "入場": round(r["res"]["entry_price"], 2),
                    "動態邊界": round(r["res"]["boundary"], 2),
                    "停損": round(r["res"]["stop_loss"], 2),
                    "停利": round(r["res"]["tp_adam"], 2),
                    "R/R": round(r["res"]["rr_ratio"], 2),
                    "建議部位": r["pos"]["unit_display"] if r["pos"] else "-",
                    "交割款估計": f"{r['pos']['currency']} {r['pos']['settlement_estimate']:,.0f}" if r["pos"] else "-",
                    "歷史滿足": f"{r['hist']['satisfied_count']}/{r['hist']['total_patterns']}",
                    "打擊區": "⚠️過窄" if r["res"].get("zone_too_tight") else "✅",
                    "停損來源": "日K精算" if r["res"].get("daily_refined") else "週K版本",
                    "趨勢位置": f"{r['res'].get('zone_label', '-')}（{r['res'].get('trend_deviation_pct', 0)*100:+.1f}%）",
                }
                for r in sorted_results
            ]

            st.caption("👆 點選下方表格的任一列，即可顯示對應的決策圖表")
            event = st.dataframe(
                pd.DataFrame(table_rows),
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
            )

            selected_rows = event["selection"]["rows"]
            st.divider()

            if not selected_rows:
                st.info("尚未選擇標的，請點選上方表格的某一列。")
            else:
                chosen = sorted_results[selected_rows[0]]
                st.subheader(f"📊 {chosen['name']} 決策圖表（週K）")
                try:
                    img_path = plot_and_save(chosen["df"], chosen["ticker"], chosen["name"], chosen["res"],
                                              output_dir=CHART_DIR)
                    st.image(img_path, use_container_width=True)
                except Exception as e:
                    st.error(f"圖表產生失敗（訊號本身仍有效）：{e}")

                if show_daily_chart:
                    if chosen["res"].get("daily_refined") and chosen["res"].get("daily_df") is not None:
                        st.subheader(f"🔍 {chosen['name']} 日K精算檢視")
                        try:
                            daily_img_path = plot_daily_chart(chosen["res"]["daily_df"], chosen["ticker"],
                                                               chosen["name"], chosen["res"], output_dir=CHART_DIR)
                            st.image(daily_img_path, use_container_width=True)
                        except Exception as e:
                            st.error(f"日K圖表產生失敗：{e}")
                    else:
                        st.caption("此標的沒有可用的日K精算資料（可能是日K下載失敗或未啟用日K精算），無法顯示日K圖表。")

        st.divider()
        st.subheader("🔭 潛在觀察名單（尚未觸發，但已進入型態關鍵階段）")
        if not watchlist:
            st.caption("本次掃描無標的進入觀察階段。")
        else:
            watch_table = [{"標的": w["name"], "目前階段": _STATUS_LABELS.get(w["status"], w["status"])}
                            for w in watchlist]
            st.dataframe(pd.DataFrame(watch_table), use_container_width=True, hide_index=True)

# ============================================================
# Tab 2：單一標的診斷
# ============================================================
with tab_single:
    ticker_input = st.text_input("輸入代碼（例如 2330.TW、AAPL、3131.TWO）", value="2330.TW").strip()

    if st.button("🔎 查詢", type="primary"):
        with st.spinner(f"下載 {ticker_input} 資料中..."):
            raw = download_with_retry([ticker_input], batch_size=1, period=period,
                                       interval="1wk", auto_adjust=True)

        if ticker_input not in raw:
            st.error("查無資料，請確認代碼格式是否正確（台股需加 .TW 或 .TWO）")
        else:
            df = prepare_dataframe(raw[ticker_input])
            if df is None:
                st.error("資料筆數不足（需至少 25 根週K棒），無法進行判斷")
            else:
                res = detect_boundary_shift(df)
                status = res.get("status")

                if status == STATUS_TRIGGERED:
                    if enable_daily_refinement:
                        try:
                            res = refine_with_daily(ticker_input, df, res)
                        except Exception:
                            res["daily_refined"] = False

                    st.success("✅ 五階段全部通過，符合邊界重塑回踩條件！")
                    pos = calc_position_size(ticker_input, res["entry_price"], res["stop_loss"],
                                              risk_amount_twd=risk_amount, usd_twd_rate=usd_rate)

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("進場", f"{res['entry_price']:.2f}")
                    c2.metric("動態邊界", f"{res['boundary']:.2f}")
                    c3.metric("停損", f"{res['stop_loss']:.2f}")
                    c4.metric("停利", f"{res['tp_adam']:.2f}")
                    st.metric("風報比 R/R", f"{res['rr_ratio']:.2f}")
                    if res.get("daily_refined"):
                        st.caption(f"📐 停損已套用日K精算（{res.get('daily_zone_start_date')} ~ {res.get('daily_zone_end_date')}，共{res.get('daily_zone_bar_count')}根日K）")
                    elif enable_daily_refinement:
                        st.caption(f"⚠️ 日K精算失敗，停損維持週K版本計算（原因: {res.get('daily_refine_reason', '未知')}）")
                    if res.get("zone_too_tight"):
                        st.warning("⚠️ 打擊區過窄（反彈高點才發生沒幾根K棒，回檔尚未止穩），停損已套用風險下限（2%），非打擊區實際低點")

                    zone_emoji = "🟢" if res.get("zone_label") == "下緣" else "🔴"
                    st.caption(f"{zone_emoji} 相對長期趨勢線：{res.get('zone_label')}（{res.get('trend_deviation_pct', 0)*100:+.1f}%，趨勢線價位約 {res.get('trend_price', 0):.2f}）")

                    try:
                        hist = historical_satisfaction_score(df)
                        rate_str = f"{hist['satisfaction_rate']*100:.0f}%" if hist["satisfaction_rate"] is not None else "無歷史樣本"
                        st.caption(f"📊 歷史翻亞當滿足紀錄：{hist['satisfied_count']}/{hist['total_patterns']}（滿足率 {rate_str}）")
                    except Exception:
                        pass

                    if pos:
                        st.write(f"💰 建議部位：**{pos['unit_display']}**（交割款估計 {pos['currency']} {pos['settlement_estimate']:,.0f}）")
                    else:
                        st.caption("目前風險金額不足以買進最小交易單位。")

                    try:
                        img_path = plot_and_save(df, ticker_input, ticker_input, res, output_dir=CHART_DIR)
                        st.image(img_path, use_container_width=True)
                    except Exception as e:
                        st.error(f"圖表產生失敗（訊號本身仍有效）：{e}")

                    if show_daily_chart:
                        if res.get("daily_refined") and res.get("daily_df") is not None:
                            st.subheader(f"🔍 {ticker_input} 日K精算檢視")
                            try:
                                daily_img_path = plot_daily_chart(res["daily_df"], ticker_input, ticker_input,
                                                                   res, output_dir=CHART_DIR)
                                st.image(daily_img_path, use_container_width=True)
                            except Exception as e:
                                st.error(f"日K圖表產生失敗：{e}")
                        else:
                            st.caption("此標的沒有可用的日K精算資料（可能是日K下載失敗或未啟用日K精算），無法顯示日K圖表。")
                elif status in _STATUS_LABELS:
                    st.info(f"尚未觸發進場。目前階段：{_STATUS_LABELS[status]}")
                    if res.get("reason"):
                        st.caption(f"🔍 診斷：{res['reason']}")
                    st.line_chart(df.set_index("DateStr")[["Close"]])
                else:
                    st.info("目前未偵測到符合條件的邊界重塑候選型態。")
                    if res.get("reason"):
                        st.caption(f"🔍 診斷：{res['reason']}")
                    st.line_chart(df.set_index("DateStr")[["Close"]])
