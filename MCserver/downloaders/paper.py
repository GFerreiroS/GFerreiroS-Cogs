import aiohttp

from .base import BaseDownloader


class PaperDownloader(BaseDownloader):
    async def build_url(self, version: str) -> str:
        # PaperMC API: https://api.papermc.io/v2/projects/paper/versions/{version}
        api = f"https://api.papermc.io/v2/projects/paper/versions/{version}"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(api) as r:
                data = await r.json()
        # pick the latest build from data["builds"], then construct download URL
        build = max(data["builds"])
        return f"https://api.papermc.io/v2/projects/paper/versions/{version}/builds/{build}/downloads/paper-{version}-{build}.jar"
