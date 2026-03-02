import base64
import json
from io import BytesIO

import aiohttp
import discord
from openai import OpenAI
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config


class Veniceimage(commands.Cog):
    """Simple cog for generating images with Venice API."""

    __author__ = "GFerreiroS"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=749365836193)
        self.default_guild = {"api_key": ""}
        self.config.register_guild(**self.default_guild)
        self.client = None
        self.image_models = []
        self.current_model = "chroma"

    async def initialize_venice(self, guild: discord.Guild):
        api_venice = await self.config.guild(guild).api_key()
        if not api_venice:
            self.client = None
            self.image_models = []
            return False

        self.api_venice = api_venice
        self.client = OpenAI(
            api_key=api_venice, base_url="https://api.venice.ai/api/v1"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.venice.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_venice}"},
                params={"type": "image"},
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    self.image_models = [m["id"] for m in data.get("data", [])]

        return True

    @commands.guildowner()
    @commands.command()
    async def veniceapikey(self, ctx, *, api_key: str):
        """Set the API key for the Venice client."""
        await self.config.guild(ctx.guild).api_key.set(api_key)
        await self.initialize_venice(ctx.guild)
        await ctx.send("API key has been updated.")

    @commands.command()
    async def venicemodels(self, ctx):
        """List available Venice image generation models."""
        api_key = await self.config.guild(ctx.guild).api_key()
        if not api_key:
            await ctx.send("API key is not set. Use `!veniceapikey` to set it.")
            return

        if not self.image_models:
            await self.initialize_venice(ctx.guild)

        if self.image_models:
            models_list = "\n".join(self.image_models)
            await ctx.send(f"Available Venice image models:\n{models_list}")
        else:
            await ctx.send("No image models found or failed to fetch models.")

    @commands.command()
    async def setvenicemodel(self, ctx, *, model_name: str):
        """Set the current Venice image generation model."""
        api_key = await self.config.guild(ctx.guild).api_key()
        if not api_key:
            await ctx.send("API key is not set. Use `!veniceapikey` to set it.")
            return

        if not self.image_models:
            await self.initialize_venice(ctx.guild)

        if model_name in self.image_models:
            self.current_model = model_name
            await ctx.send(f"Current Venice image model set to: {model_name}")
        else:
            await ctx.send(
                f"Model '{model_name}' not found. Use `!venicemodels` to see available models."
            )

    @commands.command()
    async def veniceimage(self, ctx, *, userText: str):
        """Generate image via Venice."""
        api_key = await self.config.guild(ctx.guild).api_key()
        if not api_key:
            await ctx.send("API key is not set. Use `!veniceapikey` to set it.")
            return

        if not self.client:
            initialized = await self.initialize_venice(ctx.guild)
            if not initialized:
                await ctx.send("API key is not set. Use `!veniceapikey` to set it.")
                return

        if not self.client:
            await ctx.send("API key is not set. Use `!veniceapikey` to set it.")
            return

        api_venice = getattr(self, "api_venice", None) or "key"

        url = "https://api.venice.ai/api/v1/image/generate"
        headers = {
            "Authorization": f"Bearer {api_venice}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.current_model,
            "prompt": userText,
            "width": 1280,
            "height": 1280,
            "format": "png",
            "safe_mode": False,
            "hide_watermark": True,
            "cfg_scale": 12,
            "steps": 50,
            "variants": 3,
            "lora_strength": 100,
            "resolution": "4K",
            "seed": 123,
        }

        try:
            async with ctx.typing():
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, headers=headers) as r:
                        if r.status >= 400:
                            err_text = await r.text()
                            await ctx.send(
                                f"Venice error {r.status}: {err_text[:1500]}"
                            )
                            return

                        j = await r.json()

            # 🔹 Guardar JSON
            with open("response.json", "w") as f:
                json.dump(j, f, indent=4)

            if "images" in j and len(j["images"]) > 0:
                files = []
                for index, image_base64 in enumerate(j["images"], start=1):
                    image_bytes = base64.b64decode(image_base64)
                    image_file = BytesIO(image_bytes)
                    image_file.seek(0)
                    files.append(
                        discord.File(image_file, filename=f"image_{index}.png")
                    )

                await ctx.send(files=files)
                return

            await ctx.send("No recibí imagen en la respuesta. Revisa response.json")

        except Exception as e:
            await ctx.send(f"An error occurred: {e}")

    @commands.command()
    async def venicemultiplemodels(self, ctx, *, userText: str):
        """Generate images using multiple Venice models."""
        api_key = await self.config.guild(ctx.guild).api_key()
        if not api_key:
            await ctx.send("API key is not set. Use `!veniceapikey` to set it.")
            return

        if not self.client:
            initialized = await self.initialize_venice(ctx.guild)
            if not initialized:
                await ctx.send("API key is not set. Use `!veniceapikey` to set it.")
                return

        if not self.client:
            await ctx.send("API key is not set. Use `!veniceapikey` to set it.")
            return

        api_venice = getattr(self, "api_venice", None) or "key"
        url = "https://api.venice.ai/api/v1/image/generate"
        headers = {
            "Authorization": f"Bearer {api_venice}",
            "Content-Type": "application/json",
        }

        models_to_use = ["z-image-turbo", "chroma", "lustify-sdxl", "lustify-v7"]

        try:
            async with ctx.typing():
                async with aiohttp.ClientSession() as session:
                    for model_name in models_to_use:
                        payload = {
                            "model": model_name,
                            "prompt": userText,
                            "width": 1024,
                            "height": 1024,
                            "format": "png",
                            "safe_mode": False,
                            "hide_watermark": True,
                            "cfg_scale": 7.5,
                            "steps": 50,
                            "variants": 3,
                        }

                        async with session.post(
                            url, json=payload, headers=headers
                        ) as response:
                            if response.status >= 400:
                                err_text = await response.text()
                                await ctx.send(
                                    f"Model `{model_name}` error {response.status}: {err_text[:1500]}"
                                )
                                continue

                            response_json = await response.json()

                        with open(f"response_{model_name}.json", "w") as f:
                            json.dump(response_json, f, indent=4)

                        images = response_json.get("images", [])
                        if not images:
                            await ctx.send(
                                f"Model `{model_name}` returned no images. Check response_{model_name}.json"
                            )
                            continue

                        files = []
                        for index, image_base64 in enumerate(images, start=1):
                            image_bytes = base64.b64decode(image_base64)
                            image_file = BytesIO(image_bytes)
                            image_file.seek(0)
                            files.append(
                                discord.File(
                                    image_file,
                                    filename=f"{model_name}_image_{index}.png",
                                )
                            )

                        await ctx.send(content=f"Model: `{model_name}`", files=files)

        except Exception as e:
            await ctx.send(f"An error occurred: {e}")


async def setup(bot: Red):
    cog = Veniceimage(bot)
    await bot.add_cog(cog)
