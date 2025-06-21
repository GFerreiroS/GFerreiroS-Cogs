import re

import aiohttp

from .base import BaseDownloader


class VanillaDownloader(BaseDownloader):
    """
    Downloads the official Mojang “vanilla” Minecraft server.
    """

    # Mojang’s central version manifest
    MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest.json"

    async def get_versions(self) -> list[str]:
        """
        Return only the purely-numeric Java‐edition versions.
        """
        async with aiohttp.ClientSession() as sess:
            async with sess.get(self.MANIFEST_URL) as resp:
                resp.raise_for_status()
                manifest = await resp.json()
        # keep only things like "1", "1.2", "1.2.3" (no snapshots, no alphas)
        all_versions = [v["id"] for v in manifest.get("versions", [])]
        numeric = [v for v in all_versions if re.fullmatch(r"\d+(?:\.\d+)*", v)]
        return numeric

    async def build_url(self, version: str) -> str:
        """
        Return the direct download URL for the server.jar of `version`.
        If `version` == "latest", uses the manifest’s `latest.release` field.
        """
        async with aiohttp.ClientSession() as sess:
            # 1) get the main manifest
            async with sess.get(self.MANIFEST_URL) as resp:
                resp.raise_for_status()
                manifest = await resp.json()

        # 2) resolve "latest"
        if version.lower() == "latest":
            version = manifest.get("latest", {}).get("release")
            if version is None:
                raise RuntimeError("Could not determine latest release")

        # 3) find that version’s sub-manifest URL
        entry = next((v for v in manifest["versions"] if v["id"] == version), None)
        if not entry:
            raise ValueError(f"Version '{version}' not found in manifest")
        version_json_url = entry["url"]

        # 4) fetch the per-version JSON and extract the server download URL
        async with aiohttp.ClientSession() as sess:
            async with sess.get(version_json_url) as resp:
                resp.raise_for_status()
                vd = await resp.json()
        server_info = vd.get("downloads", {}).get("server")
        if not server_info or "url" not in server_info:
            raise RuntimeError(f"No server download URL for version {version}")
        return server_info["url"]
