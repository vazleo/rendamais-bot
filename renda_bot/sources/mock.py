from datetime import datetime, timezone
from renda_bot.models import RateReading, TituloRef


class MockSource:
    name = "mock"

    def __init__(self, taxa_compra: float = 7.10, taxa_resgate: float = 7.05):
        self._taxa_compra = taxa_compra
        self._taxa_resgate = taxa_resgate

    def get_rate(self, titulo: TituloRef) -> RateReading:
        from renda_bot.market import is_market_open
        return RateReading(
            titulo=titulo.apelido,
            taxa_compra=self._taxa_compra,
            taxa_resgate=self._taxa_resgate,
            pu_compra=1234.56,
            pu_resgate=1230.00,
            mercado_aberto=is_market_open(),
            timestamp_fonte=datetime.now(timezone.utc),
            fonte=self.name,
        )
