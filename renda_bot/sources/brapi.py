import logging
from datetime import datetime, timezone

import requests

from renda_bot.config import BRAPI_TOKEN, REQUEST_TIMEOUT, USER_AGENT
from renda_bot.models import RateReading, TituloRef

logger = logging.getLogger(__name__)

URL = "https://brapi.dev/api/v2/treasury"

HEADERS = {"User-Agent": USER_AGENT}


class BrapiSource:
    name = "brapi"

    def get_rate(self, titulo: TituloRef) -> RateReading:
        if not BRAPI_TOKEN:
            raise RuntimeError("BRAPI_TOKEN não configurado")

        params = {"token": BRAPI_TOKEN}
        resp = requests.get(URL, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        data = resp.json()
        logger.debug("brapi raw keys: %s", list(data.keys()))

        if data.get("error"):
            raise RuntimeError(f"brapi error: {data.get('message')}")

        bonds = data.get("treasuries", [])
        logger.debug("brapi: %d treasuries found", len(bonds))

        bond = _find_titulo(bonds, titulo)
        if bond is None:
            raise ValueError(f"Título {titulo.apelido} não encontrado na brapi")

        logger.debug("brapi matched: %s", bond)

        # brapi field names to confirm with real payload:
        # name, type, rate, price, date, isOpen
        ts_str = bond.get("date", "")
        timestamp = _parse_ts(ts_str)

        return RateReading(
            titulo=titulo.apelido,
            taxa_compra=float(bond["sellingRate"]),
            taxa_resgate=float(bond["buyingRate"]) if bond.get("buyingRate") is not None else None,
            pu_compra=float(bond["sellingPrice"]) if bond.get("sellingPrice") is not None else None,
            pu_resgate=float(bond["buyingPrice"]) if bond.get("buyingPrice") is not None else None,
            mercado_aberto=bool(bond.get("isOpen", False)),
            timestamp_fonte=timestamp,
            fonte=self.name,
        )


def _find_titulo(bonds: list, titulo: TituloRef) -> dict | None:
    year = str(titulo.ano_vencimento)
    tipo = titulo.tipo.lower()
    for bond in bonds:
        nm = bond.get("name", "").lower()
        if tipo.replace("+", "").replace(" ", "") in nm.replace("+", "").replace(" ", "") and year in nm:
            return bond
    return None


def _parse_ts(ts_str: str) -> datetime:
    if not ts_str:
        return datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.warning("brapi: timestamp format not recognized: %s", ts_str)
    return datetime.now(timezone.utc)
