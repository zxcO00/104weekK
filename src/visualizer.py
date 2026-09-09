"""
visualizer.py
繪製「極簡 4 橫線 + 滿足區」決策圖表（含中文字型註冊），輸出 PNG。
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

_FONT_READY = False


_VALID_FONT_MAGIC = (b"\x00\x01\x00\x00", b"true", b"ttcf", b"OTTO")


def _is_valid_font_file(path, min_size_bytes=10_000):
    """
    檢查檔案是否為真正的字型檔（而不是 Google Drive 被限流時回傳的 HTML 警告頁面）。
    用檔案魔數（magic bytes）判斷，比單看副檔名可靠。
    """
    try:
        if os.path.getsize(path) < min_size_bytes:
            return False
        with open(path, "rb") as f:
            header = f.read(4)
        return header in _VALID_FONT_MAGIC
    except Exception:
        return False


def setup_chinese_font(font_dir="fonts"):
    """
    下載並註冊台北思源黑體，用於圖表中文標籤。
    找不到網路、下載失敗，或下載到的檔案不是有效字型（例如 Google Drive
    在雲端 CI 環境回傳的病毒掃描警告頁面）時，一律靜默退回 DejaVu Sans
    （英數字仍可正常顯示，不會讓繪圖流程整個炸掉）。
    只會執行一次（模組層級快取），重複呼叫不會重下載。
    """
    global _FONT_READY
    if _FONT_READY:
        return

    os.makedirs(font_dir, exist_ok=True)
    font_path = os.path.join(font_dir, "TaipeiSansTCBeta-Regular.ttf")

    if os.path.exists(font_path) and not _is_valid_font_file(font_path):
        print("⚠️ 快取的字型檔無效（可能是先前下載失敗留下的殘檔），刪除後重新下載")
        try:
            os.remove(font_path)
        except OSError:
            pass

    if not os.path.exists(font_path):
        try:
            import requests
            print(">> 正在下載台北思源黑體...")
            url = "https://drive.google.com/uc?id=1eGAsTN1HBpJAkeVM57_C7ccp7hbgSz3_&export=download"
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            with open(font_path, "wb") as f:
                f.write(resp.content)
        except Exception as e:
            print(f"⚠️ 中文字型下載失敗，圖表中文可能無法顯示：{e}")

    font_usable = os.path.exists(font_path) and _is_valid_font_file(font_path)
    if os.path.exists(font_path) and not font_usable:
        print("⚠️ 下載到的字型檔無效（很可能是 Google Drive 回傳了警告頁面而非字型檔），改用預設英文字型")

    matplotlib.rcdefaults()
    if font_usable:
        try:
            matplotlib.font_manager.fontManager.addfont(font_path)
        except Exception as e:
            print(f"⚠️ 字型註冊失敗：{e}")
            font_usable = False

    font_list = ["Taipei Sans TC Beta", "DejaVu Sans", "Arial"] if font_usable else ["DejaVu Sans", "Arial"]
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = font_list
    plt.rcParams["axes.unicode_minus"] = False

    _FONT_READY = True


def plot_and_save(df, ticker, name, res, output_dir="output"):
    setup_chinese_font()

    os.makedirs(output_dir, exist_ok=True)
    clean_code = ticker.replace(".TW", "").replace(".TWO", "")
    is_us = not (ticker.endswith(".TW") or ticker.endswith(".TWO"))
    prefix = "[美股-週K]" if is_us else "[台股-週K]"

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2] if len(df) >= 2 else last_row

    cur_o = float(last_row["Open"])
    cur_h = float(last_row["High"])
    cur_l = float(last_row["Low"])
    cur_c = float(last_row["Close"])
    prev_c = float(prev_row["Close"])

    change = cur_c - prev_c
    change_pct = (change / prev_c) * 100 if prev_c != 0 else 0.0
    sign = "+" if change > 0 else ""
    title_color = "#FF3B30" if change > 0 else ("#00F5FF" if change < 0 else "#FFFFFF")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6.8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    fig.patch.set_facecolor("#131722")
    ax1.set_facecolor("#131722")
    ax2.set_facecolor("#131722")

    x_indices = np.arange(len(df))
    width = 0.55
    up = (df["Close"] >= df["Open"]).values
    down = (df["Close"] < df["Open"]).values

    # 台股慣例：紅漲綠(青)跌
    ax1.vlines(x_indices[up], df.loc[up, "Low"], df.loc[up, "High"], color="#FF3B30", linewidth=1.2)
    ax1.bar(x_indices[up], df.loc[up, "Close"] - df.loc[up, "Open"], width,
            bottom=df.loc[up, "Open"], color="#FF3B30", edgecolor="#FF3B30")
    ax1.vlines(x_indices[down], df.loc[down, "Low"], df.loc[down, "High"], color="#00F5FF", linewidth=1.2)
    ax1.bar(x_indices[down], df.loc[down, "Open"] - df.loc[down, "Close"], width,
            bottom=df.loc[down, "Close"], color="#00F5FF", edgecolor="#00F5FF")

    # 打擊區（黃框）—— 包覆最新回踩K棒的實際密集重疊區，而非固定百分比帶
    last_x = len(df) - 1
    if "strike_zone_start_idx" in res and "strike_zone_high" in res and "strike_zone_low" in res:
        zone_start_x = res["strike_zone_start_idx"]
        zone_end_x = last_x
        box_x = zone_start_x - 0.4
        box_w = (zone_end_x - zone_start_x) + 0.8
        box_bottom = res["strike_zone_low"]
        box_h = res["strike_zone_high"] - res["strike_zone_low"]
        zone_label = "打擊區"
    else:
        # 舊版相容：沒有打擊區資料時，退回滿足區（動態邊界±緩衝）畫法
        box_x = last_x - 0.6
        box_w = 1.2
        box_bottom = res["box_bottom"]
        box_h = res["box_top"] - res["box_bottom"]
        zone_label = "滿足區"

    rect = patches.Rectangle(
        (box_x, box_bottom), box_w, max(box_h, 1e-6),
        linewidth=2, edgecolor="#FFD700", facecolor="#FFD700", alpha=0.18,
        label=zone_label,
    )
    ax1.add_patch(rect)

    # 四條核心決策線
    ax1.axhline(y=res["tp_adam"], color="#00FF7F", linestyle="-", linewidth=2.0,
                label=f"目標停利 ({res['tp_adam']:.2f})")
    ax1.axhline(y=res["entry_price"], color="#00E5FF", linestyle="-.", linewidth=2.0,
                label=f"進場訊號 ({res['entry_price']:.2f})")
    ax1.axhline(y=res["boundary"], color="#FFD700", linestyle="-", linewidth=2.0,
                label=f"動態邊界 ({res['boundary']:.2f})")
    ax1.axhline(y=res["stop_loss"], color="#FF3B30", linestyle="--", linewidth=1.8,
                label=f"防守停損 ({res['stop_loss']:.2f})")

    max_p = max(float(df["High"].max()), res["tp_adam"])
    min_p = min(float(df["Low"].min()), res["stop_loss"])
    p_range = max_p - min_p
    ax1.set_ylim(min_p - p_range * 0.18, max_p + p_range * 0.18)

    step = max(len(df) // 8, 1)
    ax2.set_xticks(x_indices[::step])
    ax2.set_xticklabels(df["DateStr"].iloc[::step], rotation=15, ha="right", color="white", fontsize=9)

    main_title = f"{prefix} {name}  {cur_c:.2f}  {sign}{change:.2f} ({sign}{change_pct:.2f}%)"
    sub_title = f"開: {cur_o:.2f} | 高: {cur_h:.2f} | 低: {cur_l:.2f} | 收: {cur_c:.2f} | 週成交量: {int(last_row['Volume']):,}"

    ax1.set_title(f"{main_title}\n{sub_title}", color=title_color, fontsize=12, fontweight="bold", loc="left", pad=10)
    ax1.set_ylabel("價格", color="white", fontsize=11)
    ax1.tick_params(colors="white")
    ax1.grid(True, color="#2A2E39", linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", facecolor="#1E222D", edgecolor="none", labelcolor="white", fontsize=9)

    ax2.bar(x_indices[up], df.loc[up, "Volume"], width, color="#FF3B30", alpha=0.6)
    ax2.bar(x_indices[down], df.loc[down, "Volume"], width, color="#00F5FF", alpha=0.6)
    ax2.plot(x_indices, df["Vol_MA"], color="yellow", linestyle=":", label="10 週均量")
    ax2.set_ylabel("成交量", color="white", fontsize=10)
    ax2.tick_params(colors="white")
    ax2.grid(True, color="#2A2E39", linestyle=":", alpha=0.6)
    ax2.legend(loc="upper left", facecolor="#1E222D", edgecolor="none", labelcolor="white", fontsize=8.5)

    plt.tight_layout()
    file_path = os.path.join(output_dir, f"{clean_code}_boundary_reset.png")
    plt.savefig(file_path, dpi=120, facecolor="#131722")
    plt.close(fig)
    return file_path
