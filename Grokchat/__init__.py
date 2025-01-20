from .grokchat import Grokchat

async def setup(bot):
   await bot.add_cog(Grokchat(bot))