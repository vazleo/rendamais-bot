import logging
from datetime import datetime, timezone
from typing import Optional

from renda_bot.config import HISTERESE_BPS
from renda_bot.models import RateReading
from renda_bot.notifier.base import Notifier
from renda_bot import storage

logger = logging.getLogger(__name__)


def format_reading(reading: RateReading, taxa_anterior: Optional[float] = None) -> str:
    ts_br = reading.timestamp_fonte.astimezone(
        __import__("pytz").timezone("America/Sao_Paulo")
    ).strftime("%d/%m/%Y %H:%M:%S")

    lines = [
        f"Tesouro {reading.titulo}",
        f"Mercado: {'Aberto' if reading.mercado_aberto else 'Fechado'}",
        f"Taxa compra: {reading.taxa_compra:.2f}% a.a.",
    ]

    if taxa_anterior is not None:
        delta = reading.taxa_compra - taxa_anterior
        delta_bps = delta * 100
        delta_pct = (delta / taxa_anterior) * 100 if taxa_anterior else 0
        sinal = "+" if delta >= 0 else ""
        lines.append(f"Variacao: {taxa_anterior:.2f}% -> {reading.taxa_compra:.2f}% ({sinal}{delta_bps:.1f} bps, {sinal}{delta_pct:.2f}%)")

    if reading.taxa_resgate is not None:
        lines.append(f"Taxa resgate: {reading.taxa_resgate:.2f}% a.a.")

    if reading.pu_compra is not None:
        lines.append(f"PU compra: R$ {reading.pu_compra:.2f}")

    if reading.pu_resgate is not None:
        lines.append(f"PU resgate: R$ {reading.pu_resgate:.2f}")

    lines.append(f"Fonte: {reading.fonte} | {ts_br}")

    return "\n".join(lines)


def _get_modo() -> str:
    return storage.get_config("modo", "delta")


def _is_pausado() -> bool:
    return storage.get_config("pausado", "0") == "1"


def _in_silencio() -> bool:
    silencio = storage.get_config("silencio", "")
    if not silencio:
        return False
    try:
        inicio_str, fim_str = silencio.split("-")
        from datetime import time
        import pytz
        now = datetime.now(pytz.timezone("America/Sao_Paulo")).time()
        h_i, m_i = map(int, inicio_str.split(":"))
        h_f, m_f = map(int, fim_str.split(":"))
        inicio = time(h_i, m_i)
        fim = time(h_f, m_f)
        if inicio <= fim:
            return inicio <= now < fim
        return now >= inicio or now < fim
    except Exception:
        return False


def check_and_alert(reading: RateReading, notifier: Notifier) -> None:
    if _is_pausado() or _in_silencio():
        return

    modo = _get_modo()
    titulo = reading.titulo

    state = storage.get_alert_state(titulo)
    ultima_taxa = state.get("ultima_taxa_alertada")

    if modo == "sempre":
        _alert_sempre(reading, ultima_taxa, notifier)
    elif modo == "threshold":
        _alert_threshold(reading, ultima_taxa, state, notifier)
    elif modo == "delta":
        _alert_delta(reading, ultima_taxa, notifier)


def _alert_sempre(reading: RateReading, ultima_taxa: Optional[float], notifier: Notifier) -> None:
    if ultima_taxa is None or reading.taxa_compra != ultima_taxa:
        msg = format_reading(reading, ultima_taxa)
        notifier.send_text(msg)
        storage.update_alert_state(reading.titulo, reading.taxa_compra, armado=1)


def _alert_threshold(
    reading: RateReading,
    ultima_taxa: Optional[float],
    state: dict,
    notifier: Notifier,
) -> None:
    alvo = float(storage.get_config("alvo", "7.00"))
    direcao = storage.get_config("alvo_direcao", "acima")
    armado = bool(state.get("armado", 1))
    taxa = reading.taxa_compra
    histerese = HISTERESE_BPS / 100

    if direcao == "acima":
        cruzou = taxa >= alvo
        voltou = taxa < (alvo - histerese)
    else:
        cruzou = taxa <= alvo
        voltou = taxa > (alvo + histerese)

    if armado and cruzou:
        msg = f"Alerta: taxa cruzou alvo {alvo:.2f}% ({direcao})\n" + format_reading(reading, ultima_taxa)
        notifier.send_text(msg)
        storage.update_alert_state(reading.titulo, taxa, armado=0)
        logger.info("threshold disparado: %.2f %s %.2f", taxa, direcao, alvo)
    elif not armado and voltou:
        storage.update_alert_state(reading.titulo, taxa, armado=1)
        logger.info("threshold re-armado: %.2f voltou", taxa)


def _alert_delta(reading: RateReading, ultima_taxa: Optional[float], notifier: Notifier) -> None:
    delta_bps_config = float(storage.get_config("delta_bps", "5"))
    delta_threshold = delta_bps_config / 100
    taxa = reading.taxa_compra

    if ultima_taxa is None:
        storage.update_alert_state(reading.titulo, taxa, armado=1)
        return

    delta = abs(taxa - ultima_taxa)
    if delta >= delta_threshold:
        msg = format_reading(reading, ultima_taxa)
        notifier.send_text(msg)
        storage.update_alert_state(reading.titulo, taxa, armado=1)
        logger.info("delta disparado: %.4f >= %.4f", delta, delta_threshold)


def send_daily_summary(titulo: str, notifier: Notifier) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = storage.get_day_summary(titulo, today)

    if not summary or summary.get("abertura") is None:
        logger.info("sem dados para resumo diario de %s", titulo)
        return

    abertura = summary["abertura"]
    fechamento = summary["fechamento"]
    minima = summary["minima"]
    maxima = summary["maxima"]

    if abertura and fechamento:
        variacao_bps = (fechamento - abertura) * 100
        variacao_pct = ((fechamento - abertura) / abertura) * 100 if abertura else 0
        sinal = "+" if variacao_bps >= 0 else ""
        var_str = f"{sinal}{variacao_bps:.1f} bps ({sinal}{variacao_pct:.2f}%)"
    else:
        var_str = "N/A"

    msg = (
        f"Resumo diario - {titulo} - {today}\n"
        f"Abertura:   {abertura:.2f}% a.a.\n"
        f"Fechamento: {fechamento:.2f}% a.a.\n"
        f"Minima:     {minima:.2f}% a.a.\n"
        f"Maxima:     {maxima:.2f}% a.a.\n"
        f"Variacao:   {var_str}"
    )
    notifier.send_text(msg)
    logger.info("resumo diario enviado para %s", titulo)
