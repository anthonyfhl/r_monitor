"""Text notifications only. HTML file reports are retired."""
import logging
from src import http_client
from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REQUEST_TIMEOUT
from src.health import record_fetch_result

logger = logging.getLogger(__name__)


def send_message(text, parse_mode="HTML"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram delivery needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        record_fetch_result("telegram",False,"Telegram credential missing","已檢查通知設定；需要在 .env 補回 Telegram bot token 及收件人編號。")
        return False
    if len(text) > 4096:
        raise ValueError("Telegram message exceeds 4096 characters; shorten it without dropping warnings")
    try:
        payload={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}
        if parse_mode:
            payload["parse_mode"]=parse_mode
        response = http_client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if not response.json().get("ok"):
            raise RuntimeError("Telegram did not acknowledge delivery")
        record_fetch_result("telegram",True)
        return True
    except Exception as exc:
        from src.repair import repair_source
        outcome=repair_source("telegram",exc)
        record_fetch_result("telegram",False,str(exc),outcome)
        logger.error("Telegram delivery failed: %s; repair outcome: %s",exc,outcome)
        return False
