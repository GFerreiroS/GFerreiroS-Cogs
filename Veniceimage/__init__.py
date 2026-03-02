from .veniceimage import Veniceimage


async def setup(bot):
    await bot.add_cog(Veniceimage(bot))
