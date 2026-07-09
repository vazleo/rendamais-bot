import logging
import time
from typing import Optional

from renda_bot.config import MAX_FALHAS_CONSECUTIVAS
from renda_bot.notifier.base import Notifier

logger = logging.getLogger(__name__)

_ERROR_COOLDOWN = 3600
_last_error_alert: float = 0
_daily_summary_sent_date: Optional[str] = None


def check_dead_man(consecutive_failures: int, notifier: Notifier) -> None:
    global _last_error_alert
    if consecutive_failures < MAX_FALHAS_CONSECUTIVAS:
        return
    now = time.monotonic()
    if now - _last_error_alert < _ERROR_COOLDOWN:
        return
    _last_error_alert = now
    msg = (
        f"ALERTA: bot cego!\n"
        f"Todas as fontes falharam por {consecutive_failures} ciclos consecutivos.\n"
        f"Verifique a conectividade e os logs."
    )
    notifier.send_text(msg)
    logger.critical("dead-man switch acionado: %d falhas consecutivas", consecutive_failures)


def should_send_daily_summary(titulo: str) -> bool:
    from renda_bot.market import is_market_closing, market_open_today
    global _daily_summary_sent_date
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _daily_summary_sent_date == today:
        return False
    if not market_open_today():
        return False
    return is_market_closing()


def mark_daily_summary_sent() -> None:
    global _daily_summary_sent_date
    from datetime import datetime, timezone
    _daily_summary_sent_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
