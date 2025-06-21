import aiohttp

from .base import BaseDownloader


class PurpurDownloader(BaseDownloader):
    PROJECT = "purpur"
    BASE_API = "https://api.purpurmc.org/v2"

    async def get_versions(self) -> list[str]:
        """
        Fetch the list of available Purpur versions.
        """
        url = f"{self.BASE_API}/{self.PROJECT}"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return data.get("versions", [])

    async def build_url(self, version: str) -> str:
        """
        Return the download URL for the latest build of the given Purpur version.
        If `version` is 'latest', resolves to the current version from metadata.
        """
        # Resolve "latest" to the metadata current version
        if version.lower() == "latest":
            meta_url = f"{self.BASE_API}/{self.PROJECT}"
            async with aiohttp.ClientSession() as sess:
                async with sess.get(meta_url) as resp:
                    resp.raise_for_status()
                    meta = await resp.json()
            version = meta.get("metadata", {}).get("current")
            if not version:
                raise RuntimeError("Could not determine current Purpur version")

        # Fetch build info for that version
        builds_url = f"{self.BASE_API}/{self.PROJECT}/{version}/"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(builds_url) as resp:
                resp.raise_for_status()
                data = await resp.json()

        # Pick the latest build
        latest_build = data.get("builds", {}).get("latest")
        if not latest_build:
            raise RuntimeError(f"No builds found for Purpur {version}")

        # Construct download URL
        return f"{self.BASE_API}/{self.PROJECT}/{version}/{latest_build}/download"
