from .mcserver import MCserver


async def setup(bot):
    await bot.add_cog(MCserver(bot))
