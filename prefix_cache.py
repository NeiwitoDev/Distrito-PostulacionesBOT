"""Caché en memoria del prefijo de comandos por servidor.

El prefijo se consulta en cada mensaje que recibe el bot, así que se
mantiene en memoria para evitar leer el archivo de configuración
constantemente. Se actualiza cuando /bot-setup guarda un nuevo prefijo.
"""

DEFAULT_PREFIX = "?"

_cache: dict[int, str] = {}


def get_cached(guild_id: int) -> str | None:
    return _cache.get(guild_id)


def set_cached(guild_id: int, prefix: str) -> None:
    _cache[guild_id] = prefix
