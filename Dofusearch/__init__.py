from .dofusearch import Dofusearch

async def setup(bot):
    await bot.add_cog(Dofusearch(bot))
