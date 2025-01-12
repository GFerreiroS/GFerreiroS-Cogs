import dofusdude
import discord
import aiohttp
import os
import tempfile
import json
import asyncio
from dofusdude.rest import ApiException
from redbot.core import commands
from datetime import datetime
from urllib.parse import urlparse

# Helper function to serialize non-serializable objects
def serialize(obj):
    if hasattr(obj, 'dict'):
        return obj.dict()
    elif isinstance(obj, list):
        return [serialize(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: serialize(value) for key, value in obj.items()}
    else:
        return str(obj)

class Dofusearch(commands.Cog):
    """A cog to fetch Almanax data using the Dofus Dude API."""

    def __init__(self, bot):
        self.bot = bot
        self.configuration = dofusdude.Configuration(
            host="https://api.dofusdu.de"
        )

    @commands.command()
    async def almanax(self, ctx, date: str):
        """Fetch the Almanax data for the provided date (yyyy-mm-dd)."""
        # Validate the date format (optional)
        try:
            # Try parsing the date to check the format
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            await ctx.send("Invalid date format. Please use yyyy-mm-dd.")
            return

        # Enter a context with an instance of the API client
        with dofusdude.ApiClient(self.configuration) as api_client:
            # Create an instance of the AlmanaxApi
            api_instance = dofusdude.AlmanaxApi(api_client)
            language = 'es'  # Change if needed (e.g., 'en' for English)

            try:
                # Get Almanax data for the provided date
                api_response = api_instance.get_almanax_date(language, date)
                
                # Access the attributes correctly using dot notation
                bonus_description = api_response.bonus.description
                bonus_type = api_response.bonus.type.name
                tribute_name = api_response.tribute.item.name
                tribute_image_url = api_response.tribute.item.image_urls.sd
                reward_kamas = api_response.reward_kamas
                almanax_date = date  # Default to input date if the response doesn't have a date attribute

                # Get file extension from the image URL (e.g., .png, .jpg)
                image_extension = os.path.splitext(urlparse(tribute_image_url).path)[-1].lower()

                # Download the image
                async with aiohttp.ClientSession() as session:
                    async with session.get(tribute_image_url) as resp:
                        if resp.status == 200:
                            # Create a temporary file with the correct extension
                            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=image_extension)
                            temp_file_path = temp_file.name
                            with open(temp_file_path, 'wb') as f:
                                f.write(await resp.read())
                            temp_file.close()

                            # Send the message with the image as an attachment
                            formatted_message = (
                                f"**Almanax for {almanax_date}:**\n\n"
                                f"**Bonus:** {bonus_description} ({bonus_type})\n"
                                f"**Tribute:** {tribute_name}\n"
                                f"**Reward Kamas:** {reward_kamas}\n"
                            )

                            await ctx.send(formatted_message, file=discord.File(temp_file_path))

                            # Clean up by deleting the temporary file
                            os.remove(temp_file_path)
                        else:
                            await ctx.send("Failed to download the tribute image.")
            except ApiException as e:
                await ctx.send(f"Error when calling Almanax API: {e}")

    @commands.command()
    async def dofusearch(self, ctx, *, name: str):
        """Search for the given name across all available Dofus API categories."""
        # List of all the search methods to try
        search_methods = [
            ("ConsumablesApi", "get_items_consumables_search", "Consumibles"),
            ("EquipmentApi", "get_items_equipment_search", "Equipamiento"),
            ("CosmeticsApi", "get_cosmetics_search", "Cosméticos"),
            ("ResourcesApi", "get_items_resource_search", "Recursos"),
            ("MountsApi", "get_mounts_search", "Monturas"),
            ("QuestItemsApi", "get_items_quest_search", "Misiones"),
            ("SetsApi", "get_sets_search", "Conjuntos")
        ]

        results = None
        name = name.lower()  # Lowercase the input name

        # Enter a context with an instance of the API client
        with dofusdude.ApiClient(self.configuration) as api_client:
            language = 'es'  # Spanish
            game = "dofus3"  # Game type (default to Dofus)

            # Search through all methods
            for api_class, method, category in search_methods:
                try:
                    # Get the correct API class and method
                    api_instance = getattr(dofusdude, api_class)(api_client)
                    search_method = getattr(api_instance, method)

                    print(f"Searching for '{name}' in category {category} using query: {name}")

                    # Check if the method is asynchronous or synchronous
                    if asyncio.iscoroutinefunction(search_method):
                        api_response = await search_method(game=game, language=language, query=name)
                    else:
                        api_response = search_method(game=game, language=language, query=name)

                    # DEBUGGING: Print the raw API response for inspection
                    print(f"API response from {category}: {api_response}")

                    # Ensure that api_response is a list of items
                    if isinstance(api_response, list):
                        exact_matches = []
                        for item in api_response:
                            # Check if the item has a 'name' attribute and compare it case insensitively
                            item_name = getattr(item, 'name', '').lower()  # Safely get 'name'
                            if item_name == name:
                                exact_matches.append(item)

                        if exact_matches:
                            # We found at least one exact match
                            results = (category, exact_matches[0])
                            break

                except ApiException as e:
                    if e.status == 404:
                        continue  # Ignore 404 errors and keep searching
                    else:
                        await ctx.send(f"Error while searching {category}: {e}")
                except TypeError as e:
                    print(f"TypeError encountered in {category} API: {e}")
                    continue

        if results:
            # If we found an exact match, display it
            category, exact_match = results
            response_text = f"**Resultado encontrado en {category}:**\n"
            response_text += f"- {getattr(exact_match, 'name', 'Nombre no disponible')}\n"

            # Send the full response data (api_response) as raw JSON
            try:
                serialized_response = json.dumps(exact_match.dict(), indent=2)  # Ensure that 'exact_match' is serializable
                response_text += "\n**Datos completos de la API:**\n"
                response_text += f"```json\n{serialized_response}\n```"
            except Exception as e:
                response_text += f"\nError serializing the API response: {e}"

            # Check if response is too long, and split into chunks if necessary
            if len(response_text) > 2000:
                # Split the response into chunks of 2000 characters or less
                for i in range(0, len(response_text), 2000):
                    await ctx.send(response_text[i:i+2000])
            else:
                await ctx.send(response_text)
        else:
            # If no results were found, inform the user
            await ctx.send("No se ha encontrado ningún elemento con ese nombre.")
        
# Setup function to add the cog
def setup(bot):
    bot.add_cog(Dofusearch(bot))
