from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config

class Grokchat(commands.Cog):
    """Simple cog for chatting with Grok."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=29384703)
        self.default_global = {}
        self.default_guild = {}
        self.default_member = {}

        self.config.register_global(**self.default_global)
        self.config.register_guild(**self.default_guild)
        self.config.register_member(**self.default_member)

    @commands.command()
    async def example(self, ctx: commands.Context):
        """An example command."""
        await ctx.send("This is an example command!")

    async def cog_unload(self):
        pass

async def setup(bot: Red):
    cog = Grokchat(bot)
    await bot.add_cog(cog)