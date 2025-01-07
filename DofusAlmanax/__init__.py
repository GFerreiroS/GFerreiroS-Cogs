from .dofusalmanax import DofusAlmanax

async def setup(bot):
    await bot.add_cog(DofusAlmanax(bot))
