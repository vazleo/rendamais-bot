import logging
import time
from typing import Optional

from renda_bot.config import BACKOFF_BASE, BACKOFF_MAX, SOURCES_ORDER, STAGNATION_THRESHOLD
from renda_bot.models import RateReading, TituloRef
from renda_bot.sources.oficial import OfficialSource

logger = logging.getLogger(__name__)


def _build_sources() -> dict:
    sources = {}
    for name in SOURCES_ORDER:
        if name == "oficial":
            sources["oficial"] = OfficialSource()
    return sources


class SourceOrchestrator:
    def __init__(self):
        self._sources = _build_sources()
        self._backoff: dict[str, float] = {}
        self._last_ts: dict[str, Optional[str]] = {}
        self._stagnation_count: dict[str, int] = {}
        self._consecutive_failures: int = 0
        self._last_ok_source: Optional[str] = None

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def last_ok_source(self) -> Optional[str]:
        return self._last_ok_source

    def fetch(self, titulo: TituloRef) -> Optional[RateReading]:
        for name in SOURCES_ORDER:
            source = self._sources.get(name)
            if source is None:
                continue

            backoff_until = self._backoff.get(name, 0)
            if time.monotonic() < backoff_until:
                logger.debug("%s em backoff, pulando", name)
                continue

            try:
                reading = source.get_rate(titulo)
            except Exception as exc:
                logger.warning("%s falhou: %s", name, exc)
                self._apply_backoff(name)
                continue

            if self._is_stagnated(name, reading):
                logger.warning("%s dado estagnado, tentando próxima fonte", name)
                self._apply_backoff(name)
                continue

            self._reset_backoff(name)
            self._update_stagnation(name, reading)
            self._consecutive_failures = 0
            self._last_ok_source = name
            return reading

        self._consecutive_failures += 1
        logger.error("todas as fontes falharam (consecutivo: %d)", self._consecutive_failures)
        return None

    def _is_stagnated(self, name: str, reading: RateReading) -> bool:
        ts_key = reading.timestamp_fonte.isoformat()
        last = self._last_ts.get(name)
        if last is None:
            return False
        if ts_key == last:
            self._stagnation_count[name] = self._stagnation_count.get(name, 0) + 1
            count = self._stagnation_count[name]
            if count >= STAGNATION_THRESHOLD:
                logger.warning("%s timestamp estagnado há %d ciclos", name, count)
                return True
        else:
            self._stagnation_count[name] = 0
        return False

    def _update_stagnation(self, name: str, reading: RateReading) -> None:
        self._last_ts[name] = reading.timestamp_fonte.isoformat()
        self._stagnation_count[name] = 0

    def _apply_backoff(self, name: str) -> None:
        current = self._backoff.get(name, 0)
        elapsed = time.monotonic() - current
        delay = min(BACKOFF_BASE ** max(1, self._stagnation_count.get(name, 1)), BACKOFF_MAX)
        self._backoff[name] = time.monotonic() + delay
        logger.debug("%s backoff de %.0fs", name, delay)

    def _reset_backoff(self, name: str) -> None:
        self._backoff.pop(name, None)
