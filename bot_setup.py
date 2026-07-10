"""Comando /bot-setup: configuración general del bot por servidor.

Permite ajustar el prefijo de los comandos de texto y el idioma de
los mensajes que ven los usuarios.
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import get_guild_data, update_guild_data
from utils.prefix_cache import set_cached, DEFAULT_PREFIX

STORE = "bot_setup"

LANGUAGES = {"es": "Español", "en": "English"}


def build_settings_embed(prefix: str, language: str) -> discord.Embed:
    embed = discord.Embed(
        title="Configuración general del bot",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Prefijo", value=f"`{prefix}`", inline=True)
    embed.add_field(name="Idioma", value=LANGUAGES.get(language, language), inline=True)
    embed.set_footer(text="El prefijo se usa para los comandos de texto del bot.")
    return embed


class PrefixModal(discord.ui.Modal, title="Cambiar prefijo"):
    def __init__(self, view: "BotSetupView"):
        super().__init__()
        self.view_ref = view
        self.prefix_input = discord.ui.TextInput(
            label="Nuevo prefijo",
            placeholder="Ej: ? ! . >",
            default=view.prefix,
            max_length=5,
            min_length=1,
            required=True,
        )
        self.add_item(self.prefix_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_prefix = str(self.prefix_input.value).strip()
        if not new_prefix or " " in new_prefix:
            await interaction.response.send_message(
                "El prefijo no puede estar vacío ni contener espacios.", ephemeral=True
            )
            return
        self.view_ref.prefix = new_prefix
        await self.view_ref.refresh(interaction)


class ChangePrefixButton(discord.ui.Button):
    def __init__(self, view: "BotSetupView"):
        super().__init__(label="Cambiar prefijo", style=discord.ButtonStyle.secondary, row=0)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PrefixModal(self.view_ref))


class LanguageSelect(discord.ui.Select):
    def __init__(self, view: "BotSetupView"):
        options = [
            discord.SelectOption(label=name, value=code, default=(code == view.language))
            for code, name in LANGUAGES.items()
        ]
        super().__init__(placeholder="Selecciona el idioma", options=options, row=1)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.language = self.values[0]
        await self.view_ref.refresh(interaction)


class SaveSettingsButton(discord.ui.Button):
    def __init__(self, view: "BotSetupView"):
        super().__init__(label="Guardar configuración", style=discord.ButtonStyle.success, row=0)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        v = self.view_ref

        def _mutate(current: dict) -> dict:
            current.update({"prefix": v.prefix, "language": v.language})
            return current

        await update_guild_data(STORE, v.guild_id, _mutate)
        set_cached(v.guild_id, v.prefix)

        for item in v.children:
            item.disabled = True
        embed = build_settings_embed(v.prefix, v.language)
        embed.color = discord.Color.green()
        embed.set_footer(text="✅ Configuración guardada.")
        await interaction.response.edit_message(embed=embed, view=v)
        v.stop()


class BotSetupView(discord.ui.View):
    def __init__(self, guild_id: int, prefix: str, language: str, author_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.prefix = prefix
        self.language = language
        self.author_id = author_id
        self.message: discord.Message | None = None

        self.add_item(ChangePrefixButton(self))
        self.add_item(SaveSettingsButton(self))
        self.add_item(LanguageSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Solo quien ejecutó el comando puede usar este panel.", ephemeral=True
            )
            return False
        return True

    async def refresh(self, interaction: discord.Interaction):
        self.clear_items()
        self.add_item(ChangePrefixButton(self))
        self.add_item(SaveSettingsButton(self))
        self.add_item(LanguageSelect(self))
        embed = build_settings_embed(self.prefix, self.language)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class BotSetup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="bot-setup",
        description="Configura el prefijo y el idioma del bot en este servidor.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def general_setup_cmd(self, interaction: discord.Interaction):
        data = await get_guild_data(STORE, interaction.guild_id)
        prefix = data.get("prefix", DEFAULT_PREFIX)
        language = data.get("language", "es")
        view = BotSetupView(
            guild_id=interaction.guild_id,
            prefix=prefix,
            language=language,
            author_id=interaction.user.id,
        )
        embed = build_settings_embed(prefix, language)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(BotSetup(bot))
