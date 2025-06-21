import aiohttp

from .base import BaseDownloader


class LeafDownloader(BaseDownloader):
    PROJECT = "leaf"
    BASE_API = "https://api.leafmc.one/v2/projects"

    async def get_versions(self) -> list[str]:
        """Return all published Paper Minecraft versions."""
        url = f"{self.BASE_API}/{self.PROJECT}"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return data.get("versions", [])

    async def build_url(self, version: str) -> str:
        """
        Return the download URL for the latest *stable* Paper build
        for the given Minecraft version.
        """
        # if user asked for 'latest' version, resolve to the newest MC version
        if version.lower() == "latest":
            versions = await self.get_versions()
            if not versions:
                raise RuntimeError("No Paper versions found")
            version = versions[-1]  # assume sorted ascending

        # fetch all builds for that MC version
        builds_api = f"{self.BASE_API}/{self.PROJECT}/versions/{version}/builds"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(builds_api) as resp:
                resp.raise_for_status()
                data = await resp.json()

        # filter for the "default" (stable) channel
        stable_builds = [
            b["build"] for b in data.get("builds", []) if b.get("channel") == "default"
        ]
        if not stable_builds:
            raise RuntimeError(f"No stable Paper build found for version {version}")

        latest_build = stable_builds[-1]
        jar_name = f"{self.PROJECT}-{version}-{latest_build}.jar"
        return (
            f"{self.BASE_API}/{self.PROJECT}/versions/"
            f"{version}/builds/{latest_build}/downloads/{jar_name}"
        )
