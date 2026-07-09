import os
from dotenv import load_dotenv
from renda_bot.models import TituloRef

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID: int = int(os.environ["TELEGRAM_CHAT_ID"])
TELEGRAM_ALLOWED_IDS: set[int] = {
    int(os.environ["TELEGRAM_CHAT_ID"]),
    1291062384,
    817406374,
    8160137060, # Nicolas
}
SOURCES_ORDER: list[str] = ["oficial"]

TITULOS_MONITORADOS: list[TituloRef] = [
    TituloRef(apelido="renda_mais_2065", tipo="Renda+", ano_vencimento=2065),
]

POLL_INTERVAL_SEG: int = 45
MAX_FALHAS_CONSECUTIVAS: int = 5
RETENCAO_DIAS: int = 30
HISTERESE_BPS: float = 2.0

MARKET_OPEN_HOUR: int = 9
MARKET_OPEN_MIN: int = 30
MARKET_CLOSE_HOUR: int = 18
MARKET_CLOSE_MIN: int = 0

DB_PATH: str = "bot.db"

USER_AGENT: str = "rendamais-bot/0.1"

REQUEST_TIMEOUT: int = 10
BACKOFF_BASE: float = 2.0
BACKOFF_MAX: float = 60.0

STAGNATION_THRESHOLD: int = 3
