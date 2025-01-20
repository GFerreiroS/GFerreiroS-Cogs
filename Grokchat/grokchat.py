import discord
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config
from openai import OpenAI

class Grokchat(commands.Cog):
    """Simple cog for chatting with Grok."""

    DEBUG = False
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=29384703)
        self.default_guild = {"api_key": ""}
        self.config.register_guild(**self.default_guild)
        self.setcontext = {
            "You are mean to anybody to talks to you."
            "If they ask something just answer with the meanest thing you can think of."
            "Insults are encouraged."
            "And in the end you respond with the answer to the question the meanest way."
            "You respond will respond with the same language as the user."
        }
        self.client = None
        self.bot.add_listener(self.on_message, "on_message")
    
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
    async def grokbullycontext(self, ctx, *, bullyContext: str):
        """Set a custom context for bullying a specific user."""
        await self.config.bully_context.set(bullyContext)
        await ctx.send("Bully context added.")

    @commands.command()
    async def grokbully(self, ctx, user: str):
        """Set a user to bully by ID or username."""
        # Try to resolve the user as an ID or username
        target_user = None

        # Check if it's a numeric ID
        if user.isdigit():
            target_user = ctx.guild.get_member(int(user))
        else:
            # Try to resolve by username or nickname
            target_user = discord.utils.find(
                lambda u: str(u) == user or u.name == user or u.display_name == user,
                ctx.guild.members,
            )

        if target_user:
            # Store the user's unique ID
            await self.config.bully_user.set(str(target_user.id))
            await ctx.send(f"{target_user.name} has been set as the target for bullying.")
        else:
            await ctx.send("User not found. Please provide a valid username or ID.")
        
    @commands.command()
    async def grokchat(self, ctx, *, userText: str):
        """Chat with Grok."""
        if not self.client:
            await self.initialize_client()

        if not self.client:
            await ctx.send("API key is not set. Use `!setapikey` to set it.")
            return

        bully_user = await self.config.bully_user()
        bully_context = await self.config.bully_context()

        # Check if the author's ID matches the stored bully user ID
        current_context = (
            bully_context if str(ctx.author.id) == bully_user else self.setcontext
        )

        try:
            # Show the typing indicator while waiting for the API response
            async with ctx.typing():
                completion = self.client.chat.completions.create(
                    model="grok-2-latest",
                    messages=[
                        {"role": "system", "content": f"{current_context}"},
                        {"role": "user", "content": f"{userText}"},
                    ],
                )
            await ctx.send(completion.choices[0].message.content)
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")

    async def on_message(self, message: discord.Message):
        """Respond automatically to bullied user's messages."""
        # Ignore messages from bots
        if message.author.bot:
            return

        # Check if the message is a command
        prefixes = await self.bot.get_valid_prefixes(message.guild)
        if any(message.content.startswith(prefix) for prefix in prefixes):
            return  # Let the command processor handle this message

        # Fetch bullied user and check if the message is from them
        bully_user = await self.config.bully_user()
        if str(message.author.id) == bully_user:
            # If the message is from the bullied user, respond
            if not self.client:
                await self.initialize_client()

            if not self.client:
                return  # No API key, silently ignore

            try:
                # Show typing indicator
                async with message.channel.typing():
                    completion = self.client.chat.completions.create(
                        model="grok-2-latest",
                        messages=[
                            {"role": "system", "content": f"{await self.config.bully_context()}"},
                            {"role": "user", "content": f"{message.content}"},
                        ],
                    )
                await message.channel.send(completion.choices[0].message.content)
            except Exception as e:
                await message.channel.send(f"An error occurred: {e}")

            return  # Stop further processing for this message

        # Allow other cogs and commands to process non-bullied user messages
        await self.bot.process_commands(message)
                
    async def cog_unload(self):
        self.bot.remove_listener(self.on_message, "on_message")
        pass

async def setup(bot: Red):
    cog = Grokchat(bot)
    await cog.initialize_client()
    await bot.add_cog(cog)