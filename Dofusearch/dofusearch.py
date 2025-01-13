import dofusdude
import discord
import aiohttp
import os
import tempfile
import json
import asyncio
import unicodedata
from dofusdude.rest import ApiException
from redbot.core import commands
from datetime import datetime
from urllib.parse import urlparse

# Helper function to remove accents/diacritics
def remove_accents(input_str: str) -> str:
    """
    Removes all accent/diacritic marks from the given string
    and returns the normalized version (e.g., "á" -> "a").
    """
    nf = unicodedata.normalize('NFD', input_str)
    return ''.join(ch for ch in nf if unicodedata.category(ch) != 'Mn')

# Helper function to serialize objects that are not JSON-serializable by default
def json_default(obj):
    """
    Converts sets to lists, and anything else not serializable to string.
    """
    if isinstance(obj, set):
        return list(obj)
    return str(obj)

# Helper function to serialize non-serializable objects (if you still need it)
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
    """A cog to fetch Almanax data and item data using the Dofus Dude API."""

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
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            await ctx.send("Invalid date format. Please use yyyy-mm-dd.")
            return

        with dofusdude.ApiClient(self.configuration) as api_client:
            api_instance = dofusdude.AlmanaxApi(api_client)
            language = 'es'  # Spanish

            try:
                api_response = api_instance.get_almanax_date(language, date)
                bonus_description = api_response.bonus.description
                bonus_type = api_response.bonus.type.name
                tribute_name = api_response.tribute.item.name
                tribute_image_url = api_response.tribute.item.image_urls.sd
                reward_kamas = api_response.reward_kamas
                almanax_date = date

                image_extension = os.path.splitext(urlparse(tribute_image_url).path)[-1].lower()

                async with aiohttp.ClientSession() as session:
                    async with session.get(tribute_image_url) as resp:
                        if resp.status == 200:
                            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=image_extension)
                            temp_file_path = temp_file.name
                            with open(temp_file_path, 'wb') as f:
                                f.write(await resp.read())
                            temp_file.close()

                            formatted_message = (
                                f"**Almanax for {almanax_date}:**\n\n"
                                f"**Bonus:** {bonus_description} ({bonus_type})\n"
                                f"**Tribute:** {tribute_name}\n"
                                f"**Reward Kamas:** {reward_kamas}\n"
                            )

                            await ctx.send(formatted_message, file=discord.File(temp_file_path))
                            os.remove(temp_file_path)
                        else:
                            await ctx.send("Failed to download the tribute image.")
            except ApiException as e:
                await ctx.send(f"Error when calling Almanax API: {e}")

class Dofusearch(commands.Cog):
    """A cog to fetch item data using the Dofus Dude API.
    
    - If item is 'Recursos', do a second call to get_items_resources_single(ankama_id)
      and output the raw JSON.
    - If item is 'Consumibles', build an embed with name/description/etc.
    - If item is 'Equipamiento', do the existing equip logic (pagination).
    - Otherwise, handle all other categories as you wish.
    """

    def __init__(self, bot):
        self.bot = bot
        self.configuration = dofusdude.Configuration(
            host="https://api.dofusdu.de"
        )

    @commands.command()
    async def dofusearch(self, ctx, *, name: str):
        """
        1) Search for the given name across Dofus items (search APIs).
        2) If item is 'Recursos', do get_items_resources_single for an exact match
           and output raw JSON.
        3) If item is 'Consumibles', build an embed with name/description/etc.
        4) If item is 'Equipamiento', do your pagination logic.
        5) Otherwise, handle any other categories as needed.
        """
        name = remove_accents(name).lower()

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

        with dofusdude.ApiClient(self.configuration) as api_client:
            language = 'es'
            game = "dofus3"

            # STEP 1: Search by name
            for api_class, method, category in search_methods:
                try:
                    api_instance = getattr(dofusdude, api_class)(api_client)
                    search_method = getattr(api_instance, method)

                    if asyncio.iscoroutinefunction(search_method):
                        api_response = await search_method(game=game, language=language, query=name)
                    else:
                        api_response = search_method(game=game, language=language, query=name)

                    if isinstance(api_response, list):
                        for item in api_response:
                            item_name_raw = getattr(item, 'name', '')
                            item_name_normalized = remove_accents(item_name_raw).lower()
                            if item_name_normalized == name:
                                results = (category, item)
                                break
                        if results:
                            break

                except ApiException:
                    continue
                except TypeError:
                    continue

        if not results:
            await ctx.send("No se ha encontrado ningún elemento con ese nombre.")
            return

        category, matched_item = results
        ankama_id = getattr(matched_item, 'ankama_id', None)

        # ---------------------------
        # If category == "Recursos" => get detailed resource & output JSON
        # ---------------------------
        if category == "Recursos" and ankama_id is not None:
            try:
                resources_api = dofusdude.ResourcesApi(api_client)
                # Fetch detailed resource data
                detailed_resource = resources_api.get_items_resources_single(
                    game=game,
                    language=language,
                    ankama_id=ankama_id
                )

                # Extract relevant fields
                item_name = getattr(detailed_resource, 'name', None)
                item_description = getattr(detailed_resource, 'description', None)
                item_type_obj = getattr(detailed_resource, 'type', None)
                item_type_name = getattr(item_type_obj, 'name', None) if item_type_obj else None
                item_level = getattr(detailed_resource, 'level', None)
                item_pods = getattr(detailed_resource, 'pods', None)
                image_urls = getattr(detailed_resource, 'image_urls', None)
                image_sd = getattr(image_urls, 'sd', None) if image_urls else None
                item_effects = getattr(detailed_resource, 'effects', None)

                # Create the embed
                embed_color = discord.Color.blurple()
                embed = discord.Embed(title="", description="", color=embed_color)

                # Add title (name)
                if item_name:
                    embed.title = item_name

                # Add description
                if item_description:
                    embed.description = item_description

                # Add type name
                if item_type_name:
                    embed.add_field(name="Tipo", value=item_type_name, inline=True)

                # Add level
                if item_level is not None:
                    embed.add_field(name="Nivel", value=str(item_level), inline=True)

                # Add pods
                if item_pods is not None:
                    embed.add_field(name="Peso (pods)", value=str(item_pods), inline=True)

                # Add effects
                if item_effects:
                    effect_lines = []
                    for eff in item_effects:
                        eff_formatted = getattr(eff, 'formatted', None)
                        if eff_formatted:
                            effect_lines.append(f"- {eff_formatted}")
                    if effect_lines:
                        embed.add_field(
                            name="Efectos",
                            value="\n".join(effect_lines),
                            inline=False
                        )

                # Add image
                if image_sd:
                    embed.set_image(url=image_sd)

                # Send the embed
                await ctx.send(embed=embed)
                return

            except ApiException as e:
                await ctx.send(f"Error al obtener Recurso detallado: {e}")
                return

        # --------------------------- 
        # IF CONSUMABLES => BUILD A SPECIAL EMBED
        # ---------------------------
        if category == "Consumibles" and ankama_id is not None:
            try:
                consumables_api = dofusdude.ConsumablesApi(api_client)
                # second call for detailed data
                detailed_item = consumables_api.get_items_consumables_single(
                    game=game,
                    language=language,
                    ankama_id=ankama_id
                )

                # Now build an embed
                item_name = getattr(detailed_item, 'name', None)
                item_description = getattr(detailed_item, 'description', None)
                item_type_obj = getattr(detailed_item, 'type', None)
                item_type_name = getattr(item_type_obj, 'name', None) if item_type_obj else None
                item_level = getattr(detailed_item, 'level', None)
                item_pods = getattr(detailed_item, 'pods', None)  # "weight inside the pocket"
                image_urls = getattr(detailed_item, 'image_urls', None)
                image_sd = getattr(image_urls, 'sd', None) if image_urls else None
                item_effects = getattr(detailed_item, 'effects', None)
                item_conditions = getattr(detailed_item, 'conditions', None)

                embed_color = discord.Color.blurple()
                embed = discord.Embed(title="", description="", color=embed_color)

                # NAME => embed.title if not None
                if item_name:
                    embed.title = item_name

                # DESCRIPTION => embed.description if not None
                if item_description:
                    embed.description = item_description

                # TYPE => field
                if item_type_name:
                    embed.add_field(name="Tipo", value=item_type_name, inline=True)

                # LEVEL => field
                if item_level is not None:
                    embed.add_field(name="Nivel", value=str(item_level), inline=True)

                # PODS => field
                if item_pods is not None:
                    embed.add_field(name="Peso", value=str(item_pods), inline=True)

                # IMAGE => set image
                if image_sd:
                    embed.set_image(url=image_sd)

                # EFFECTS => bullet list
                if item_effects:
                    effect_lines = []
                    for eff in item_effects:
                        # We only display the "formatted" text
                        eff_formatted = getattr(eff, 'formatted', None)
                        if eff_formatted:
                            effect_lines.append(f"- {eff_formatted}")
                    if effect_lines:
                        embed.add_field(
                            name="Efectos",
                            value="\n".join(effect_lines),
                            inline=False
                        )

                # CONDITIONS => field if not None
                # Conditions can be a string or complex object. 
                # If your code has a single condition string, you can do:
                if item_conditions:
                    # For example, item_conditions might be a dict or an object
                    # Check if it's a simple attribute like `.condition`
                    # Or just do a naive approach:
                    cond_text = str(item_conditions)
                    embed.add_field(
                        name="Condiciones",
                        value=cond_text,
                        inline=False
                    )

                await ctx.send(embed=embed)
                return

            except ApiException as e:
                await ctx.send(f"Error al obtener Consumible detallado: {e}")
                return

        # ---------------------------
        # If it's Equipamiento, fetch more details
        # ---------------------------
        if category == "Equipamiento" and ankama_id is not None:
            try:
                equipment_api = dofusdude.EquipmentApi(api_client)
                matched_item = equipment_api.get_items_equipment_single(
                    game=game,
                    language=language,
                    ankama_id=ankama_id
                )
            except ApiException:
                pass

        # For all else (including equip with extra info now), we do pagination logic
        item_name = getattr(matched_item, 'name', "Desconocido")
        item_type_obj = getattr(matched_item, 'type', None)
        item_type_name = getattr(item_type_obj, 'name', None)
        item_description = getattr(matched_item, 'description', None) or ""
        item_level = getattr(matched_item, 'level', None)
        item_range = getattr(matched_item, 'range', None)
        item_ap_cost = getattr(matched_item, 'ap_cost', None)
        item_max_cast = getattr(matched_item, 'max_cast_per_turn', None)
        item_crit_prob = getattr(matched_item, 'critical_hit_probability', None)
        item_crit_bonus = getattr(matched_item, 'critical_hit_bonus', None)
        item_effects = getattr(matched_item, 'effects', None)
        parent_set = getattr(matched_item, 'parent_set', None)
        parent_set_name = getattr(parent_set, 'name', None) if parent_set else None

        image_url = None
        if getattr(matched_item, 'image_urls', None):
            image_url = getattr(matched_item.image_urls, 'sd', None)

        # ---- PAGE 1 (Basic info except description) ----
        page1 = discord.Embed(title=item_name, color=discord.Color.blurple())
        # Tipo
        if item_type_name:
            page1.add_field(name="Tipo", value=item_type_name, inline=True)
        # Nivel
        if item_level is not None:
            page1.add_field(name="Nivel", value=str(item_level), inline=True)

        # Efectos
        if item_effects:
            eff_lines = []
            for eff in item_effects:
                eff_name = getattr(getattr(eff, 'type', None), 'name', '')
                eff_formatted = getattr(eff, 'formatted', '')
                if eff_name and eff_formatted:
                    eff_lines.append(f"- **{eff_name}**: {eff_formatted}")
            if eff_lines:
                page1.add_field(name="Efectos", value="\n".join(eff_lines), inline=False)

        # Stats
        stats_lines = []
        if item_range is not None:
            stats_lines.append(f"**Alcance**: {item_range}")
        if item_ap_cost is not None:
            stats_lines.append(f"**Coste de PA**: {item_ap_cost}")
        if item_max_cast is not None:
            stats_lines.append(f"**Lanzamientos/turno**: {item_max_cast}")
        if item_crit_prob is not None:
            stats_lines.append(f"**Crítico**: {item_crit_prob}%")
        if item_crit_bonus is not None:
            stats_lines.append(f"**Bonificación Crítico**: {item_crit_bonus}")
        if stats_lines:
            page1.add_field(
                name="Características adicionales",
                value="\n".join(stats_lines),
                inline=False
            )

        # Set
        if parent_set_name:
            page1.add_field(name="Set", value=parent_set_name, inline=True)

        # Image
        if image_url:
            page1.set_image(url=image_url)

        # Build pages
        pages = []

        # If the description is <= 150 chars, all in one page
        if len(item_description) <= 150:
            page1.description = item_description
            pages.append(page1)
        else:
            # Make page2 for the description
            page2 = discord.Embed(
                title=item_name,
                color=discord.Color.blurple(),
                description=item_description
            )
            if image_url:
                page2.set_image(url=image_url)
            pages = [page1, page2]

        # If single page, just send it
        if len(pages) == 1:
            await ctx.send(embed=pages[0])
            return

        # Otherwise, reaction-based pagination for 2 pages
        current_page = 0
        message = await ctx.send(embed=pages[current_page])
        await message.add_reaction("⬅")
        await message.add_reaction("➡")

        def check(reaction, user):
            return (
                user == ctx.author
                and reaction.message.id == message.id
                and str(reaction.emoji) in ["⬅", "➡"]
            )

        while True:
            try:
                reaction, user = await self.bot.wait_for(
                    "reaction_add",
                    timeout=60.0,
                    check=check
                )
                # Try removing their reaction if possible
                try:
                    await message.remove_reaction(reaction.emoji, user)
                except discord.Forbidden:
                    pass

                if str(reaction.emoji) == "➡":
                    current_page = (current_page + 1) % len(pages)
                elif str(reaction.emoji) == "⬅":
                    current_page = (current_page - 1) % len(pages)

                await message.edit(embed=pages[current_page])

            except asyncio.TimeoutError:
                # Attempt to clear reactions if permitted
                try:
                    await message.clear_reactions()
                except discord.Forbidden:
                    pass
                break

        
# Setup function to add the cog
def setup(bot):
    bot.add_cog(Dofusearch(bot))
