"""Send HTML report via Telegram Bot API."""

import logging
import tempfile
from pathlib import Path

import requests

from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

TG_API = "https://api.telegram.org/bot{token}"


def _api_url(method: str) -> str:
    return f"{TG_API.format(token=TELEGRAM_BOT_TOKEN)}/{method}"


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send a text message via Telegram.

    Telegram message limit is 4096 chars. If exceeded, splits into chunks.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return False

    # Telegram limit
    max_len = 4096
    chunks = _split_html(text, max_len) if len(text) > max_len else [text]

    success = True
    for chunk in chunks:
        try:
            resp = requests.post(
                _api_url("sendMessage"),
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            result = resp.json()
            if not result.get("ok"):
                logger.error(f"Telegram API error: {result}")
                success = False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            success = False

    return success


def send_document(file_path: str | Path, caption: str = "") -> bool:
    """Send a file as a Telegram document."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram credentials not configured")
        return False

    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                _api_url("sendDocument"),
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "caption": caption[:1024],  # Telegram caption limit
                    "parse_mode": "HTML",
                },
                files={"document": (Path(file_path).name, f)},
                timeout=60,
            )
        resp.raise_for_status()
        result = resp.json()
        if not result.get("ok"):
            logger.error(f"Telegram API error: {result}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram document: {e}")
        return False


def send_report(html_content: str, summary: str = "") -> bool:
    """Send the HTML report via Telegram.

    Strategy:
    1. Send a brief text summary as a message
    2. Send the full HTML report as a file attachment
    """
    if not summary:
        summary = "📊 <b>Daily Interest Rate Report</b>\n\nFull HTML report attached below."

    # Send summary message
    msg_ok = send_message(summary)

    # Save HTML to temp file and send as document
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", prefix="rate_report_", delete=False, encoding="utf-8"
        ) as f:
            f.write(html_content)
            tmp_path = f.name

        doc_ok = send_document(tmp_path, caption="Interest Rate Monitor Report")

        # Cleanup
        Path(tmp_path).unlink(missing_ok=True)

        return msg_ok and doc_ok
    except Exception as e:
        logger.error(f"Failed to send HTML report: {e}")
        return False


def _split_html(text: str, max_len: int) -> list[str]:
    """Split text into chunks respecting Telegram's limit.

    Simple split on newlines; not perfect for complex HTML but workable for summaries.
    """
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current)
            current = line[:max_len]
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks


def build_summary(data: dict) -> str:
    """Build a brief text summary for the Telegram message."""
    lines = ["📊 <b>Interest Rate Monitor</b>", ""]

    # HIBOR
    hibor = data.get("hibor", {})
    if hibor:
        h1m = hibor.get("1 Month")
        h3m = hibor.get("3 Months")
        if h1m is not None:
            lines.append(f"🇭🇰 HIBOR 1M: <b>{h1m:.4f}%</b>")
        if h3m is not None:
            lines.append(f"🇭🇰 HIBOR 3M: <b>{h3m:.4f}%</b>")
        if h1m is not None:
            wpl = h1m + 1.2
            lines.append(f"🏠 HSBC WPL (&lt;1m): <b>{wpl:.4f}%</b>")

    # Prime rates
    for pr in data.get("prime_rates", []):
        if pr.get("rate") is not None:
            lines.append(f"🏦 {pr['bank']} Prime: <b>{pr['rate']:.3f}%</b>")

    lines.append("")

    # Fed Funds
    fed = data.get("fed_funds", {})
    if fed.get("target_upper") is not None:
        lines.append(f"🇺🇸 Fed Target: <b>{fed.get('target_lower', 0):.2f}%-{fed['target_upper']:.2f}%</b>")
    if fed.get("effective") is not None:
        lines.append(f"🇺🇸 Fed Effective: <b>{fed['effective']:.2f}%</b>")

    # SOFR
    sofr = data.get("sofr", {})
    if sofr.get("rate") is not None:
        lines.append(f"🇺🇸 SOFR: <b>{sofr['rate']:.4f}%</b>")

    # IB rates
    ib = data.get("ib_rates", {})
    for ccy in ["HKD", "USD"]:
        r = ib.get(ccy)
        if r and r.get("rate") is not None:
            lines.append(f"💹 IB {ccy} Margin: <b>{r['rate']:.2f}%</b>")

    lines.append("")
    lines.append("<i>Full HTML report attached.</i>")

    return "\n".join(lines)
