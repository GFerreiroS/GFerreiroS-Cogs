import discord
from redbot.core import commands, Config
import asyncio
import datetime
from io import BytesIO
import os
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By


class DofusAlmanax(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567890, force_registration=True
        )

        # Register persistent storage for each guild
        self.config.register_guild(
            channel_id=None,  # Persistent storage for channel ID
            guild_id=None,  # Persistent storage for guild ID (optional, if you need to track it explicitly)
        )

        self.image_filename = "almanax_image.png"
        self.channel_id = None  # Fallback in case config doesn't load properly
        self.guild_id = None  # Fallback for guild ID

        # Start the scheduler
        self.bot.loop.create_task(self.start_scheduler())

    async def start_scheduler(self):
        """Start the almanax_scheduler task."""
        await self.bot.wait_until_ready()

        # Load the configuration for the guilds
        for guild in self.bot.guilds:
            # Retrieve channel_id for the guild
            guild_config = self.config.guild(guild)
            self.channel_id = await guild_config.channel_id()
            self.guild_id = guild.id  # Use dynamic guild ID

            # If no channel is configured, print a helpful message
            if not self.channel_id:
                print(
                    f"No channel configured for guild {guild.id}. Use the `setalmanaxchannel` command."
                )

        # Start the scheduler task
        await self.almanax_scheduler()

    async def almanax_scheduler(self):
        """Scheduler to send the Almanax image at 23:30 UTC each day."""
        while True:
            # If channel_id is missing, try to load it from the configuration
            if not self.channel_id:
                print("Channel ID not set. Attempting to reload from configuration...")
                for guild in self.bot.guilds:
                    self.channel_id = await self.config.guild(guild).channel_id()
                    self.guild_id = guild.id

            # Continue only if channel_id is configured
            if not self.channel_id:
                print("Channel ID is still not configured. Skipping this cycle.")
                await asyncio.sleep(60)  # Retry after 1 minute
                continue  # Move to the next iteration of the loop

            now = datetime.datetime.utcnow()
            target_time = datetime.time(23, 30)  # 23:30 UTC
            next_run = datetime.datetime.combine(now.date(), target_time)

            if now >= next_run:
                next_run += datetime.timedelta(days=1)

            sleep_time = (next_run - now).total_seconds()
            print(
                f"Sleeping for {sleep_time} seconds until the next run at {next_run} UTC..."
            )
            await asyncio.sleep(sleep_time)

            # Generate and send the image
            print("Generating and sending Almanax image...")
            image = await self.generate_image()
            if image:
                guild = self.bot.get_guild(self.guild_id)
                if not guild:
                    print(f"Guild with ID {self.guild_id} not found.")
                    continue  # Skip to the next iteration of the loop

                almanax_role = discord.utils.get(guild.roles, name="Almanax")
                channel = guild.get_channel(self.channel_id)

                if almanax_role and channel:
                    await channel.send(f"{almanax_role.mention} {now.date()}")
                    await channel.send(file=discord.File(image, "almanax_image.png"))
                else:
                    print(f"Channel or role not found in guild {self.guild_id}.")
            else:
                print("An error occurred while generating the image.")

    @commands.command()
    async def setalmanaxchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel for Almanax messages."""
        guild_id = ctx.guild.id  # Dynamically get the guild ID
        self.channel_id = channel.id  # Save the channel ID in memory
        self.guild_id = guild_id  # Save the guild ID in memory

        # Save both to persistent storage
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await self.config.guild(ctx.guild).guild_id.set(guild_id)  # Optional

        await ctx.send(
            f"The Almanax channel has been set to {channel.mention} for this server."
        )

    @commands.command()
    async def almanaximage(self, ctx):
        """Generate and send the Almanax image on demand."""
        image = await self.generate_image()
        if image:
            now = datetime.datetime.utcnow()
            almanax_role = discord.utils.get(ctx.guild.roles, name="Almanax")

            if almanax_role:
                await ctx.send(f"{almanax_role.mention} {now.date()}")
            else:
                await ctx.send("The 'Almanax' role does not exist.")

            await ctx.send(file=discord.File(image, "almanax_image.png"))
        else:
            await ctx.send("An error occurred while generating the image.")

    async def generate_image(self):
        """Generate the Almanax image by scraping the webpage."""
        url = "https://www.krosmoz.com/es/almanax"
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Set options for headless Chrome
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        chrome_options.add_argument("--high-dpi-support=1")

        # Initialize WebDriver
        driver = webdriver.Chrome(options=chrome_options)

        try:
            driver.set_window_size(2560, 1440)
            driver.get(url)
            await asyncio.sleep(3)  # Give the page time to load

            # Close cookies modal
            try:
                cookies_button = driver.find_element(
                    By.CSS_SELECTOR, "button[class*='ak-accept']"
                )
                cookies_button.click()
                await asyncio.sleep(1)  # Wait for modal to close
            except Exception:
                pass

            # Close welcome modal
            try:
                welcome_modal_button = driver.find_element(
                    By.CSS_SELECTOR, "a.btn_close"
                )
                welcome_modal_button.click()
                await asyncio.sleep(1)  # Wait for modal to close
            except Exception:
                pass

            # Locate the div element by ID
            achievement_div = driver.find_element(By.ID, "achievement_dofus")

            # Get the location and size of the div
            location = achievement_div.location
            size = achievement_div.size

            # Calculate the crop region based on the div's location and size
            crop_region = (
                location["x"],  # left
                location["y"],  # top
                location["x"] + size["width"],  # right
                location["y"] + size["height"],  # bottom
            )

            # Save the full screenshot
            image_path = os.path.join(script_dir, self.image_filename)
            driver.save_screenshot(image_path)

            # Open the full image and crop it
            full_image = Image.open(image_path)
            cropped_image = full_image.crop(crop_region)

            # Save the cropped image to BytesIO
            image_bytes = BytesIO()
            cropped_image.save(image_bytes, format="PNG")
            image_bytes.seek(0)

            os.remove(image_path)  # Clean up the temporary image file
            return image_bytes

        except Exception as e:
            print(f"An error occurred while generating the image: {e}")
            return None
        finally:
            driver.quit()


# Setup the cog
async def setup(bot):
    await bot.add_cog(DofusAlmanax(bot))
