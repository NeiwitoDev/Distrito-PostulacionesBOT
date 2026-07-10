"""Sistema de moderación con comandos de texto (prefijo).

Comandos:
- ?warn {user} {motivo}
- ?warns {user}
- ?delwarn {user} {warn-id}
- ?ban {user} {motivo}
- ?unban {user_id}
- ?tempban {user} {motivo} {tiempo}
- ?mute {user} {motivo}
- ?unmute {user}
- ?lock {canal} {tiempo}
- ?unlock {canal}

Los warns y baneos temporales se guardan por guild_id en data/ (como el
resto de sistemas del bot) para que sobrevivan a un reinicio.
"""

import asyncio
import time

import discord
from discord.ext import commands

from utils.storage import get_guild_data, set_guild_data, update_guild_data
from utils.duration import parse_duration, format_duration

WARNS_STORE = "warns"
TEMPBANS_STORE = "tempbans"
MOD_STORE = "moderation"

MUTED_ROLE_NAME = "Muted"


def _fmt_ts(ts: float) -> str:
    return f"<t:{int(ts)}:f>"


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tempban_tasks: dict[tuple[int, int], asyncio.Task] = {}

    async def cog_load(self):
        # Al cargar el cog, reprograma los tempbans pendientes guardados en disco.
        all_guilds = await get_all_guild_tempbans(self.bot)
        for guild_id, entries in all_guilds.items():
            for entry in entries:
                self._schedule_tempban_expiry(guild_id, entry["user_id"], entry["unban_at"])

    def _schedule_tempban_expiry(self, guild_id: int, user_id: int, unban_at: float):
        key = (guild_id, user_id)
        if key in self._tempban_tasks:
            self._tempban_tasks[key].cancel()
        delay = max(0, unban_at - time.time())
        self._tempban_tasks[key] = self.bot.loop.create_task(
            self._expire_tempban(guild_id, user_id, delay)
        )

    async def _expire_tempban(self, guild_id: int, user_id: int, delay: float):
        try:
            await asyncio.sleep(delay)
            guild = self.bot.get_guild(guild_id)
            if guild:
                try:
                    await guild.unban(discord.Object(id=user_id), reason="Tempban expirado")
                except discord.NotFound:
                    pass
            await self._remove_tempban_record(guild_id, user_id)
        except asyncio.CancelledError:
            pass

    async def _remove_tempban_record(self, guild_id: int, user_id: int):
        def mutator(data: dict) -> dict:
            entries = data.get("entries", [])
            data["entries"] = [e for e in entries if e["user_id"] != user_id]
            return data

        await update_guild_data(TEMPBANS_STORE, guild_id, mutator)
        task = self._tempban_tasks.pop((guild_id, user_id), None)
        if task and not task.done():
            task.cancel()

    def _hierarchy_ok(self, ctx: commands.Context, target: discord.Member) -> str | None:
        """Devuelve un mensaje de error si la jerarquía de roles no permite la acción, o None si está OK."""
        if target.id == ctx.guild.owner_id:
            return "No podés actuar sobre el dueño del servidor."
        if ctx.guild.owner_id != ctx.author.id and target.top_role >= ctx.author.top_role:
            return "No podés actuar sobre alguien con un rol igual o mayor al tuyo."
        if target.top_role >= ctx.guild.me.top_role:
            return "Mi rol está por debajo (o igual) del rol de esa persona, no puedo actuar sobre ella."
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_muted_role(self, guild: discord.Guild) -> discord.Role:
        data = await get_guild_data(MOD_STORE, guild.id)
        role_id = data.get("muted_role_id")
        role = guild.get_role(role_id) if role_id else None
        if role is None:
            role = discord.utils.get(guild.roles, name=MUTED_ROLE_NAME)
        if role is None:
            role = await guild.create_role(
                name=MUTED_ROLE_NAME,
                reason="Rol creado automáticamente para el comando ?mute",
            )
            for channel in guild.channels:
                try:
                    await channel.set_permissions(
                        role,
                        send_messages=False,
                        add_reactions=False,
                        speak=False,
                        reason="Configuración del rol Muted",
                    )
                except discord.Forbidden:
                    continue
        await update_guild_data(MOD_STORE, guild.id, lambda d: {**d, "muted_role_id": role.id})
        return role

    def _error_embed(self, message: str) -> discord.Embed:
        return discord.Embed(description=f"❌ {message}", color=discord.Color.red())

    def _success_embed(self, message: str) -> discord.Embed:
        return discord.Embed(description=f"✅ {message}", color=discord.Color.green())

    # ------------------------------------------------------------------
    # Warns
    # ------------------------------------------------------------------

    @commands.command(name="warn")
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def warn(self, ctx: commands.Context, member: discord.Member, *, motivo: str):
        if member.id == ctx.author.id:
            await ctx.reply(embed=self._error_embed("No podés advertirte a vos mismo."))
            return
        if member.bot:
            await ctx.reply(embed=self._error_embed("No podés advertir a un bot."))
            return

        def mutator(data: dict) -> dict:
            next_id = data.get("next_id", 1)
            warns = data.get("warns", [])
            warns.append(
                {
                    "id": next_id,
                    "user_id": member.id,
                    "moderator_id": ctx.author.id,
                    "reason": motivo,
                    "timestamp": time.time(),
                }
            )
            return {"next_id": next_id + 1, "warns": warns}

        updated = await update_guild_data(WARNS_STORE, ctx.guild.id, mutator)
        warn_id = updated["next_id"] - 1

        embed = discord.Embed(
            title="⚠️ Advertencia registrada",
            description=f"{member.mention} fue advertido/a.",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Motivo", value=motivo, inline=False)
        embed.add_field(name="ID del warn", value=str(warn_id), inline=True)
        embed.set_footer(text=f"Moderador: {ctx.author}")
        await ctx.reply(embed=embed)

        try:
            dm_embed = discord.Embed(
                title=f"⚠️ Recibiste una advertencia en {ctx.guild.name}",
                description=motivo,
                color=discord.Color.orange(),
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    @commands.command(name="warns")
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def warns(self, ctx: commands.Context, member: discord.Member):
        data = await get_guild_data(WARNS_STORE, ctx.guild.id)
        user_warns = [w for w in data.get("warns", []) if w["user_id"] == member.id]

        embed = discord.Embed(
            title=f"Advertencias de {member}",
            color=discord.Color.orange(),
        )
        if not user_warns:
            embed.description = "Este usuario no tiene advertencias."
        else:
            for w in user_warns:
                moderator = ctx.guild.get_member(w["moderator_id"])
                mod_text = moderator.mention if moderator else f"ID {w['moderator_id']}"
                embed.add_field(
                    name=f"Warn #{w['id']} — {_fmt_ts(w['timestamp'])}",
                    value=f"**Motivo:** {w['reason']}\n**Moderador:** {mod_text}",
                    inline=False,
                )
        await ctx.reply(embed=embed)

    @commands.command(name="delwarn")
    @commands.has_permissions(moderate_members=True)
    @commands.guild_only()
    async def delwarn(self, ctx: commands.Context, member: discord.Member, warn_id: int):
        def mutator(data: dict) -> dict:
            warns = data.get("warns", [])
            data["warns"] = [
                w for w in warns if not (w["user_id"] == member.id and w["id"] == warn_id)
            ]
            return data

        before = await get_guild_data(WARNS_STORE, ctx.guild.id)
        before_count = len([w for w in before.get("warns", []) if w["user_id"] == member.id])

        updated = await update_guild_data(WARNS_STORE, ctx.guild.id, mutator)
        after_count = len([w for w in updated.get("warns", []) if w["user_id"] == member.id])

        if after_count == before_count:
            await ctx.reply(embed=self._error_embed(f"No se encontró el warn #{warn_id} para {member.mention}."))
            return

        await ctx.reply(embed=self._success_embed(f"Se eliminó el warn #{warn_id} de {member.mention}."))

    # ------------------------------------------------------------------
    # Ban / Unban / Tempban
    # ------------------------------------------------------------------

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    async def ban(self, ctx: commands.Context, member: discord.Member, *, motivo: str = "Sin motivo especificado"):
        hierarchy_error = self._hierarchy_ok(ctx, member)
        if hierarchy_error:
            await ctx.reply(embed=self._error_embed(hierarchy_error))
            return

        try:
            embed_dm = discord.Embed(
                title=f"🔨 Fuiste baneado de {ctx.guild.name}",
                description=motivo,
                color=discord.Color.red(),
            )
            await member.send(embed=embed_dm)
        except discord.Forbidden:
            pass

        await ctx.guild.ban(member, reason=f"{ctx.author}: {motivo}")
        await ctx.reply(embed=self._success_embed(f"{member.mention} fue baneado.\n**Motivo:** {motivo}"))

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    async def unban(self, ctx: commands.Context, user_id: int):
        try:
            await ctx.guild.unban(discord.Object(id=user_id), reason=f"Desbaneado por {ctx.author}")
        except discord.NotFound:
            await ctx.reply(embed=self._error_embed("Ese usuario no está baneado en este servidor."))
            return

        await self._remove_tempban_record(ctx.guild.id, user_id)
        await ctx.reply(embed=self._success_embed(f"El usuario con ID `{user_id}` fue desbaneado."))

    @commands.command(name="tempban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    async def tempban(self, ctx: commands.Context, member: discord.Member, motivo: str, tiempo: str):
        hierarchy_error = self._hierarchy_ok(ctx, member)
        if hierarchy_error:
            await ctx.reply(embed=self._error_embed(hierarchy_error))
            return

        delta = parse_duration(tiempo)
        if delta is None:
            await ctx.reply(
                embed=self._error_embed(
                    "Duración inválida. Usá un formato como `10m`, `2h`, `1d12h` (s/m/h/d/w)."
                )
            )
            return

        unban_at = time.time() + delta.total_seconds()

        try:
            embed_dm = discord.Embed(
                title=f"⏳ Fuiste baneado temporalmente de {ctx.guild.name}",
                description=f"{motivo}\n\nDuración: {format_duration(delta)}",
                color=discord.Color.red(),
            )
            await member.send(embed=embed_dm)
        except discord.Forbidden:
            pass

        await ctx.guild.ban(member, reason=f"{ctx.author}: {motivo} (tempban {format_duration(delta)})")

        def mutator(data: dict) -> dict:
            entries = [e for e in data.get("entries", []) if e["user_id"] != member.id]
            entries.append({"user_id": member.id, "unban_at": unban_at, "reason": motivo})
            return {"entries": entries}

        await update_guild_data(TEMPBANS_STORE, ctx.guild.id, mutator)
        self._schedule_tempban_expiry(ctx.guild.id, member.id, unban_at)

        await ctx.reply(
            embed=self._success_embed(
                f"{member.mention} fue baneado temporalmente por {format_duration(delta)}.\n**Motivo:** {motivo}"
            )
        )

    # ------------------------------------------------------------------
    # Mute / Unmute
    # ------------------------------------------------------------------

    @commands.command(name="mute")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    async def mute(self, ctx: commands.Context, member: discord.Member, *, motivo: str = "Sin motivo especificado"):
        hierarchy_error = self._hierarchy_ok(ctx, member)
        if hierarchy_error:
            await ctx.reply(embed=self._error_embed(hierarchy_error))
            return

        role = await self._get_muted_role(ctx.guild)
        if role in member.roles:
            await ctx.reply(embed=self._error_embed(f"{member.mention} ya está muteado."))
            return

        await member.add_roles(role, reason=f"{ctx.author}: {motivo}")

        try:
            embed_dm = discord.Embed(
                title=f"🔇 Fuiste muteado en {ctx.guild.name}",
                description=motivo,
                color=discord.Color.greyple(),
            )
            await member.send(embed=embed_dm)
        except discord.Forbidden:
            pass

        await ctx.reply(embed=self._success_embed(f"{member.mention} fue muteado.\n**Motivo:** {motivo}"))

    @commands.command(name="unmute")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    async def unmute(self, ctx: commands.Context, member: discord.Member):
        role = await self._get_muted_role(ctx.guild)
        if role not in member.roles:
            await ctx.reply(embed=self._error_embed(f"{member.mention} no está muteado."))
            return

        await member.remove_roles(role, reason=f"Desmuteado por {ctx.author}")
        await ctx.reply(embed=self._success_embed(f"{member.mention} fue desmuteado."))

    # ------------------------------------------------------------------
    # Lock / Unlock
    # ------------------------------------------------------------------

    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @commands.guild_only()
    async def lock(
        self,
        ctx: commands.Context,
        canal: discord.TextChannel | None = None,
        tiempo: str | None = None,
    ):
        channel = canal or ctx.channel
        delta = None
        if tiempo:
            delta = parse_duration(tiempo)
            if delta is None:
                await ctx.reply(
                    embed=self._error_embed(
                        "Duración inválida. Usá un formato como `10m`, `2h`, `1d` (s/m/h/d/w), o dejalo vacío para bloquear indefinidamente."
                    )
                )
                return

        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(
            ctx.guild.default_role, overwrite=overwrite, reason=f"Bloqueado por {ctx.author}"
        )

        if delta:
            await ctx.reply(
                embed=self._success_embed(
                    f"{channel.mention} fue bloqueado por {format_duration(delta)}."
                )
            )
            await asyncio.sleep(delta.total_seconds())
            fresh = ctx.guild.get_channel(channel.id)
            if fresh is not None:
                ow = fresh.overwrites_for(ctx.guild.default_role)
                if ow.send_messages is False:
                    ow.send_messages = None
                    await fresh.set_permissions(
                        ctx.guild.default_role, overwrite=ow, reason="Bloqueo temporal expirado"
                    )
                    await fresh.send(embed=self._success_embed("El bloqueo temporal expiró. El canal fue desbloqueado."))
        else:
            await ctx.reply(embed=self._success_embed(f"{channel.mention} fue bloqueado."))

    @commands.command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @commands.guild_only()
    async def unlock(self, ctx: commands.Context, canal: discord.TextChannel | None = None):
        channel = canal or ctx.channel
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(
            ctx.guild.default_role, overwrite=overwrite, reason=f"Desbloqueado por {ctx.author}"
        )
        await ctx.reply(embed=self._success_embed(f"{channel.mention} fue desbloqueado."))

    # ------------------------------------------------------------------
    # Manejo de errores
    # ------------------------------------------------------------------

    @warn.error
    @warns.error
    @delwarn.error
    @ban.error
    @unban.error
    @tempban.error
    @mute.error
    @unmute.error
    @lock.error
    @unlock.error
    async def moderation_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply(embed=self._error_embed("No tenés permisos para usar este comando."))
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.reply(embed=self._error_embed("No tengo los permisos necesarios para hacer eso."))
        elif isinstance(error, commands.MemberNotFound):
            await ctx.reply(embed=self._error_embed("No se encontró a ese usuario en el servidor."))
        elif isinstance(error, commands.ChannelNotFound):
            await ctx.reply(embed=self._error_embed("No se encontró ese canal."))
        elif isinstance(error, commands.BadArgument):
            await ctx.reply(embed=self._error_embed("Parámetros inválidos. Revisá el uso del comando."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(embed=self._error_embed(f"Falta un parámetro: `{error.param.name}`."))
        elif isinstance(error, discord.Forbidden):
            await ctx.reply(embed=self._error_embed("No tengo permisos suficientes (revisá la jerarquía de roles)."))
        else:
            raise error


async def get_all_guild_tempbans(bot: commands.Bot) -> dict[int, list[dict]]:
    from utils.storage import get_all_guild_data

    raw = await get_all_guild_data(TEMPBANS_STORE)
    result: dict[int, list[dict]] = {}
    for guild_id_str, data in raw.items():
        entries = data.get("entries", [])
        if entries:
            result[int(guild_id_str)] = entries
    return result


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
