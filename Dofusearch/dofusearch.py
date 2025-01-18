import dofusdude
import discord
import os
import asyncio
import unicodedata
import i18n
from dofusdude.rest import ApiException
from redbot.core import commands, checks

current_directory = os.path.dirname(os.path.abspath(__file__))
locales_path = os.path.join(current_directory, 'locales')
i18n.load_path.append(locales_path)
i18n.set('locale', 'es')
i18n.set("file_format", "json")
i18n.set('filename_format', '{locale}.{format}')
i18n.set('enable_memoization', True)
_ = i18n.t

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
    """A cog to fetch item data using the Dofus Dude API.
    
    - If item is 'Resources', do a second call to get_items_resources_single(ankama_id)
      and output the raw JSON.
    - If item is 'Consumables', build an embed with name/description/etc.
    - If item is 'Equipment', do the existing equip logic (pagination).
    - Otherwise, handle all other categories as you wish.
    """

    def __init__(self, bot):
        self.bot = bot
        self.configuration = dofusdude.Configuration(
            host="https://api.dofusdu.de"
        )
        self.selected_language = 'es'

    @commands.guildowner()
    @commands.command()
    async def searchlang(self, ctx, language: str):
        supported_languages = ['en', 'es', 'fr', 'de', 'pt']
        if language in supported_languages:
            i18n.set('locale', language)
            self.selected_language = language
            await ctx.send(f"Changed to {language}")
        else:
            await ctx.send("Language not supported. Supported languages: en, es, fr, de, pt")

    @commands.command()
    @commands.cooldown(10, 10, commands.BucketType.guild)
    @commands.max_concurrency(10, commands.BucketType.default)
    @checks.bot_has_permissions(attach_files=True)
    async def dofusearch(self, ctx, *, name: str):
        """
        1) Search for the given name across Dofus items (search APIs).
        2) If the name starts with a mount prefix ('Dragopavo', 'Vueloceronte', 'Mulagua'), search mounts directly.
        3) Handle other categories such as 'Resources', 'Consumables', etc.
        """
        name = remove_accents(name).lower()

        search_methods = [
            ("MountsApi", "get_mounts_search", "Mounts"),                           # Search logic done
            ("ConsumablesApi", "get_items_consumables_search", "Consumables"),      # Search logic done
            ("EquipmentApi", "get_items_equipment_search", "Equipment"),            # Search logic done
            ("CosmeticsApi", "get_cosmetics_search", "Cosmetics"),                  # Search logic done
            ("ResourcesApi", "get_items_resource_search", "Resources"),             # Search logic done
            ("QuestItemsApi", "get_items_quest_search", "QuestItems"),              # Search logic done
            ("SetsApi", "get_sets_search", "Sets")                                  # TODO
        ]

        results = None

        with dofusdude.ApiClient(self.configuration) as api_client:
            language = self.selected_language
            game = "dofus3"

            # STEP 2: Search for other categories (general logic)
            for api_class, method, category in search_methods:
                try:
                    api_instance = getattr(dofusdude, api_class)(api_client)
                    search_method = getattr(api_instance, method)

                    if asyncio.iscoroutinefunction(search_method):
                        api_response = await search_method(game=game, language=language, query=name)
                    else:
                        api_response = search_method(game=game, language=language, query=name)
                    
                    if isinstance(api_response, list):
                        matching_items = []
                    for item in api_response:
                        item_name_raw = getattr(item, 'name', '')
                        item_name_normalized = remove_accents(item_name_raw).lower()
                        if item_name_normalized == name:
                            matching_items.append(item)

                    # If there are matching items, find the one with the highest level
                    if matching_items:
                        # Sort items by level in descending order and take the first one
                        highest_level_item = max(matching_items, key=lambda x: getattr(x, 'level', 0))
                        results = (category, highest_level_item)
                        break

                except ApiException:
                    continue
                except TypeError:
                    continue

        if not results:
            await ctx.send(_("messages.info.not_found"))
            return

        # Handle other categories (Resources, Consumables, etc.)
        category, matched_item = results
        ankama_id = getattr(matched_item, 'ankama_id', None)
    
        # --------------------------- 
        # IF MOUNTS => BUILD A SPECIAL EMBED
        # ---------------------------
        if category == "Mounts" and ankama_id is not None:
            try:
                mounts_api = dofusdude.MountsApi(api_client)
                detailed_mount = mounts_api.get_mounts_single(
                    game=game,
                    language=language,
                    ankama_id=ankama_id
                )

                # Now build an embed
                mount_name = getattr(detailed_mount, 'name', None)
                mount_description = getattr(detailed_mount, 'description', None)
                image_urls = getattr(detailed_mount, 'image_urls', None)
                image_sd = getattr(image_urls, 'sd', None) if image_urls else None
                mount_effects = getattr(detailed_mount, 'effects', None)

                embed_color = discord.Color.blurple()
                embed = discord.Embed(title="", description="", color=embed_color)

                # NAME => embed.title if not None
                if mount_name:
                    embed.title = mount_name

                # DESCRIPTION => embed.description if not None
                if mount_description:
                    embed.description = mount_description

                # IMAGE => set image
                if image_sd:
                    embed.set_image(url=image_sd)

                # EFFECTS => bullet list
                if mount_effects:
                    effect_lines = []
                    for eff in mount_effects:
                        # We only display the "formatted" text
                        eff_formatted = getattr(eff, 'formatted', None)
                        if eff_formatted:
                            effect_lines.append(f"- {eff_formatted}")
                    if effect_lines:
                        embed.add_field(
                            name=_("key_words.effects"),
                            value="\n".join(effect_lines),
                            inline=False
                        )

                await ctx.send(embed=embed)
                return

            except ApiException as e:
                await ctx.send(f"Error al obtener Montura detallado: {e}")
                return
    
        # ---------------------------
        # If category == "Resources" => get detailed resource & output JSON
        # ---------------------------
        if category == "Resources" and ankama_id is not None:
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
                    embed.add_field(name=_("key_words.type"), value=item_type_name, inline=True)

                # Add level
                if item_level is not None:
                    embed.add_field(name=_("key_words.level"), value=str(item_level), inline=True)

                # Add pods
                if item_pods is not None:
                    embed.add_field(name=_("key_words.pods"), value=str(item_pods), inline=True)

                # Add effects
                if item_effects:
                    effect_lines = []
                    for eff in item_effects:
                        eff_formatted = getattr(eff, 'formatted', None)
                        if eff_formatted:
                            effect_lines.append(f"- {eff_formatted}")
                    if effect_lines:
                        embed.add_field(
                            name=_("key_words.effects"),
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
        if category == "Consumables" and ankama_id is not None:
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
                    embed.add_field(name=_("key_words.type"), value=item_type_name, inline=True)

                # LEVEL => field
                if item_level is not None:
                    embed.add_field(name=_("key_words.level"), value=str(item_level), inline=True)

                # PODS => field
                if item_pods is not None:
                    embed.add_field(name=_("key_words.pods"), value=str(item_pods), inline=True)

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
                            name=_("key_words.effects"),
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
                        name=_("key_words.conditions"),
                        value=cond_text,
                        inline=False
                    )

                await ctx.send(embed=embed)
                return

            except ApiException as e:
                await ctx.send(f"Error al obtener Consumible detallado: {e}")
                return

        # ---------------------------
        # If category == "QuestItems" => Get detailed quest item & build embed
        # ---------------------------
        if category == "QuestItems" and ankama_id is not None:
            try:
                quest_items_api = dofusdude.QuestItemsApi(api_client)
                # Fetch detailed quest item data
                detailed_quest_item = quest_items_api.get_item_quest_single(
                    game=game,
                    language=language,
                    ankama_id=ankama_id
                )

                # Extract relevant fields
                item_name = getattr(detailed_quest_item, 'name', "Unknown")
                item_description = getattr(detailed_quest_item, 'description', None)
                item_type_obj = getattr(detailed_quest_item, 'type', None)
                item_type_name = getattr(item_type_obj, 'name', None) if item_type_obj else None
                item_level = getattr(detailed_quest_item, 'level', None)
                item_pods = getattr(detailed_quest_item, 'pods', None)
                image_urls = getattr(detailed_quest_item, 'image_urls', None)
                image_sd = getattr(image_urls, 'sd', None) if image_urls else None
                item_effects = getattr(detailed_quest_item, 'effects', None)
                item_conditions = getattr(detailed_quest_item, 'conditions', None)

                # Build the embed
                embed_color = discord.Color.blurple()
                embed = discord.Embed(title=item_name, color=embed_color)

                # Add description
                if item_description:
                    embed.description = item_description

                # Add type
                if item_type_name:
                    embed.add_field(name=_("key_words.type"), value=item_type_name, inline=True)

                # Add level
                if item_level is not None:
                    embed.add_field(name=_("key_words.level"), value=str(item_level), inline=True)

                # Add pods
                if item_pods is not None:
                    embed.add_field(name=_("key_words.pods"), value=str(item_pods), inline=True)

                # Add effects
                if item_effects:
                    effect_lines = [
                        f"- {effect.formatted}" for effect in item_effects if getattr(effect, 'formatted', None)
                    ]
                    if effect_lines:
                        embed.add_field(
                            name=_("key_words.effects"),
                            value="\n".join(effect_lines),
                            inline=False
                        )

                # Add conditions
                if item_conditions:
                    # Assuming conditions are strings or have a "condition" attribute
                    conditions_text = getattr(item_conditions, 'condition', None) or str(item_conditions)
                    embed.add_field(name=_("key_words.conditions"), value=conditions_text, inline=False)

                # Add image
                if image_sd:
                    embed.set_image(url=image_sd)

                # Send the embed
                await ctx.send(embed=embed)
                return

            except ApiException as e:
                await ctx.send(f"Error al obtener Misión detallada: {e}")
                return
        
        
        cosmetic_types = [
            _("cosmetic_types.wings"),
            _("cosmetic_types.weapon"),
            _("cosmetic_types.dragopavo_gear"),
            _("cosmetic_types.mulagua_gear"),
            _("cosmetic_types.vueloceronte_gear"),
            _("cosmetic_types.cape"),
            _("cosmetic_types.shield"),
            _("cosmetic_types.shoulders"),
            _("cosmetic_types.pet"),
            _("cosmetic_types.pet_gear"),
            _("cosmetic_types.misc_cosmetics"),
            _("cosmetic_types.living_item"),
            _("cosmetic_types.hat"),
            _("cosmetic_types.outfit")
        ]

        # ---------------------------
        # If it's Equipment, fetch more details
        # ---------------------------
        if category == "Equipment" and ankama_id is not None:
            try:
                equipment_api = dofusdude.EquipmentApi(api_client)
                matched_item = equipment_api.get_items_equipment_single(
                    game=game,
                    language=language,
                    ankama_id=ankama_id
                )
            except ApiException:
                await ctx.send(f"Error al obtener Equipamiento detallado: {e}")
                pass
            
        # For all else (including equip with extra info now), we do pagination logic
        item_name = getattr(matched_item, 'name', "Unknown")
        item_type_obj = getattr(matched_item, 'type', None)
        item_type_name = getattr(item_type_obj, 'name', None)

        if item_type_name in cosmetic_types:
            # Fetch detailed cosmetic data
            try:
                cosmetics_api = dofusdude.CosmeticsApi(api_client)
                detailed_cosmetic = cosmetics_api.get_cosmetics_single(
                    game=game,
                    language=language,
                    ankama_id=ankama_id
                )

                # Extract relevant fields
                item_name = getattr(detailed_cosmetic, 'name', "Desconocido")
                item_description = getattr(detailed_cosmetic, 'description', None)
                item_type_obj = getattr(detailed_cosmetic, 'type', None)
                item_type_name = getattr(item_type_obj, 'name', None)
                item_pods = getattr(detailed_cosmetic, 'pods', None)
                image_urls = getattr(detailed_cosmetic, 'image_urls', None)
                image_sd = getattr(image_urls, 'sd', None) if image_urls else None
                parent_set = getattr(detailed_cosmetic, 'parent_set', None)
                parent_set_name = getattr(parent_set, 'name', None) if parent_set else None

                # Build the embed for the cosmetic item
                embed_color = discord.Color.blurple()
                embed = discord.Embed(title=item_name, color=embed_color)

                # Add description
                if item_description:
                    embed.description = item_description

                # Add type name
                if item_type_name:
                    embed.add_field(name=_("key_words.type"), value=item_type_name, inline=True)

                # Add pods
                if item_pods is not None:
                    embed.add_field(name=_("key_words.pods"), value=str(item_pods), inline=True)

                # Add parent set
                if parent_set_name:
                    embed.add_field(name=_("key_words.cosmetic_set"), value=parent_set_name, inline=False)

                # Add image
                if image_sd:
                    embed.set_image(url=image_sd)

                # Send the embed
                await ctx.send(embed=embed)
                
                return

            except ApiException as e:
                await ctx.send(f"Error al obtener datos del cosmético: {e}")
                return
        
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

        if item_type_name:
            page1.add_field(name=_("key_words.type"), value=item_type_name, inline=True)

        if item_level is not None:
            page1.add_field(name=_("key_words.level"), value=str(item_level), inline=True)

        if item_effects:
            eff_lines = []
            for eff in item_effects:
                eff_name = getattr(getattr(eff, 'type', None), 'name', '').capitalize()
                eff_formatted = getattr(eff, 'formatted', '')
                if eff_name and eff_formatted:
                    eff_lines.append(f"- **{eff_name}**: {eff_formatted}")
            if eff_lines:
                page1.add_field(name=_("key_words.effects"), value="\n".join(eff_lines), inline=False)

        # Stats
        stats_lines = []
        if item_range is not None:
            stats_lines.append(f"**{_('key_words.range')}**: {item_range}")
        if item_ap_cost is not None:
            stats_lines.append(f"**{_('key_words.ap_cost')}**: {item_ap_cost}")
        if item_max_cast is not None:
            stats_lines.append(f"**{_('key_words.turn')}**: {item_max_cast}")
        if item_crit_prob is not None:
            stats_lines.append(f"**{_('key_words.crit_prob')}**: {item_crit_prob}%")
        if item_crit_bonus is not None:
            stats_lines.append(f"**{_('key_words.crit_bonus')}**: {item_crit_bonus}")
        if stats_lines:
            page1.add_field(
                name=_("key_words.additional_stats"),
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

        # If the description is <= 300 chars, all in one page
        if len(item_description) <= 300:
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