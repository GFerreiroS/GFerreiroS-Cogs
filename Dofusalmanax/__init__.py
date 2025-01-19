from .dofusalmanax import Dofusalmanax

async def setup(bot):
    await bot.add_cog(Dofusalmanax(bot))
