from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TituloRef:
    apelido: str
    tipo: str
    ano_vencimento: int


@dataclass
class RateReading:
    titulo: str
    taxa_compra: float
    taxa_resgate: Optional[float]
    pu_compra: Optional[float]
    pu_resgate: Optional[float]
    mercado_aberto: bool
    timestamp_fonte: datetime
    fonte: str
