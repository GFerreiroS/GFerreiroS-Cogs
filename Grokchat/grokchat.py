from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config
from openai import OpenAI

class Grokchat(commands.Cog):
    """Simple cog for chatting with Grok."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=29384703)
        self.default_global = {"api_key": ""}
        self.config.register_global(**self.default_global)
        self.setcontext = {
            "You are mean to anybody to talks to you."
            "If they ask something just answer with the meanest thing you can think of."
            "Insults are encouraged."
            "And in the end you respond with the answer to the question the meanest way."
            "You respond will respond with the same language as the user."
        }
        self.client = None
    
    async def initialize_client(self):
        """Initialize the OpenAI client using the stored API key."""
        api_key = await self.config.api_key()
        if api_key:
            self.client = OpenAI(
                api_key=api_key,
                base_url="https://api.x.ai/v1",
            )
            
    @commands.guildowner()
    @commands.command()
    async def grokapikey(self, ctx, *, api_key: str):
        """Set the API key for the OpenAI client."""
        await self.config.api_key.set(api_key)
        await self.initialize_client()
        await ctx.send("API key has been updated.")

    @commands.command()
    async def grokcontext(self, ctx, *, userContext: str):
        self.setcontext = userContext
        await ctx.send("Context added.")
        return
    
    @commands.command()
    async def grokchat(self, ctx, *, userText: str):
        """Chat with Grok."""
        if not self.client:
            await self.initialize_client()

        if not self.client:
            await ctx.send("API key is not set. Use `!grokapikey` to set it.")
            return

        try:
            completion = self.client.chat.completions.create(
                model="grok-2-latest",
                messages=[
                    {"role": "system", "content": f"{self.setcontext}"},
                    {"role": "user", "content": f"{userText}"},
                ],
            )
            await ctx.send(completion.choices[0].message.content)
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")

    async def cog_unload(self):
        pass

async def setup(bot: Red):
    cog = Grokchat(bot)
    await cog.initialize_client()
    await bot.add_cog(cog)