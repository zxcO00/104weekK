"""
notifier.py
Telegram / Discord Webhook 推播模組（雙幣別 / 動態邊界版本，含純文字備援）。
"""

import os
import requests


def _build_caption(name, res, pos, is_us, markdown=True):
    prefix = "[美股-週K]" if is_us else "[台股-週K]"
    bold = "*" if markdown else "**"
    code = "`" if markdown else "`"

    lines = [
        f"{bold}{prefix} {name}{bold} 觸發邊界重塑訊號（滿足區回踩）",
        "",
        f"進場: {code}{res['entry_price']:.2f}{code}",
        f"動態邊界: {code}{res['boundary']:.2f}{code}",
        f"停損: {code}{res['stop_loss']:.2f}{code}",
        f"停利: {code}{res['tp_adam']:.2f}{code}",
        f"風報比: {code}{res['rr_ratio']:.2f}{code}",
    ]
    if pos:
        lines.append(
            f"建議部位: {code}{pos['unit_display']}{code} "
            f"({pos['currency']} {pos['settlement_estimate']:,.0f})"
        )
    return "\n".join(lines)


def send_telegram_alert(name, res, img_path, pos=None, is_us=False):
    """帶圖片的完整推播"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("⚠️ 未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，跳過 Telegram 推播")
        return False

    caption = _build_caption(name, res, pos, is_us, markdown=True)
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        with open(img_path, "rb") as photo:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": photo},
                timeout=15,
            )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Telegram 圖片推播失敗（{name}）: {e}")
        return False


def send_telegram_text(name, res, pos=None, is_us=False):
    """
    純文字備援推播（繪圖失敗時使用）——確保訊號本身不會因為圖表產生失敗而完全沒有通知。
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return False

    text = "⚠️（本次圖表產生失敗，僅文字通知）\n\n" + _build_caption(name, res, pos, is_us, markdown=True)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Telegram 文字推播失敗（{name}）: {e}")
        return False


def send_discord_alert(name, res, img_path, pos=None, is_us=False):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("⚠️ 未設定 DISCORD_WEBHOOK_URL，跳過 Discord 推播")
        return False

    content = _build_caption(name, res, pos, is_us, markdown=False)
    try:
        with open(img_path, "rb") as f:
            resp = requests.post(
                webhook_url,
                data={"content": content},
                files={"file": (os.path.basename(img_path), f, "image/png")},
                timeout=15,
            )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Discord 推播失敗（{name}）: {e}")
        return False


def send_telegram_photo(img_path, caption=""):
    """
    通用圖片推播（不依賴 res 的下單四要素）——用於日K精算檢視圖這種附加圖表，
    只需要圖片本身跟一句說明文字。
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        with open(img_path, "rb") as photo:
            resp = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"photo": photo},
                timeout=15,
            )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Telegram 圖片推播失敗: {e}")
        return False


def send_failure_notice(error_message):
    """掃描流程整體失敗時的告警"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(
            url,
            data={"chat_id": chat_id, "text": f"⚠️ 掃描器執行失敗:\n{error_message}"},
            timeout=10,
        )
        return True
    except Exception:
        return False


def send_data_warning(loaded_count, total_count, threshold_pct=0.5):
    """
    當成功載入的標的數量遠低於觀察池總數時發出告警——
    通常代表 yfinance 在這次執行環境被限流，掃描結果不可信。
    """
    if total_count == 0:
        return False
    ratio = loaded_count / total_count
    if ratio >= threshold_pct:
        return False

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print(f"⚠️ 資料載入率過低（{loaded_count}/{total_count}），疑似被 Yahoo Finance 限流")
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        text = (
            f"⚠️ 本次掃描僅成功載入 {loaded_count}/{total_count} 檔標的資料，"
            f"疑似 yfinance 在此執行環境被限流，本次掃描結果可能不完整。"
        )
        requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
        return True
    except Exception:
        return False
