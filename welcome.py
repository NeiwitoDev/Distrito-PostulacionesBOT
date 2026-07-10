"""Sistema de bienvenidas.

Comando /welcome-setup: abre un panel para configurar, por servidor:
- Canal de bienvenida
- Mensaje de bienvenida (con variables {usuario}, {servidor}, {miembros})
- Canales recomendados (opcional), mostrados como enlaces en el mensaje

La configuración se guarda por guild_id, así que el bot funciona igual
en cualquier servidor donde se invite (es global).
"""

import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import get_guild_data, set_guild_data, update_guild_data

STORE = "welcome"

DEFAULT_MESSAGE = "¡Bienvenido/a {usuario} a **{servidor}**! Ya somos {miembros} miembros."


def build_preview_embed(
    guild: discord.Guild,
    channel_id: int | None,
    message: str | None,
    recommended_channel_ids: list[int],
) -> discord.Embed:
    embed = discord.Embed(
        title="Configuración de bienvenidas",
        color=discord.Color.blurple(),
    )
    channel_text = f"<#{channel_id}>" if channel_id else "*Sin configurar*"
    embed.add_field(name="Canal", value=channel_text, inline=False)

    msg = message or DEFAULT_MESSAGE
    embed.add_field(name="Mensaje de bienvenida", value=f"```{msg}```", inline=False)

    if recommended_channel_ids:
        rec_text = " ".join(f"<#{cid}>" for cid in recommended_channel_ids)
    else:
        rec_text = "*Ninguno*"
    embed.add_field(name="Canales recomendados (opcional)", value=rec_text, inline=False)

    embed.set_footer(text="Usa los menús y botones de abajo para configurar. No olvides guardar.")
    return embed


def render_welcome_message(template: str, member: discord.Member) -> str:
    return (
        template.replace("{usuario}", member.mention)
        .replace("{servidor}", member.guild.name)
        .replace("{miembros}", str(member.guild.member_count))
    )


class WelcomeMessageModal(discord.ui.Modal, title="Mensaje de bienvenida"):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__()
        self.view_ref = view
        self.message_input = discord.ui.TextInput(
            label="Mensaje de bienvenida",
            style=discord.TextStyle.paragraph,
            placeholder="Ej: ¡Bienvenido/a {usuario} a {servidor}!",
            default=view.welcome_message or DEFAULT_MESSAGE,
            max_length=1000,
            required=True,
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.welcome_message = str(self.message_input.value)
        await self.view_ref.refresh(interaction)


class WelcomeChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__(
            placeholder="Selecciona el canal de bienvenida",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1,
            max_values=1,
            row=0,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.channel_id = self.values[0].id
        await self.view_ref.refresh(interaction)


class RecommendedChannelsSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__(
            placeholder="Selecciona canales recomendados (opcional)",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0,
            max_values=25,
            row=1,
        )
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.recommended_channel_ids = [c.id for c in self.values]
        await self.view_ref.refresh(interaction)


class SetMessageButton(discord.ui.Button):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__(label="Editar mensaje", style=discord.ButtonStyle.secondary, row=2)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(WelcomeMessageModal(self.view_ref))


class SaveButton(discord.ui.Button):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__(label="Guardar configuración", style=discord.ButtonStyle.success, row=2)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        v = self.view_ref
        if not v.channel_id:
            await interaction.response.send_message(
                "Selecciona un canal antes de guardar.", ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(v.channel_id)
        if channel is not None:
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.send_messages and perms.embed_links):
                await interaction.response.send_message(
                    "No tengo permisos de **Enviar mensajes** y/o **Insertar enlaces** en "
                    f"{channel.mention}. Ajusta los permisos del canal y vuelve a guardar.",
                    ephemeral=True,
                )
                return

        def _mutate(current: dict) -> dict:
            current.update(
                {
                    "channel_id": v.channel_id,
                    "message": v.welcome_message or DEFAULT_MESSAGE,
                    "recommended_channel_ids": v.recommended_channel_ids,
                    "enabled": True,
                }
            )
            return current

        await update_guild_data(STORE, v.guild_id, _mutate)
        for item in v.children:
            item.disabled = True
        embed = build_preview_embed(
            interaction.guild, v.channel_id, v.welcome_message, v.recommended_channel_ids
        )
        embed.color = discord.Color.green()
        embed.set_footer(text="✅ Configuración guardada.")
        await interaction.response.edit_message(embed=embed, view=v)
        v.stop()


class DisableButton(discord.ui.Button):
    def __init__(self, view: "WelcomeSetupView"):
        super().__init__(label="Desactivar bienvenidas", style=discord.ButtonStyle.danger, row=3)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        v = self.view_ref

        def _mutate(current: dict) -> dict:
            current["enabled"] = False
            return current

        await update_guild_data(STORE, v.guild_id, _mutate)
        for item in v.children:
            item.disabled = True
        embed = discord.Embed(
            title="Sistema de bienvenidas desactivado",
            description="Ya no se enviarán mensajes de bienvenida en este servidor.",
            color=discord.Color.red(),
        )
        await interaction.response.edit_message(embed=embed, view=v)
        v.stop()


class WelcomeSetupView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        channel_id: int | None,
        welcome_message: str | None,
        recommended_channel_ids: list[int],
        author_id: int,
    ):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.welcome_message = welcome_message
        self.recommended_channel_ids = recommended_channel_ids
        self.author_id = author_id
        self.message: discord.Message | None = None

        self.add_item(WelcomeChannelSelect(self))
        self.add_item(RecommendedChannelsSelect(self))
        self.add_item(SetMessageButton(self))
        self.add_item(SaveButton(self))
        self.add_item(DisableButton(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Solo quien ejecutó el comando puede usar este panel.", ephemeral=True
            )
            return False
        return True

    async def refresh(self, interaction: discord.Interaction):
        embed = build_preview_embed(
            interaction.guild, self.channel_id, self.welcome_message, self.recommended_channel_ids
        )
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


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="welcome-setup",
        description="Configura el sistema de bienvenidas de este servidor.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def welcome_setup(self, interaction: discord.Interaction):
        data = await get_guild_data(STORE, interaction.guild_id)
        view = WelcomeSetupView(
            guild_id=interaction.guild_id,
            channel_id=data.get("channel_id"),
            welcome_message=data.get("message"),
            recommended_channel_ids=data.get("recommended_channel_ids", []),
            author_id=interaction.user.id,
        )
        embed = build_preview_embed(
            interaction.guild,
            view.channel_id,
            view.welcome_message,
            view.recommended_channel_ids,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        data = await get_guild_data(STORE, member.guild.id)
        if not data or not data.get("enabled") or not data.get("channel_id"):
            return

        channel = member.guild.get_channel(data["channel_id"])
        if channel is None:
            return

        template = data.get("message") or DEFAULT_MESSAGE
        text = render_welcome_message(template, member)

        embed = discord.Embed(description=text, color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)

        recommended_ids = data.get("recommended_channel_ids") or []
        if recommended_ids:
            links = " ".join(
                f"<#{cid}>" for cid in recommended_ids if member.guild.get_channel(cid)
            )
            if links:
                embed.add_field(name="Canales recomendados", value=links, inline=False)

        try:
            await channel.send(content=member.mention, embed=embed)
        except discord.Forbidden:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
