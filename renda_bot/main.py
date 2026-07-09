import fcntl
import logging
import os
import signal
import sys
import threading
import time

from renda_bot import storage, alerts, health, commands
from renda_bot.config import POLL_INTERVAL_SEG, TITULOS_MONITORADOS
from renda_bot.market import is_market_open
from renda_bot.notifier.telegram import BroadcastNotifier
from renda_bot.orchestrator import SourceOrchestrator

_LOCK_FILE = "/tmp/rendamais-bot.lock"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_shutdown = threading.Event()


def _handle_signal(signum, frame):
    logger.info("sinal %d recebido, encerrando...", signum)
    _shutdown.set()


def poll_loop():
    notifier = BroadcastNotifier()
    orchestrator = SourceOrchestrator()

    logger.info("poll loop iniciado (intervalo=%ds)", POLL_INTERVAL_SEG)

    while not _shutdown.is_set():
        if not is_market_open():
            logger.debug("mercado fechado, aguardando...")
            _shutdown.wait(POLL_INTERVAL_SEG * 4)
            continue

        for titulo in TITULOS_MONITORADOS:
            try:
                reading = orchestrator.fetch(titulo)
            except Exception as exc:
                logger.error("erro inesperado no fetch: %s", exc)
                reading = None

            if reading is not None:
                storage.save_reading(reading)
                commands.set_last_reading(reading)
                alerts.check_and_alert(reading, notifier)
            else:
                health.check_dead_man(orchestrator.consecutive_failures, notifier)

            if health.should_send_daily_summary(titulo.apelido):
                alerts.send_daily_summary(titulo.apelido, notifier)
                health.mark_daily_summary_sent()

        storage.prune_old_readings()
        _shutdown.wait(POLL_INTERVAL_SEG)


def command_loop():
    logger.info("command loop iniciado (long polling)")
    while not _shutdown.is_set():
        try:
            commands.poll_commands()
        except Exception as exc:
            logger.error("erro no command loop: %s", exc)
            _shutdown.wait(5)


def main():
    # Garante que só uma instância rode por vez
    lock_fh = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Outra instância do bot já está rodando. Encerrando.", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    storage.init_db()
    logger.info("banco de dados inicializado")

    t_poll = threading.Thread(target=poll_loop, name="poll", daemon=True)
    t_cmd = threading.Thread(target=command_loop, name="commands", daemon=True)

    t_poll.start()
    t_cmd.start()

    logger.info("bot iniciado")

    _shutdown.wait()
    logger.info("aguardando threads encerrarem...")
    t_poll.join(timeout=10)
    t_cmd.join(timeout=10)
    logger.info("bot encerrado")


if __name__ == "__main__":
    main()
