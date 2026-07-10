"""Parser simple de duraciones tipo "10m", "2h", "1d12h", "30s"."""

import re
from datetime import timedelta

_UNITS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}

_PATTERN = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)


def parse_duration(text: str) -> timedelta | None:
    """Convierte algo como "1d12h" o "45m" en un timedelta. None si no es válido."""
    text = text.strip().lower()
    if not text:
        return None
    matches = _PATTERN.findall(text)
    if not matches:
        return None
    # Verifica que todo el texto haya sido consumido por el patrón (evita "10x" mal escrito).
    if _PATTERN.sub("", text).strip():
        return None

    kwargs: dict[str, int] = {}
    for amount, unit in matches:
        key = _UNITS[unit]
        kwargs[key] = kwargs.get(key, 0) + int(amount)

    delta = timedelta(**kwargs)
    if delta.total_seconds() <= 0:
        return None
    return delta


def format_duration(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    parts = []
    for unit, seconds in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        value, total = divmod(total, seconds)
        if value:
            parts.append(f"{value}{unit}")
    return " ".join(parts) if parts else "0s"
