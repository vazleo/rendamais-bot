import logging

import requests

from renda_bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


class TelegramNotifier:
    def __init__(self, chat_id: int | None = None):
        self._chat_id = chat_id or TELEGRAM_CHAT_ID

    def send_text(self, msg: str) -> None:
        try:
            resp = requests.post(
                f"{_BASE}/sendMessage",
                json={"chat_id": self._chat_id, "text": msg},
                timeout=10,
            )
            resp.raise_for_status()
            logger.debug("telegram: mensagem enviada")
        except Exception as exc:
            logger.error("telegram send_text falhou: %s", exc)

    def send_photo(self, png_bytes: bytes, caption: str | None = None) -> None:
        try:
            data = {"chat_id": self._chat_id}
            if caption:
                data["caption"] = caption
            resp = requests.post(
                f"{_BASE}/sendPhoto",
                data=data,
                files={"photo": ("historico.png", png_bytes, "image/png")},
                timeout=30,
            )
            resp.raise_for_status()
            logger.debug("telegram: foto enviada")
        except Exception as exc:
            logger.error("telegram send_photo falhou: %s", exc)

    def send_document(self, data_bytes: bytes, filename: str, caption: str | None = None) -> None:
        try:
            data = {"chat_id": self._chat_id}
            if caption:
                data["caption"] = caption
            resp = requests.post(
                f"{_BASE}/sendDocument",
                data=data,
                files={"document": (filename, data_bytes, "text/csv")},
                timeout=30,
            )
            resp.raise_for_status()
            logger.debug("telegram: documento enviado")
        except Exception as exc:
            logger.error("telegram send_document falhou: %s", exc)


def get_updates(offset: int = 0, timeout: int = 30) -> list[dict]:
    try:
        resp = requests.get(
            f"{_BASE}/getUpdates",
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 5,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", [])
    except Exception as exc:
        logger.error("getUpdates falhou: %s", exc)
        return []


class BroadcastNotifier:
    """Envia para todos os chat_ids autorizados."""
    def __init__(self):
        from renda_bot.config import TELEGRAM_ALLOWED_IDS
        self._notifiers = [TelegramNotifier(chat_id=cid) for cid in TELEGRAM_ALLOWED_IDS]

    def send_text(self, msg: str) -> None:
        for n in self._notifiers:
            n.send_text(msg)

    def send_photo(self, png_bytes: bytes, caption: str | None = None) -> None:
        for n in self._notifiers:
            n.send_photo(png_bytes, caption)

    def send_document(self, data_bytes: bytes, filename: str, caption: str | None = None) -> None:
        for n in self._notifiers:
            n.send_document(data_bytes, filename, caption)
