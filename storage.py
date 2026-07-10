"""Almacenamiento simple en JSON para la configuración de cada servidor.

Cada sistema del bot (bienvenidas, etc.) guarda su configuración por
guild_id dentro de un único archivo JSON en data/. Se usa un lock por
archivo para evitar condiciones de carrera entre escrituras concurrentes.
"""

import json
import os
import asyncio
from typing import Any

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(path: str) -> asyncio.Lock:
    if path not in _locks:
        _locks[path] = asyncio.Lock()
    return _locks[path]


def _path_for(name: str) -> str:
    return os.path.join(DATA_DIR, f"{name}.json")


def _read_raw(name: str) -> dict:
    path = _path_for(name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_raw(name: str, data: dict) -> None:
    path = _path_for(name)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


async def get_guild_data(store: str, guild_id: int) -> dict[str, Any]:
    """Obtiene la configuración de un guild dentro de un store (ej. 'welcome')."""
    async with _lock_for(store):
        data = _read_raw(store)
        return data.get(str(guild_id), {})


async def set_guild_data(store: str, guild_id: int, value: dict[str, Any]) -> None:
    """Guarda/actualiza la configuración de un guild dentro de un store."""
    async with _lock_for(store):
        data = _read_raw(store)
        data[str(guild_id)] = value
        _write_raw(store, data)


async def delete_guild_data(store: str, guild_id: int) -> None:
    async with _lock_for(store):
        data = _read_raw(store)
        if str(guild_id) in data:
            del data[str(guild_id)]
            _write_raw(store, data)


async def get_all_guild_data(store: str) -> dict[str, dict[str, Any]]:
    """Devuelve la configuración de todos los guilds para un store dado.

    Útil al iniciar el bot para reconstruir vistas persistentes que
    dependen de configuración guardada por servidor.
    """
    async with _lock_for(store):
        return _read_raw(store)


async def update_guild_data(store: str, guild_id: int, mutator) -> dict[str, Any]:
    """Lee, modifica y guarda la configuración de un guild de forma atómica.

    `mutator` recibe el dict actual (posiblemente vacío) y debe devolver el
    dict actualizado. Todo ocurre bajo un único lock para evitar perder
    cambios cuando hay varias interacciones concurrentes sobre el mismo guild.
    """
    async with _lock_for(store):
        data = _read_raw(store)
        current = data.get(str(guild_id), {})
        updated = mutator(current)
        data[str(guild_id)] = updated
        _write_raw(store, data)
        return updated
