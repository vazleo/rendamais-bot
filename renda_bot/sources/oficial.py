import logging
import re
from datetime import datetime, timezone
from typing import Optional

import pytz

_SP_TZ = pytz.timezone("America/Sao_Paulo")

import requests

from renda_bot.config import REQUEST_TIMEOUT, USER_AGENT
from renda_bot.models import RateReading, TituloRef

logger = logging.getLogger(__name__)

URL = "https://www.tesourodireto.com.br/o/rentabilidade/investir"

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
    "Referer": "https://www.tesourodireto.com.br/produtos/dados-sobre-titulos/rendimento-dos-titulos",
}


class OfficialSource:
    name = "oficial"

    def get_rate(self, titulo: TituloRef) -> RateReading:
        resp = requests.get(URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        data = resp.json()
        logger.debug("oficial raw keys: %s", list(data.keys()))

        # bonds vem em TesouroLegado e Tesouro24x7
        all_bonds = data.get("TesouroLegado", []) + data.get("Tesouro24x7", [])
        logger.debug("oficial: %d bonds no total", len(all_bonds))

        bond = _find_titulo(all_bonds, titulo)
        if bond is None:
            raise ValueError(f"Título {titulo.apelido} não encontrado na fonte oficial")

        logger.debug("matched bond: %s", bond.get("treasuryBondName"))

        taxa_compra = _parse_rate(bond.get("investmentProfitabilityIndexerName", ""))
        taxa_resgate = _parse_rate(bond.get("redemptionProfitabilityFeeIndexerName", ""))

        if taxa_compra is None:
            raise ValueError(f"Não foi possível parsear taxa de compra: {bond.get('investmentProfitabilityIndexerName')}")

        pu_compra = bond.get("unitaryInvestmentValue")
        pu_resgate = bond.get("unitaryRedemptionValue")

        # Mercado aberto: PU de compra > 0 e título disponível
        mercado_aberto = bool(pu_compra and pu_compra > 0)

        ts_str = bond.get("lastMarketPricingDate", "")
        timestamp = _parse_ts(ts_str)

        return RateReading(
            titulo=titulo.apelido,
            taxa_compra=taxa_compra,
            taxa_resgate=taxa_resgate,
            pu_compra=float(pu_compra) if pu_compra is not None else None,
            pu_resgate=float(pu_resgate) if pu_resgate is not None else None,
            mercado_aberto=mercado_aberto,
            timestamp_fonte=timestamp,
            fonte=self.name,
        )


def _find_titulo(bonds: list, titulo: TituloRef) -> Optional[dict]:
    year = str(titulo.ano_vencimento)
    tipo = titulo.tipo.lower().replace("+", "").strip()
    for bond in bonds:
        nm = bond.get("treasuryBondName", "")
        nm_lower = nm.lower()
        if year in nm and tipo in nm_lower.replace("+", "").replace(" ", ""):
            return bond
    return None


def _parse_rate(rate_str: str) -> Optional[float]:
    """Extrai o componente numérico da taxa. Ex: 'IPCA + 7,04%' -> 7.04, '14,44%' -> 14.44"""
    if not rate_str:
        return None
    m = re.search(r'([\d]+[,\.][\d]+)\s*%', rate_str)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _parse_ts(ts_str: str) -> datetime:
    """API retorna horário em BRT sem offset — localiza em SP antes de converter pra UTC."""
    if not ts_str:
        return datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(ts_str, fmt)
            return _SP_TZ.localize(naive).astimezone(timezone.utc)
        except ValueError:
            continue
    logger.warning("oficial: timestamp não reconhecido: %s", ts_str)
    return datetime.now(timezone.utc)
