import io
import logging
from datetime import datetime, timedelta, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from renda_bot import storage

logger = logging.getLogger(__name__)

BUCKET_MINUTES = 5


def _bucket_key(ts_str: str) -> datetime:
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    minutes = (dt.minute // BUCKET_MINUTES) * BUCKET_MINUTES
    return dt.replace(minute=minutes, second=0, microsecond=0)


def _downsample(rows: list[dict]) -> tuple[list, list, list]:
    buckets: dict[datetime, list] = {}
    for r in rows:
        key = _bucket_key(r["ts_coleta"])
        buckets.setdefault(key, []).append(r)

    times, compra, resgate = [], [], []
    for ts in sorted(buckets):
        group = buckets[ts]
        last = group[-1]
        times.append(ts)
        compra.append(last["taxa_compra"])
        resgate.append(last["taxa_resgate"])

    return times, compra, resgate


def build_chart(titulo: str, dias: int = 1) -> tuple[bytes, str]:
    since = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    rows = storage.get_readings(titulo, since)

    if not rows:
        return _empty_chart(), f"Sem dados para {titulo} nos ultimos {dias} dia(s)"

    times, compra, resgate = _downsample(rows)

    import pytz
    tz_br = pytz.timezone("America/Sao_Paulo")
    times_br = [t.astimezone(tz_br) for t in times]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(times_br, compra, label="Taxa compra", linewidth=1.5, color="steelblue")

    has_resgate = any(v is not None for v in resgate)
    if has_resgate:
        resgate_clean = [v for v in resgate if v is not None]
        times_res = [times_br[i] for i, v in enumerate(resgate) if v is not None]
        ax.plot(times_res, resgate_clean, label="Taxa resgate", linewidth=1.2,
                linestyle="--", color="darkorange")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M", tz=tz_br))
    fig.autofmt_xdate()
    ax.set_ylabel("Taxa (% a.a.)")
    ax.set_title(f"Tesouro {titulo} - ultimos {dias} dia(s)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    compra_vals = [v for v in compra if v is not None]
    minima = min(compra_vals) if compra_vals else 0
    maxima = max(compra_vals) if compra_vals else 0

    fontes = {r["fonte"] for r in rows}
    fonte_str = "/".join(sorted(fontes))

    caption = (
        f"Periodo: {dias} dia(s) | "
        f"Min: {minima:.2f}% | Max: {maxima:.2f}% | Fonte: {fonte_str}"
    )

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.read(), caption


def _empty_chart() -> bytes:
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.text(0.5, 0.5, "Sem dados", ha="center", va="center", transform=ax.transAxes)
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
