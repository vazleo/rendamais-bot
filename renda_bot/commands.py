import logging
from io import BytesIO
from datetime import datetime, timedelta, timezone
from typing import Optional

from renda_bot import storage, charts
from renda_bot.config import TITULOS_MONITORADOS
from renda_bot.notifier.telegram import TelegramNotifier, get_updates
from renda_bot.alerts import format_reading

logger = logging.getLogger(__name__)

_TITULO = TITULOS_MONITORADOS[0]
_offset: int = 0
_last_reading = None


def set_last_reading(reading) -> None:
    global _last_reading
    _last_reading = reading


def poll_commands() -> None:
    global _offset
    updates = get_updates(_offset, timeout=30)
    for update in updates:
        _offset = update["update_id"] + 1
        message = update.get("message") or update.get("edited_message")
        if not message:
            continue
        _handle_message(message)


def _user_str(message: dict) -> str:
    sender = message.get("from", {})
    username = sender.get("username")
    first = sender.get("first_name", "")
    chat_id = message.get("chat", {}).get("id")
    if username:
        return f"@{username} ({chat_id})"
    return f"{first} ({chat_id})" if first else str(chat_id)


def _handle_message(message: dict) -> None:
    from renda_bot.config import TELEGRAM_ALLOWED_IDS
    chat_id = message.get("chat", {}).get("id")
    user = _user_str(message)

    if chat_id not in TELEGRAM_ALLOWED_IDS:
        logger.warning("mensagem nao autorizada de %s", user)
        return

    text = message.get("text", "").strip()
    if not text.startswith("/"):
        return

    notifier = TelegramNotifier(chat_id=chat_id)

    parts = text.split()
    cmd = parts[0].lower().split("@")[0]
    logger.info("comando %s de %s", cmd, user)
    args = parts[1:]

    handlers = {
        "/taxa": _cmd_taxa,
        "/modo": _cmd_modo,
        "/alvo": _cmd_alvo,
        "/delta": _cmd_delta,
        "/status": _cmd_status,
        "/historico": _cmd_historico,
        "/export": _cmd_export,
        "/pausar": _cmd_pausar,
        "/retomar": _cmd_retomar,
        "/silencio": _cmd_silencio,
        "/test": _cmd_test,
        "/help": _cmd_help,
    }

    handler = handlers.get(cmd)
    if handler:
        try:
            handler(args, notifier)
        except Exception as exc:
            logger.exception("erro no handler %s", cmd)
            notifier.send_text(f"Erro ao processar {cmd}: {exc}")
    else:
        notifier.send_text(f"Comando desconhecido: {cmd}. Use /help.")


def _cmd_taxa(_args, notifier) -> None:
    if _last_reading is None:
        notifier.send_text("Sem leitura disponivel ainda.")
        return
    notifier.send_text(format_reading(_last_reading))


def _cmd_modo(args, notifier) -> None:
    valid = ["sempre", "threshold", "delta"]
    if not args or args[0] not in valid:
        notifier.send_text(f"Uso: /modo {'|'.join(valid)}")
        return
    storage.set_config("modo", args[0])
    notifier.send_text(f"Modo alterado para: {args[0]}")


def _cmd_alvo(args, notifier) -> None:
    if not args:
        notifier.send_text("Uso: /alvo <valor> [acima|abaixo]")
        return
    try:
        valor = float(args[0].replace(",", "."))
    except ValueError:
        notifier.send_text("Valor invalido.")
        return
    direcao = args[1].lower() if len(args) > 1 else "acima"
    if direcao not in ("acima", "abaixo"):
        notifier.send_text("Direcao deve ser 'acima' ou 'abaixo'.")
        return
    storage.set_config("alvo", str(valor))
    storage.set_config("alvo_direcao", direcao)
    storage.set_config("modo", "threshold")
    storage.update_alert_state(_TITULO.apelido, ultima_taxa=valor, armado=1)
    notifier.send_text(f"Alvo definido: {valor:.2f}% {direcao}. Modo: threshold.")


def _cmd_delta(args, notifier) -> None:
    if not args:
        notifier.send_text("Uso: /delta <bps>")
        return
    try:
        bps = float(args[0].replace(",", "."))
    except ValueError:
        notifier.send_text("Valor invalido.")
        return
    storage.set_config("delta_bps", str(bps))
    storage.set_config("modo", "delta")
    notifier.send_text(f"Delta definido: {bps} bps. Modo: delta.")


def _cmd_status(_args, notifier) -> None:
    from renda_bot.market import now_br, is_market_open
    modo = storage.get_config("modo", "delta")
    alvo = storage.get_config("alvo", "N/A")
    alvo_dir = storage.get_config("alvo_direcao", "acima")
    delta_bps = storage.get_config("delta_bps", "5")
    pausado = storage.get_config("pausado", "0") == "1"
    silencio = storage.get_config("silencio", "desabilitado")

    last = storage.get_last_reading(_TITULO.apelido)
    if last:
        ts = datetime.fromisoformat(last["ts_coleta"])
        ago = datetime.now(timezone.utc) - ts
        ago_min = int(ago.total_seconds() / 60)
        fonte = last["fonte"]
        last_str = f"{ago_min} min atras (fonte: {fonte})"
    else:
        last_str = "nunca"

    msg = (
        f"Status do bot\n"
        f"Modo: {modo}\n"
        f"Alvo: {alvo}% ({alvo_dir})\n"
        f"Delta: {delta_bps} bps\n"
        f"Pausado: {'sim' if pausado else 'nao'}\n"
        f"Silencio: {silencio or 'desabilitado'}\n"
        f"Mercado aberto: {'sim' if is_market_open() else 'nao'}\n"
        f"Ultimo fetch OK: {last_str}\n"
        f"Horario BR: {now_br().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    notifier.send_text(msg)


def _cmd_historico(args, notifier) -> None:
    try:
        dias = int(args[0]) if args else 1
        dias = max(1, min(dias, 30))
    except ValueError:
        dias = 1

    png, caption = charts.build_chart(_TITULO.apelido, dias)
    notifier.send_photo(png, caption)


def _cmd_export(args, notifier) -> None:
    try:
        dias = int(args[0]) if args else 7
        dias = max(1, min(dias, 90))
    except ValueError:
        dias = 7

    since = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    csv_data = storage.export_csv(_TITULO.apelido, since)
    notifier.send_document(
        csv_data.encode("utf-8"),
        filename=f"renda_mais_2065_{dias}d.csv",
        caption=f"Export CSV - {dias} dias",
    )


def _cmd_pausar(_args, notifier) -> None:
    storage.set_config("pausado", "1")
    notifier.send_text("Alertas pausados. Use /retomar para reativar.")


def _cmd_retomar(_args, notifier) -> None:
    storage.set_config("pausado", "0")
    notifier.send_text("Alertas reativados.")


def _cmd_silencio(args, notifier) -> None:
    if not args:
        storage.set_config("silencio", "")
        notifier.send_text("Silencio desabilitado.")
        return
    horario = args[0]
    if "-" not in horario:
        notifier.send_text("Uso: /silencio HH:MM-HH:MM (ex: /silencio 22:00-08:00)")
        return
    storage.set_config("silencio", horario)
    notifier.send_text(f"Silencio configurado: {horario}")


def _cmd_test(_args, notifier) -> None:
    from renda_bot.sources.mock import MockSource
    mock = MockSource()
    reading = mock.get_rate(_TITULO)
    msg = "[TESTE] " + format_reading(reading, taxa_anterior=6.95)
    notifier.send_text(msg)


def _cmd_help(_args, notifier) -> None:
    msg = (
        "Comandos disponiveis:\n"
        "/taxa               - Taxa atual\n"
        "/modo sempre|threshold|delta - Troca modo\n"
        "/alvo <val> [acima|abaixo]   - Define alvo threshold\n"
        "/delta <bps>        - Define sensibilidade delta\n"
        "/status             - Config e saude do bot\n"
        "/historico [dias]   - Grafico de historico\n"
        "/export [dias]      - CSV das leituras\n"
        "/pausar             - Pausa alertas\n"
        "/retomar            - Reativa alertas\n"
        "/silencio HH:MM-HH:MM - Quiet hours\n"
        "/test               - Alerta fake de teste\n"
        "/help               - Esta mensagem"
    )
    notifier.send_text(msg)
