"""Punto de entrada del bot de Discord global.

El bot está pensado para ser invitado a múltiples servidores. La
configuración de cada sistema (bienvenidas, etc.) se guarda por
guild_id en archivos JSON dentro de data/, así que cada servidor
tiene su propia configuración independiente.
"""

import asyncio
import logging
import os

import discord
from discord.ext import commands

from utils.storage import get_guild_data
from utils.prefix_cache import get_cached, set_cached, DEFAULT_PREFIX

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot")

TOKEN = os.environ.get("TOKEN")

INITIAL_COGS = [
    "cogs.welcome",
    "cogs.bot_setup",
    "cogs.moderation",
]


async def get_prefix(bot: commands.Bot, message: discord.Message):
    if not message.guild:
        return commands.when_mentioned_or(DEFAULT_PREFIX)(bot, message)

    guild_id = message.guild.id
    prefix = get_cached(guild_id)
    if prefix is None:
        data = await get_guild_data("bot_setup", guild_id)
        prefix = data.get("prefix", DEFAULT_PREFIX)
        set_cached(guild_id, prefix)
    return commands.when_mentioned_or(prefix)(bot, message)


class GlobalBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True  # necesario para on_member_join
        intents.message_content = True  # necesario para leer comandos con prefijo (?warn, ?ban, etc.)
        super().__init__(command_prefix=get_prefix, intents=intents, help_command=None)

    async def setup_hook(self):
        for cog in INITIAL_COGS:
            await self.load_extension(cog)
            logger.info("Cog cargado: %s", cog)

        synced = await self.tree.sync()
        logger.info("Comandos slash sincronizados globalmente: %d", len(synced))

    async def on_ready(self):
        logger.info("Conectado como %s (ID: %s)", self.user, self.user.id)
        logger.info("Presente en %d servidores", len(self.guilds))


async def main():
    if not TOKEN:
        raise RuntimeError(
            "No se encontró la variable de entorno TOKEN. "
            "Configura el token del bot como secreto antes de iniciarlo."
        )

    bot = GlobalBot()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
