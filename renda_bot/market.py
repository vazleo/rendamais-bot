import logging
from datetime import date, datetime, time

import holidays
import pytz

from renda_bot.config import (
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN,
    MARKET_OPEN_HOUR, MARKET_OPEN_MIN,
)

logger = logging.getLogger(__name__)

TZ_BR = pytz.timezone("America/Sao_Paulo")
_b3_holidays = holidays.Brazil(state="SP")

MARKET_OPEN = time(MARKET_OPEN_HOUR, MARKET_OPEN_MIN)
MARKET_CLOSE = time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MIN)


def now_br() -> datetime:
    return datetime.now(TZ_BR)


def is_market_open() -> bool:
    now = now_br()
    if now.weekday() >= 5:
        return False
    if now.date() in _b3_holidays:
        logger.debug("feriado hoje: %s", now.date())
        return False
    t = now.time()
    return MARKET_OPEN <= t < MARKET_CLOSE


def is_market_closing(now: datetime | None = None) -> bool:
    """Returns True in the window [close-5min, close) — used for daily summary."""
    if now is None:
        now = now_br()
    t = now.time()
    from datetime import timedelta
    close = datetime.combine(now.date(), MARKET_CLOSE, tzinfo=TZ_BR)
    window_start = (close - timedelta(minutes=5)).time()
    return window_start <= t < MARKET_CLOSE


def market_open_today() -> bool:
    """Returns True if the market was/is open at any point today."""
    today = now_br().date()
    if datetime.now(TZ_BR).weekday() >= 5:
        return False
    return today not in _b3_holidays
