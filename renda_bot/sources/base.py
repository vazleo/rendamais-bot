from typing import Protocol
from renda_bot.models import RateReading, TituloRef


class RateSource(Protocol):
    name: str

    def get_rate(self, titulo: TituloRef) -> RateReading: ...
