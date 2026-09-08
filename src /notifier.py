"""
notifier.py
Telegram / Discord Webhook 推播模組（雙幣別 / 動態邊界版本）。
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
        print(f"❌ Telegram 推播失敗（{name}）: {e}")
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
