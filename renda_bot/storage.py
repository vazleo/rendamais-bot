import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from renda_bot.config import DB_PATH, RETENCAO_DIAS
from renda_bot.models import RateReading

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _lock, _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS readings (
            id            INTEGER PRIMARY KEY,
            titulo        TEXT NOT NULL,
            taxa_compra   REAL NOT NULL,
            taxa_resgate  REAL,
            pu_compra     REAL,
            pu_resgate    REAL,
            fonte         TEXT NOT NULL,
            mercado_aberto INTEGER NOT NULL,
            ts_fonte      TEXT,
            ts_coleta     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_readings_titulo_ts ON readings (titulo, ts_coleta);

        CREATE TABLE IF NOT EXISTS config (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alert_state (
            titulo        TEXT NOT NULL,
            ultima_taxa_alertada REAL,
            armado        INTEGER NOT NULL DEFAULT 1,
            ultimo_alerta_ts TEXT,
            PRIMARY KEY (titulo)
        );
        """)

    _seed_defaults()


def _seed_defaults() -> None:
    defaults = {
        "modo": "delta",
        "alvo": "7.00",
        "alvo_direcao": "acima",
        "delta_bps": "5",
        "pausado": "0",
        "silencio": "",
    }
    with _lock, _conn() as con:
        for chave, valor in defaults.items():
            con.execute(
                "INSERT OR IGNORE INTO config (chave, valor) VALUES (?, ?)",
                (chave, valor),
            )


def save_reading(reading: RateReading) -> None:
    ts_coleta = datetime.now(timezone.utc).isoformat()
    ts_fonte = reading.timestamp_fonte.isoformat() if reading.timestamp_fonte else None
    with _lock, _conn() as con:
        con.execute(
            """INSERT INTO readings
               (titulo, taxa_compra, taxa_resgate, pu_compra, pu_resgate,
                fonte, mercado_aberto, ts_fonte, ts_coleta)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                reading.titulo,
                reading.taxa_compra,
                reading.taxa_resgate,
                reading.pu_compra,
                reading.pu_resgate,
                reading.fonte,
                int(reading.mercado_aberto),
                ts_fonte,
                ts_coleta,
            ),
        )


def get_config(chave: str, default: str = "") -> str:
    with _conn() as con:
        row = con.execute("SELECT valor FROM config WHERE chave=?", (chave,)).fetchone()
    return row["valor"] if row else default


def set_config(chave: str, valor: str) -> None:
    with _lock, _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO config (chave, valor) VALUES (?, ?)",
            (chave, str(valor)),
        )


def get_alert_state(titulo: str) -> dict:
    with _conn() as con:
        row = con.execute("SELECT * FROM alert_state WHERE titulo=?", (titulo,)).fetchone()
    if row:
        return dict(row)
    return {"titulo": titulo, "ultima_taxa_alertada": None, "armado": 1, "ultimo_alerta_ts": None}


def update_alert_state(titulo: str, ultima_taxa: float, armado: int) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with _lock, _conn() as con:
        con.execute(
            """INSERT OR REPLACE INTO alert_state
               (titulo, ultima_taxa_alertada, armado, ultimo_alerta_ts)
               VALUES (?, ?, ?, ?)""",
            (titulo, ultima_taxa, armado, ts),
        )


def get_readings(titulo: str, since_iso: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM readings WHERE titulo=? AND ts_coleta>=? ORDER BY ts_coleta",
            (titulo, since_iso),
        ).fetchall()
    return [dict(r) for r in rows]


def get_last_reading(titulo: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM readings WHERE titulo=? ORDER BY ts_coleta DESC LIMIT 1",
            (titulo,),
        ).fetchone()
    return dict(row) if row else None


def get_day_summary(titulo: str, date_iso: str) -> dict:
    with _conn() as con:
        row = con.execute(
            """SELECT
                 MIN(taxa_compra) as minima,
                 MAX(taxa_compra) as maxima,
                 (SELECT taxa_compra FROM readings
                  WHERE titulo=? AND ts_coleta LIKE ?
                  ORDER BY ts_coleta ASC LIMIT 1) as abertura,
                 (SELECT taxa_compra FROM readings
                  WHERE titulo=? AND ts_coleta LIKE ?
                  ORDER BY ts_coleta DESC LIMIT 1) as fechamento
               FROM readings WHERE titulo=? AND ts_coleta LIKE ?""",
            (titulo, date_iso + "%", titulo, date_iso + "%", titulo, date_iso + "%"),
        ).fetchone()
    return dict(row) if row else {}


def prune_old_readings() -> int:
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENCAO_DIAS)).isoformat()
    with _lock, _conn() as con:
        cur = con.execute("DELETE FROM readings WHERE ts_coleta < ?", (cutoff,))
        deleted = cur.rowcount
    if deleted:
        logger.info("poda: %d leituras antigas removidas", deleted)
    return deleted


def export_csv(titulo: str, since_iso: str) -> str:
    rows = get_readings(titulo, since_iso)
    if not rows:
        return "titulo,taxa_compra,taxa_resgate,fonte,ts_coleta\n"
    lines = ["titulo,taxa_compra,taxa_resgate,pu_compra,pu_resgate,fonte,mercado_aberto,ts_fonte,ts_coleta"]
    for r in rows:
        lines.append(
            f"{r['titulo']},{r['taxa_compra']},{r.get('taxa_resgate','')},{r.get('pu_compra','')},"
            f"{r.get('pu_resgate','')},{r['fonte']},{r['mercado_aberto']},{r.get('ts_fonte','')},{r['ts_coleta']}"
        )
    return "\n".join(lines)
