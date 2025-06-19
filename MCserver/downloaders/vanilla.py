from .base import BaseDownloader


class VanillaDownloader(BaseDownloader):
    def build_url(self, version: str) -> str:
        if version.lower() == "latest":
            # Mojang’s manifest approach
            manifest = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
            # fetch manifest JSON… find latest server URL… (left as exercise)
            ...
        else:
            # same manifest lookup for a specific version
            ...
