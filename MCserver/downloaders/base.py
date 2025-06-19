import abc
import pathlib

import aiohttp


class BaseDownloader(abc.ABC):
    """Abstract interface for a server-jar downloader."""

    base_dir = pathlib.Path("servers")

    @abc.abstractmethod
    def build_url(self, version: str) -> str:
        """Return the download URL for this launcher + version."""
        ...

    async def fetch(self, version: str) -> pathlib.Path:
        """Download the JAR to base_dir/launcher/version/server.jar."""
        url = self.build_url(version)
        dest = self.base_dir / self.__class__.__name__.lower() / version
        dest.mkdir(parents=True, exist_ok=True)
        jar_path = dest / "server.jar"

        async with aiohttp.ClientSession() as sess:
            async with sess.get(url) as resp:
                resp.raise_for_status()
                with jar_path.open("wb") as f:
                    async for chunk in resp.content.iter_chunked(1024):
                        f.write(chunk)
        return jar_path
