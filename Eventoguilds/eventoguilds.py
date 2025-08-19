import re
import time
from typing import Any, Dict, Optional

import discord

from redbot.core import Config, checks, commands
from redbot.core.bot import Red

EMOJI_MENTION_RE = re.compile(r"^<a?:(?P<name>[^:]+):(?P<id>\d+)>$")


class Eventoguilds(commands.Cog):
    """Asignación de roles por reacción (un único rol por usuario, bloqueo permanente)."""

    __author__ = "GFerreiroS"
    __version__ = "1.2.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567890, force_registration=True
        )
        # watchers: { message_id(str): {...} }
        # chosen_users: { user_id(str): {role_id:int, message_id:int, timestamp:int} }
        self.config.register_guild(watchers={}, chosen_users={})

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

        # Emoji Unicode
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

    @commands.command(name="eventorol")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def eventorol_create(
        self, ctx: commands.Context, role: discord.Role, emoji: str, *, mensaje: str
    ):
        """
        Crea un mensaje de reacción que asigna `role` cuando se reacciona con `emoji`.

        Uso:
          !eventorol @Rol <:nombre:id> Dale a la reacción para asignarte este rol
          !eventorol 1407416963696955392 :helheim: Dale a la reacción...
          !eventorol @Rol 👍 Texto...
        """
        guild = ctx.guild
        assert guild is not None

        me: discord.Member = guild.me  # type: ignore
        # Permisos necesarios
        if not me.guild_permissions.manage_roles:
            # Sin mensaje en canal; avisa por DM
            try:
                await ctx.author.send(
                    "No puedo asignar roles: me falta el permiso **Gestionar roles** en ese servidor."
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
            # Avisa por DM; no dejes mensajes en el canal
            try:
                await ctx.author.send(f"Emoji inválido: {e}")
            except Exception:
                pass
            return

        # Unicidad de rol
        async with self.config.guild(guild).watchers() as watchers:
            if any(int(w["role_id"]) == role.id for w in watchers.values()):
                try:
                    await ctx.author.send(
                        "Ya existe un mensaje que asigna **ese mismo rol**. Elimina el anterior primero."
                    )
                except Exception:
                    pass
                return

            # Publica el mensaje "limpio" y añade la reacción
            msg = await ctx.send(mensaje)
            try:
                await msg.add_reaction(self._reaction_token_for_add(guild, em))
            except discord.HTTPException:
                # Si falla, borra el mensaje recién creado y avisa por DM
                try:
                    await msg.delete()
                except Exception:
                    pass
                try:
                    await ctx.author.send(
                        "No pude añadir la reacción (¿emoji no disponible/permiso insuficiente?)."
                    )
                except Exception:
                    pass
                return

            # Guarda el watcher SOLO si todo salió bien
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

        # Borra el mensaje del comando para que solo quede el mensaje objetivo
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            # Falta "Gestionar mensajes": no podemos borrar el mensaje del usuario.
            # No escribimos nada en el canal; como fallback, avisa por DM.
            try:
                await ctx.author.send(
                    "Creado el mensaje de reacción, pero no pude borrar tu comando (me falta **Gestionar mensajes**)."
                )
            except Exception:
                pass
        except Exception:
            pass

        # No enviamos confirmación en el canal.
        return

    @commands.group(name="eventorolcfg", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def eventorolcfg(self, ctx: commands.Context):
        """Comandos de administración: listar / eliminar / desbloquear / forzar / bloqueados."""
        await ctx.send_help(ctx.command)

    @eventorolcfg.command(name="list")
    async def eventorol_list(self, ctx: commands.Context):
        """Lista los mensajes configurados en este servidor."""
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
            r_disp = role.mention if role else f"(rol {w['role_id']})"
            lines.append(f"- **{mid}** {e_disp} → {r_disp} — [ir al mensaje]({url})")
        msg = "\n".join(lines)
        for chunk in [msg[i : i + 1900] for i in range(0, len(msg), 1900)]:
            await ctx.send(chunk)

    @eventorolcfg.command(name="remove")
    async def eventorol_remove(self, ctx: commands.Context, message_id_or_link: str):
        """Elimina la vinculación de un mensaje (no borra el mensaje de Discord)."""
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

    @eventorolcfg.command(name="unlock")
    @checks.admin_or_permissions(manage_guild=True)
    async def eventorol_unlock(self, ctx: commands.Context, member: discord.Member):
        """Desbloquea a un usuario para que pueda elegir de nuevo (no modifica roles)."""
        async with self.config.guild(ctx.guild).chosen_users() as chosen:  # type: ignore
            if str(member.id) in chosen:
                chosen.pop(str(member.id))
                await ctx.send(f"🔓 {member.mention} ha sido **desbloqueado**.")
            else:
                await ctx.send("Ese usuario no estaba bloqueado.")

    @eventorolcfg.command(name="force")
    @checks.admin_or_permissions(manage_guild=True, manage_roles=True)
    async def eventorol_force(
        self, ctx: commands.Context, member: discord.Member, role: discord.Role
    ):
        """
        Fuerza asignar un rol gestionado por estos mensajes y deja al usuario bloqueado.
        """
        guild = ctx.guild
        assert guild is not None

        watchers = await self._get_guild_watchers(guild)
        watcher_role_ids = {int(x["role_id"]) for x in watchers.values()}
        if role.id not in watcher_role_ids:
            return await ctx.send(
                "Ese rol **no** está gestionado por los mensajes de `!eventorol`."
            )

        me: Optional[discord.Member] = guild.me  # type: ignore
        if not me or not me.guild_permissions.manage_roles or role >= me.top_role:
            return await ctx.send("No tengo permisos o jerarquía para asignar ese rol.")

        try:
            await member.add_roles(role, reason="Eventoguilds: force assign")
        except discord.Forbidden:
            return await ctx.send("No puedo asignar ese rol (permissions).")
        except discord.HTTPException:
            return await ctx.send("Fallo de API al asignar el rol.")

        # Bloquear
        async with self.config.guild(guild).chosen_users() as chosen:
            chosen[str(member.id)] = {
                "role_id": role.id,
                "message_id": 0,  # 0 = manual/forzado
                "timestamp": int(time.time()),
            }

        await ctx.send(
            f"✅ {member.mention} recibió {role.mention} y queda **bloqueado**."
        )

    @eventorolcfg.command(name="locked")
    @checks.admin_or_permissions(manage_guild=True)
    async def eventorol_locked(self, ctx: commands.Context):
        """Lista de usuarios bloqueados (han elegido ya un rol)."""
        chosen = await self.config.guild(ctx.guild).chosen_users()  # type: ignore
        if not chosen:
            return await ctx.send("No hay usuarios bloqueados.")
        lines = []
        for uid, info in chosen.items():
            member = ctx.guild.get_member(int(uid))  # type: ignore
            role = ctx.guild.get_role(int(info.get("role_id", 0)))  # type: ignore
            who = member.mention if member else f"`{uid}`"
            rdisp = role.mention if role else f"(rol {info.get('role_id')})"
            ts = info.get("timestamp")
            when = f"<t:{ts}:R>" if ts else ""
            lines.append(f"- {who} → {rdisp} {when}")
        msg = "\n".join(lines)
        for chunk in [msg[i : i + 1900] for i in range(0, len(msg), 1900)]:
            await ctx.send(chunk)

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

        # Coincide emoji?
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

        # ¿Ya bloqueado para siempre?
        chosen = await self.config.guild(guild).chosen_users()
        if str(member.id) in chosen:
            return  # Ignora nuevas elecciones para siempre

        role = guild.get_role(int(w["role_id"]))
        if role is None:
            return

        # ¿Ya tiene algún rol de watchers? (refuerzo)
        watcher_role_ids = {int(x["role_id"]) for x in watchers.values()}
        if any(r.id in watcher_role_ids for r in member.roles):
            # No asigna otro, pero además bloqueamos si no estaba (por coherencia)
            async with self.config.guild(guild).chosen_users() as chosen_edit:
                if str(member.id) not in chosen_edit:
                    chosen_edit[str(member.id)] = {
                        "role_id": next(
                            (r.id for r in member.roles if r.id in watcher_role_ids),
                            role.id,
                        ),
                        "message_id": payload.message_id,
                        "timestamp": int(time.time()),
                    }
            return

        # Permisos
        me: Optional[discord.Member] = guild.me
        if not me or not me.guild_permissions.manage_roles or role >= me.top_role:
            return

        # Asignar y bloquear
        try:
            await member.add_roles(
                role, reason=f"Eventoguilds: reacción en {payload.message_id}"
            )
        except (discord.Forbidden, discord.HTTPException):
            return

        async with self.config.guild(guild).chosen_users() as chosen_edit:
            chosen_edit[str(member.id)] = {
                "role_id": role.id,
                "message_id": payload.message_id,
                "timestamp": int(time.time()),
            }

    # No quitamos el rol al retirar la reacción
    @commands.Cog.listener("on_raw_reaction_remove")
    async def _on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        return

    def format_help_for_context(self, ctx: commands.Context) -> str:
        pre = super().format_help_for_context(ctx)
        return f"{pre}\n\nAutor: {self.__author__}\nVersión: {self.__version__}"

    async def cog_unload(self):
        pass
