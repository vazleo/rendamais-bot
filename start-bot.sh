#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="/tmp/rendamais-bot.pid"
LOG_FILE="$SCRIPT_DIR/bot.log"

is_running() {
    [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

if is_running; then
    pid=$(cat "$PID_FILE")
    echo "[OK] Bot ja esta rodando (PID $pid)"
    echo "     Logs: tail -f $LOG_FILE"
    exit 0
fi

rm -f "$PID_FILE"

echo "Iniciando rendamais-bot..."
cd "$SCRIPT_DIR"
nohup python3 -m renda_bot.main >> "$LOG_FILE" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > "$PID_FILE"

sleep 2

if is_running; then
    echo "[OK] Bot iniciado com sucesso (PID $BOT_PID)"
    echo "     Logs: tail -f $LOG_FILE"
else
    rm -f "$PID_FILE"
    echo "[ERRO] Bot falhou ao iniciar. Ultimas linhas do log:"
    tail -20 "$LOG_FILE" 2>/dev/null || echo "(log vazio)"
    exit 1
fi
