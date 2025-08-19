from .eventoguilds import Eventoguilds


async def setup(bot):
    await bot.add_cog(Eventoguilds(bot))
