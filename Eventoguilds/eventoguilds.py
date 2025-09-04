import re
import time
from typing import Any, Dict, Optional

import discord

from redbot.core import Config, checks, commands
from redbot.core.bot import Red

EMOJI_MENTION_RE = re.compile(r"^<a?:(?P<name>[^:]+):(?P<id>\d+)>$")


class Eventoguilds(commands.Cog):
    """Roles por reacción con elección única PER CANAL y bloqueo permanente por canal."""

    __author__ = "GFerreiroS"
    __version__ = "1.3.1"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567890, force_registration=True
        )
        # watchers: { message_id(str): {channel_id, role_id, emoji_*, created_*} }
        # chosen_by_channel: { channel_id(str): { user_id(str): {role_id, message_id, timestamp} } }
        # chosen_users: compat con versiones <= 1.2.x (registro global antiguo, ahora no se usa)
        self.config.register_guild(watchers={}, chosen_by_channel={}, chosen_users={})

    # ---------- Helpers ----------

    def _parse_emoji_input(self, guild: discord.Guild, raw: str) -> Dict[str, Any]:
        raw = raw.strip()
        m = EMOJI_MENTION_RE.match(raw)
        if m:
            name = m.group("name")
            eid = int(m.group("id"))
            animated = raw.startswith("<a:")
            return {
                "type": "custom",
                "id": eid,
                "name": name,
                "unicode": None,
                "animated": animated,
            }

        if raw.isdigit():
            eid = int(raw)
            eobj = discord.utils.get(guild.emojis, id=eid)
            return {
                "type": "custom",
                "id": eid,
                "name": eobj.name if eobj else None,
                "unicode": None,
                "animated": getattr(eobj, "animated", False),
            }

        if raw.startswith(":") and raw.endswith(":") and len(raw) > 2:
            name = raw[1:-1]
            matches = [e for e in guild.emojis if e.name == name]
            if not matches:
                raise commands.BadArgument(
                    "No encontré un emoji con ese nombre en este servidor."
                )
            if len(matches) > 1:
                raise commands.BadArgument(
                    "Hay varios emojis con ese nombre. Usa `<:nombre:id>` o el ID."
                )
            eobj = matches[0]
            return {
                "type": "custom",
                "id": eobj.id,
                "name": eobj.name,
                "unicode": None,
                "animated": eobj.animated,
            }

        # Unicode
        return {
            "type": "unicode",
            "id": None,
            "name": None,
            "unicode": raw,
            "animated": False,
        }

    def _reaction_token_for_add(
        self, guild: discord.Guild, data: Dict[str, Any]
    ) -> str:
        if data["type"] == "unicode":
            return data["unicode"]
        name = data["name"] or "emoji"
        prefix = "a" if data.get("animated") else ""
        return f"<{prefix}:{name}:{data['id']}>"

    def _emoji_matches_payload(
        self, stored: Dict[str, Any], payload: discord.RawReactionActionEvent
    ) -> bool:
        if stored["type"] == "unicode":
            return payload.emoji.id is None and str(payload.emoji) == stored["unicode"]
        if stored["id"] is not None:
            return payload.emoji.id == stored["id"]
        return payload.emoji.name == (stored.get("name") or "")

    async def _get_guild_watchers(self, guild: discord.Guild) -> Dict[str, Any]:
        return await self.config.guild(guild).watchers()

    # ---------- Commands ----------

    @commands.command(name="eventorol")  # type: ignore
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def eventorol_create(
        self, ctx: commands.Context, role: discord.Role, emoji: str, *, mensaje: str
    ):
        """
        Crea un mensaje de reacción que asigna `role` al reaccionar con `emoji`.
        Borra el mensaje del comando; solo queda el mensaje objetivo.
        """
        guild = ctx.guild
        assert guild is not None

        me: discord.Member = guild.me  # type: ignore
        # Permisos necesarios
        if not me.guild_permissions.manage_roles:
            try:
                await ctx.author.send(
                    "No puedo asignar roles: me falta **Gestionar roles** en ese servidor."
                )
            except Exception:
                pass
            return

        if role >= me.top_role:
            try:
                await ctx.author.send(
                    f"No puedo asignar {role.name}: está por encima (o igual) de mi rol más alto."
                )
            except Exception:
                pass
            return

        # Parseo del emoji
        try:
            em = self._parse_emoji_input(guild, emoji)
        except commands.BadArgument as e:
            try:
                await ctx.author.send(f"Emoji inválido: {e}")
            except Exception:
                pass
            return

        # Unicidad global de rol (evita duplicados del mismo rol en varios mensajes)
        async with self.config.guild(guild).watchers() as watchers:
            if any(int(w["role_id"]) == role.id for w in watchers.values()):
                try:
                    await ctx.author.send(
                        "Ya existe un mensaje que asigna **ese mismo rol**. Elimina el anterior primero."
                    )
                except Exception:
                    pass
                return

            # Publica mensaje objetivo
            msg = await ctx.send(mensaje)
            try:
                await msg.add_reaction(self._reaction_token_for_add(guild, em))
            except discord.HTTPException:
                try:
                    await msg.delete()
                except Exception:
                    pass
                try:
                    await ctx.author.send(
                        "No pude añadir la reacción (emoji no disponible/permisos)."
                    )
                except Exception:
                    pass
                return

            watchers[str(msg.id)] = {
                "channel_id": msg.channel.id,
                "role_id": role.id,
                "emoji_id": em["id"],
                "emoji_name": em["name"],
                "emoji_unicode": em["unicode"],
                "animated": em["animated"],
                "created_by": ctx.author.id,
                "created_at": int(time.time()),
            }

        # Borra el mensaje del comando
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            try:
                await ctx.author.send(
                    "Creado el mensaje de reacción, pero no pude borrar tu comando (me falta **Gestionar mensajes**)."
                )
            except Exception:
                pass
        except Exception:
            pass

    @commands.group(name="eventorolcfg", invoke_without_command=True)  # type: ignore
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def eventorolcfg(self, ctx: commands.Context):
        """Admin: listar / eliminar / desbloquear / forzar / bloqueados / limpiar global antiguo."""
        await ctx.send_help(ctx.command)

    @eventorolcfg.command(name="list")  # type: ignore
    async def eventorol_list(self, ctx: commands.Context):
        """Lista mensajes configurados en este servidor."""
        watchers = await self._get_guild_watchers(ctx.guild)  # type: ignore
        if not watchers:
            return await ctx.send("No hay mensajes configurados.")
        lines = []
        for mid, w in watchers.items():
            role = ctx.guild.get_role(int(w["role_id"]))  # type: ignore
            url = f"https://discord.com/channels/{ctx.guild.id}/{w['channel_id']}/{mid}"  # type: ignore
            if w["emoji_id"]:
                prefix = "a" if w.get("animated") else ""
                e_disp = f"<{prefix}:{w.get('emoji_name', 'emoji')}:{w['emoji_id']}>"
            else:
                e_disp = w.get("emoji_unicode", "❓")
            chan = ctx.guild.get_channel(int(w["channel_id"]))  # type: ignore
            ch_disp = (
                f"en #{chan.name}"
                if isinstance(chan, discord.TextChannel)
                else f"(canal {w['channel_id']})"
            )
            r_disp = role.mention if role else f"(rol {w['role_id']})"
            lines.append(f"- **{mid}** {e_disp} → {r_disp} — {ch_disp} — [ir]({url})")
        msg = "\n".join(lines)
        for chunk in [msg[i : i + 1900] for i in range(0, len(msg), 1900)]:
            await ctx.send(chunk)

    @eventorolcfg.command(name="remove")  # type: ignore
    async def eventorol_remove(self, ctx: commands.Context, message_id_or_link: str):
        """Elimina la vinculación de un mensaje (no borra el mensaje)."""
        if "/" in message_id_or_link:
            mid = message_id_or_link.rstrip("/").split("/")[-1]
        else:
            mid = message_id_or_link
        if not mid.isdigit():
            return await ctx.send(
                "Debes proporcionar un **ID** de mensaje válido o su **enlace**."
            )
        async with self.config.guild(ctx.guild).watchers() as watchers:  # type: ignore
            if mid not in watchers:
                return await ctx.send(
                    "No encuentro ningún mensaje configurado con ese ID."
                )
            watchers.pop(mid)
        await ctx.send(f"Vinculación eliminada para el mensaje `{mid}`.")

    @eventorolcfg.command(name="unlock")  # type: ignore
    @checks.admin_or_permissions(manage_guild=True)
    async def eventorol_unlock(
        self,
        ctx: commands.Context,
        member: discord.Member,
        channel: Optional[discord.TextChannel] = None,
    ):
        """Desbloquea a un usuario **en un canal** (no cambia roles).
        Si no indicas canal, usa el canal actual.
        """
        guild = ctx.guild
        assert guild is not None
        channel = channel or ctx.channel  # type: ignore
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Debes indicar un canal de texto.")

        async with self.config.guild(guild).chosen_by_channel() as cb:
            ch = cb.get(str(channel.id), {})
            if str(member.id) in ch:
                ch.pop(str(member.id))
                await ctx.send(
                    f"🔓 {member.mention} desbloqueado en {channel.mention}."
                )
            else:
                await ctx.send(f"Ese usuario no estaba bloqueado en {channel.mention}.")

    @eventorolcfg.command(name="force")  # type: ignore
    @checks.admin_or_permissions(manage_guild=True, manage_roles=True)
    async def eventorol_force(
        self, ctx: commands.Context, member: discord.Member, role: discord.Role
    ):
        """Asigna `role` si está gestionado por un watcher y bloquea al usuario **en el canal de ese watcher**."""
        guild = ctx.guild
        assert guild is not None

        watchers = await self._get_guild_watchers(guild)
        # Busca el watcher de ese rol (unicidad global de rol)
        target = None
        for w in watchers.values():
            if int(w["role_id"]) == role.id:
                target = w
                break
        if not target:
            return await ctx.send(
                "Ese rol **no** está gestionado por los mensajes de `!eventorol`."
            )

        channel_id = int(target["channel_id"])
        channel = guild.get_channel(channel_id)
        me: Optional[discord.Member] = guild.me  # type: ignore
        if not me or not me.guild_permissions.manage_roles or role >= me.top_role:
            return await ctx.send("No tengo permisos o jerarquía para asignar ese rol.")

        try:
            await member.add_roles(role, reason="Eventoguilds: force assign")
        except discord.Forbidden:
            return await ctx.send("No puedo asignar ese rol (permisos).")
        except discord.HTTPException:
            return await ctx.send("Fallo de API al asignar el rol.")

        async with self.config.guild(guild).chosen_by_channel() as cb:
            ch = cb.setdefault(str(channel_id), {})
            ch[str(member.id)] = {
                "role_id": role.id,
                "message_id": 0,  # 0 = forzado
                "timestamp": int(time.time()),
            }

        ch_disp = (
            channel.mention
            if isinstance(channel, discord.TextChannel)
            else f"(canal {channel_id})"
        )
        await ctx.send(
            f"✅ {member.mention} recibió {role.mention} y queda **bloqueado** en {ch_disp}."
        )

    @eventorolcfg.command(name="locked")  # type: ignore
    async def eventorol_locked(
        self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None
    ):
        """Lista bloqueados **en un canal** (si no indicas, canal actual)."""
        guild = ctx.guild
        assert guild is not None
        channel = channel or ctx.channel  # type: ignore
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("Debes indicar un canal de texto.")

        cb = await self.config.guild(guild).chosen_by_channel()
        ch = cb.get(str(channel.id), {})
        if not ch:
            return await ctx.send(f"No hay usuarios bloqueados en {channel.mention}.")
        lines = []
        for uid, info in ch.items():
            member = guild.get_member(int(uid))
            role = guild.get_role(int(info.get("role_id", 0)))
            who = member.mention if member else f"`{uid}`"
            rdisp = role.mention if role else f"(rol {info.get('role_id')})"
            ts = info.get("timestamp")
            when = f"<t:{ts}:R>" if ts else ""
            lines.append(f"- {who} → {rdisp} {when}")
        msg = "\n".join(lines)
        for chunk in [msg[i : i + 1900] for i in range(0, len(msg), 1900)]:
            await ctx.send(chunk)

    @eventorolcfg.command(name="lockedall")  # type: ignore
    async def eventorol_locked_all(self, ctx: commands.Context):
        """Lista todos los bloqueados agrupados por canal."""
        guild = ctx.guild
        assert guild is not None
        cb = await self.config.guild(guild).chosen_by_channel()
        if not cb:
            return await ctx.send("No hay usuarios bloqueados en ningún canal.")
        pieces = []
        for ch_id, users in cb.items():
            chan = guild.get_channel(int(ch_id))
            header = (
                chan.mention
                if isinstance(chan, discord.TextChannel)
                else f"(canal {ch_id})"
            )
            if not users:
                continue
            lines = []
            for uid, info in users.items():
                member = guild.get_member(int(uid))
                role = guild.get_role(int(info.get("role_id", 0)))
                who = member.mention if member else f"`{uid}`"
                rdisp = role.mention if role else f"(rol {info.get('role_id')})"
                ts = info.get("timestamp")
                when = f"<t:{ts}:R>" if ts else ""
                lines.append(f"- {who} → {rdisp} {when}")
            pieces.append(f"**{header}**\n" + "\n".join(lines))
        text = "\n\n".join(pieces)
        for chunk in [text[i : i + 1900] for i in range(0, len(text), 1900)]:
            await ctx.send(chunk)

    @eventorolcfg.command(name="clearglobal")  # type: ignore
    async def eventorol_clear_global(self, ctx: commands.Context):
        """Elimina el registro antiguo **global** de bloqueos (v1.2.x). No afecta a los bloqueos por canal."""
        # Como registramos chosen_users = {}, .clear() lo deja vacío (compat)
        await self.config.guild(ctx.guild).chosen_users.clear()  # type: ignore
        await ctx.send(
            "🧹 Registro global antiguo `chosen_users` eliminado. Los bloqueos por canal permanecen."
        )

    # ---------- Listeners ----------

    @commands.Cog.listener("on_raw_reaction_add")
    async def _on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None or payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        watchers = await self._get_guild_watchers(guild)
        w = watchers.get(str(payload.message_id))
        if not w:
            return

        # Emoji correcto para ese watcher
        if not self._emoji_matches_payload(
            {
                "type": "unicode" if w["emoji_id"] is None else "custom",
                "id": w["emoji_id"],
                "name": w.get("emoji_name"),
                "unicode": w.get("emoji_unicode"),
                "animated": w.get("animated", False),
            },
            payload,
        ):
            return

        # Miembro
        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(
                payload.user_id
            )
        except discord.HTTPException:
            return
        if member.bot:
            return

        role = guild.get_role(int(w["role_id"]))
        if role is None:
            return

        channel_id = int(w["channel_id"])

        # ¿Ya bloqueado en ESTE canal?
        cb = await self.config.guild(guild).chosen_by_channel()
        chlocks = cb.get(str(channel_id), {})
        if str(member.id) in chlocks:
            return  # ya eligió en este canal

        # ¿Ya tiene algún rol de watchers en ESTE canal?
        watcher_role_ids_in_channel = {
            int(x["role_id"])
            for x in watchers.values()
            if int(x["channel_id"]) == channel_id
        }
        existing_in_channel = next(
            (r.id for r in member.roles if r.id in watcher_role_ids_in_channel), None
        )
        if existing_in_channel is not None:
            # Solo bloquear (coherencia)
            async with self.config.guild(guild).chosen_by_channel() as cb_edit:
                ch = cb_edit.setdefault(str(channel_id), {})
                ch[str(member.id)] = {
                    "role_id": existing_in_channel,
                    "message_id": payload.message_id,
                    "timestamp": int(time.time()),
                }
            return

        # Permisos
        me: Optional[discord.Member] = guild.me
        if not me or not me.guild_permissions.manage_roles or role >= me.top_role:
            return

        # Asignar y BLOQUEAR EN ESTE CANAL
        try:
            await member.add_roles(
                role, reason=f"Eventoguilds: reacción en {payload.message_id}"
            )
        except (discord.Forbidden, discord.HTTPException):
            return

        async with self.config.guild(guild).chosen_by_channel() as cb_edit:
            ch = cb_edit.setdefault(str(channel_id), {})
            ch[str(member.id)] = {
                "role_id": role.id,
                "message_id": payload.message_id,
                "timestamp": int(time.time()),
            }

    # No quitamos rol al retirar reacción
    @commands.Cog.listener("on_raw_reaction_remove")
    async def _on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        return

    def format_help_for_context(self, ctx: commands.Context) -> str:
        pre = super().format_help_for_context(ctx)
        return f"{pre}\n\nAutor: {self.__author__}\nVersión: {self.__version__}"
