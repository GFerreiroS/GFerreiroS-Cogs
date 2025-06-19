from .base import BaseDownloader


class PurpurDownloader(BaseDownloader):
    def build_url(self, version: str) -> str:
        # Purpur uses static URLs:
        return f"https://api.purpurmc.org/v2/purpur/{version}/download"
