import discord
from redbot.core import commands
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from PIL import Image
import os
import asyncio
from io import BytesIO
import datetime

class DofusAlmanax(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.image_filename = "almanax_image.png"
        self.channel_id = 1325874852065841152  # ID of the specific channel
        self.guild_id = 1307809394884476998

        # Start the scheduler
        self.bot.loop.create_task(self.start_scheduler())

    async def start_scheduler(self):
        """Start the almanax_scheduler task."""
        await self.bot.wait_until_ready()
        await self.almanax_scheduler()

    async def almanax_scheduler(self):
        """Scheduler to send the Almanax image at 00:30 UTC each day."""
        while True:
            now = datetime.datetime.utcnow()
            target_time = datetime.time(23, 30)  # 00:30 UTC
            next_run = datetime.datetime.combine(now.date(), target_time)

            # If the current time is past today's 00:30, schedule for tomorrow
            if now >= next_run:
                next_run += datetime.timedelta(days=1)

            # Calculate the time to sleep until the next target time
            sleep_time = (next_run - now).total_seconds()
            print(f"Sleeping for {sleep_time} seconds until the next run at {next_run} UTC...")
            await asyncio.sleep(sleep_time)

            # Generate and send the image
            print("Generating and sending Almanax image...")
            image = await self.generate_image()
            if image:
                # Find the guild and get the role by name
                guild = self.bot.get_guild(self.guild_id)  # Using self.guild_id here
                almanax_role = discord.utils.get(guild.roles, name="Almanax")

                if almanax_role:
                    # Get the specific channel by ID using self.channel_id
                    channel = guild.get_channel(self.channel_id)

                    if channel:
                        # Send the message mentioning the role and the current date
                        await channel.send(f"{almanax_role.mention} {now.date()}")
                        await channel.send(file=discord.File(image, "almanax_image.png"))
                    else:
                        print(f"Channel with ID {self.channel_id} not found.")
                else:
                    print("The 'Almanax' role does not exist.")
            else:
                print("An error occurred while generating the image.")

    @commands.command()
    async def almanaximage(self, ctx):
        """Generate and send the Almanax image on demand."""
        image = await self.generate_image()
        if image:
            # Get the current date
            now = datetime.datetime.utcnow()
            current_date = now.date()

            # Retrieve the role by name (make sure the role exists in the server)
            almanax_role = discord.utils.get(ctx.guild.roles, name="Almanax")

            if almanax_role:
                # Send the message mentioning the role and the current date
                await ctx.send(f"{almanax_role.mention} {current_date}")
            else:
                await ctx.send("The 'Almanax' role does not exist.")

            # Send the Almanax image
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
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        chrome_options.add_argument("--high-dpi-support=1")

        # Initialize WebDriver
        driver = webdriver.Chrome(options=chrome_options)

        try:
            driver.set_window_size(2560, 1440)
            driver.get(url)
            await asyncio.sleep(3)  # Give the page time to load

            # Close cookies modal
            try:
                cookies_button = driver.find_element(By.CSS_SELECTOR, "button[class*='ak-accept']")
                cookies_button.click()
                await asyncio.sleep(1)  # Wait for modal to close
            except Exception:
                pass

            # Close welcome modal
            try:
                welcome_modal_button = driver.find_element(By.CSS_SELECTOR, "a.btn_close")
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
                location['x'],  # left
                location['y'],  # top
                location['x'] + size['width'],  # right
                location['y'] + size['height']  # bottom
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

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        # Check if the reaction is on the specific message
        if reaction.message.id == 1325919379950407681:
            # Check if the reaction is the specific emoji
            if str(reaction.emoji) == '✅':  # Replace with the emoji you want
                role = discord.utils.get(user.guild.roles, name="Almanax")  # Replace with the role name
                if role:
                    # Add the role to the user
                    await user.add_roles(role)

# Setup the cog
async def setup(bot):
    await bot.add_cog(DofusAlmanax(bot))
