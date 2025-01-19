import dofusdude
import discord
from dofusdude.rest import ApiException
from redbot.core import commands, Config
from discord.ext import tasks
from datetime import datetime, timedelta, timezone

class Dofusalmanax(commands.Cog):
    """A cog to fetch and send Almanax data daily using the Dofus Dude API."""

    def __init__(self, bot):
        self.bot = bot
        self.configuration = dofusdude.Configuration(
            host="https://api.dofusdu.de"
        )
        self.config = Config.get_conf(self, identifier=47294748274, force_registration=True)
        self.config.register_global(
            selected_language="es",
            almanax_role=None,
            target_channel=None,
            warning_hours=0  # Default: No warning
        )
        self.selected_language = "es"
        self.almanax_role = None
        self.target_channel = None
        self.warning_hours = 0

        # Start the loops
        self.almanax_loop.start()
        self.warning_loop.start()

    async def cog_load(self):
        """Load the stored settings when the cog is loaded."""
        self.selected_language = await self.config.selected_language()
        self.almanax_role = await self.config.almanax_role()
        self.target_channel = await self.config.target_channel()
        self.warning_hours = await self.config.warning_hours()

    async def cog_unload(self):
        """Stop the loops when the cog is unloaded."""
        self.almanax_loop.cancel()
        self.warning_loop.cancel()

    @commands.guildowner()
    @commands.command()
    async def almanaxrole(self, ctx, role: discord.Role):
        """
        Set the role to be mentioned in Almanax messages.
        """
        await self.config.almanax_role.set(role.name)
        self.almanax_role = role.name
        await ctx.send(f"The role `{role.name}` has been set for Almanax notifications.")

    @commands.guildowner()
    @commands.command()
    async def almanaxchannel(self, ctx, channel: discord.TextChannel):
        """
        Set the channel where Almanax messages will be sent.
        """
        await self.config.target_channel.set(channel.id)
        self.target_channel = channel.id

        # Translation dictionary
        translations = {
            "en": "The channel {channel} has been set for Almanax messages.",
            "es": "El canal {channel} ha sido configurado para mensajes del Almanax.",
            "fr": "Le canal {channel} a été défini pour les messages de l'Almanax.",
            "de": "Der Kanal {channel} wurde für Almanax-Nachrichten festgelegt.",
            "pt": "O canal {channel} foi definido para mensagens do Almanax."
        }

        # Get the translation and send the message
        message = translations.get(self.selected_language, translations["en"]).format(channel=channel.mention)
        await ctx.send(message)

    @commands.admin()
    @commands.command()
    async def almanaxwarning(self, ctx, hours: int):
        """
        Set how many hours in advance to warn users about the Almanax closing.
        """
        if hours < 0:
            await ctx.send("Hours must be a positive number.")  # No need for i18n here
            return

        await self.config.warning_hours.set(hours)
        self.warning_hours = hours

        # Translation dictionary
        translations = {
            "en": "Warning set for {hours} hour(s) before Almanax closes.",
            "es": "Advertencia configurada para {hours} hora(s) antes de que cierre el Almanax.",
            "fr": "Avertissement configuré pour {hours} heure(s) avant la fermeture de l'Almanax.",
            "de": "Warnung eingestellt für {hours} Stunde(n) bevor der Almanax schließt.",
            "pt": "Aviso definido para {hours} hora(s) antes do fechamento do Almanax."
        }

        # Get the translation and send the message
        message = translations.get(self.selected_language, translations["en"]).format(hours=hours)
        await ctx.send(message)
        
    @commands.command()
    async def almanax(self, ctx, date: str):
        """
        Fetch the Almanax data for the specified date (yyyy-mm-dd).
        """
        # Validate the date format
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            # Translation dictionary for invalid date format error
            translations = {
                "en": "Invalid date format. Please use yyyy-mm-dd.",
                "es": "Formato de fecha inválido. Por favor, use aaaa-mm-dd.",
                "fr": "Format de date invalide. Veuillez utiliser aaaa-mm-jj.",
                "de": "Ungültiges Datumsformat. Bitte verwenden Sie jjjj-mm-tt.",
                "pt": "Formato de data inválido. Por favor, use aaaa-mm-dd."
            }
            message = translations.get(self.selected_language, translations["en"])
            await ctx.send(message)
            return

        # Use the shared send_almanax_message method
        try:
            await self.send_almanax_message(ctx.channel, date, mention_role=False)
        except ApiException as e:
            # Translation dictionary for API error
            translations = {
                "en": "Error when fetching Almanax data: {error}",
                "es": "Error al obtener los datos del Almanax: {error}",
                "fr": "Erreur lors de la récupération des données de l'Almanax : {error}",
                "de": "Fehler beim Abrufen der Almanax-Daten: {error}",
                "pt": "Erro ao buscar os dados do Almanax: {error}"
            }
            message = translations.get(self.selected_language, translations["en"]).format(error=e)
            await ctx.send(message)

    @tasks.loop(seconds=60)
    async def almanax_loop(self):
        """Send the Almanax message daily at midnight (UTC+1)."""
        now = datetime.now(timezone.utc) + timedelta(hours=1)  # Adjust UTC to UTC+1 (France)
        if now.hour == 0 and now.minute == 0:  # Check if it's midnight in UTC+1
            if not self.target_channel:
                return  # Skip if no target channel is set

            # Get the channel object
            channel = self.bot.get_channel(self.target_channel)
            if not channel:
                print(f"Error: Target channel with ID {self.target_channel} not found.")
                return

            # Call send_almanax_message with both channel and date
            await self.send_almanax_message(channel, now.strftime('%Y-%m-%d'))


    @tasks.loop(seconds=60)
    async def warning_loop(self):
        """Send a warning message before the Almanax closes."""
        now = datetime.now(timezone.utc) + timedelta(hours=1)  # Adjust UTC to UTC+1 (France)
        closing_time = now.replace(hour=23, minute=59, second=0, microsecond=0)  # Almanax closes at 23:59
        warning_time = closing_time - timedelta(hours=self.warning_hours)

        if now >= warning_time and now < warning_time + timedelta(minutes=1):  # Trigger warning
            await self.send_almanax_warning_message(now.strftime('%Y-%m-%d'))

    async def send_almanax_message(self, channel, date: str, mention_role: bool = True):
        """
        Shared method to send an Almanax message for a given date.
        """
        if not channel:
            return

        # Fetch Almanax data
        with dofusdude.ApiClient(self.configuration) as api_client:
            api_instance = dofusdude.AlmanaxApi(api_client)
            language = self.selected_language

            api_response = api_instance.get_almanax_date(language, date)
            bonus_description = api_response.bonus.description
            bonus_type = api_response.bonus.type.name
            tribute_name = api_response.tribute.item.name
            tribute_quantity = api_response.tribute.quantity
            tribute_image_url = api_response.tribute.item.image_urls.sd
            reward_kamas = api_response.reward_kamas

            # Create the embed
            embed = discord.Embed(
                title=f"Almanax for {date}",
                color=discord.Color.blue()
            )
            embed.add_field(name=f"💫 {bonus_type}", value=bonus_description, inline=False)
            embed.add_field(name="🎁 Tribute", value=f"{tribute_quantity} {tribute_name}", inline=True)
            embed.add_field(name="💰 Reward Kamas", value=f"{reward_kamas:,}", inline=True)
            embed.set_thumbnail(url=tribute_image_url)

            # Send the message
            if mention_role and self.almanax_role:
                role = discord.utils.get(channel.guild.roles, name=self.almanax_role)
                if role:
                    await channel.send(f"{role.mention}", embed=embed)
                    return
            await channel.send(embed=embed)

    async def send_almanax_warning_message(self, date: str):
        """Send the warning message for the Almanax closing with i18n support."""
        if not self.target_channel:
            return

        # Translation dictionary
        translations = {
            "en": "⚠️ The Almanax will close in {hours} hour(s). Complete it soon!",
            "es": "⚠️ El Almanax cerrará en {hours} hora(s). ¡Complétalo pronto!",
            "fr": "⚠️ L'Almanax fermera dans {hours} heure(s). Terminez-le bientôt !",
            "de": "⚠️ Der Almanax schließt in {hours} Stunde(n). Beenden Sie ihn bald!",
            "pt": "⚠️ O Almanax fechará em {hours} hora(s). Conclua em breve!"
        }

        # Get the translation for the selected language or default to English
        warning_message = translations.get(self.selected_language, translations["en"]).format(hours=self.warning_hours)

        # Send the warning message
        channel = self.bot.get_channel(self.target_channel)
        if channel:
            if self.almanax_role:
                role = discord.utils.get(channel.guild.roles, name=self.almanax_role)
                if role:
                    await channel.send(f"{role.mention} {warning_message}")
                else:
                    await channel.send(warning_message)
            else:
                await channel.send(warning_message)

    @almanax_loop.before_loop
    @warning_loop.before_loop
    async def before_loops(self):
        """Wait until the bot is ready before starting the loops."""
        await self.bot.wait_until_ready()

# Setup function to add the cog
def setup(bot):
    bot.add_cog(Dofusalmanax(bot))
