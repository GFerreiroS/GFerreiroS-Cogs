import abc
import pathlib

import aiohttp


class BaseDownloader(abc.ABC):
    """Abstract interface for a server-jar downloader."""

    base_dir = pathlib.Path("servers")

    @abc.abstractmethod
    async def build_url(self, version: str) -> str:
        """Return the download URL for this launcher + version."""
        ...

    async def fetch(
        self,
        version: str,
        *,
        dest_dir: pathlib.Path | None = None,
    ) -> pathlib.Path:
        """
        Download the JAR into `dest_dir/server.jar` if given,
        otherwise into base_dir/launcher/version/server.jar.
        """
        url = await self.build_url(version)
        if dest_dir is None:
            dest = self.base_dir / self.__class__.__name__.lower() / version
        else:
            dest = dest_dir
        dest.mkdir(parents=True, exist_ok=True)
        jar_path = dest / "server.jar"

        async with aiohttp.ClientSession() as sess:
            async with sess.get(url) as resp:
                resp.raise_for_status()
                with jar_path.open("wb") as f:
                    async for chunk in resp.content.iter_chunked(1024):
                        f.write(chunk)
        return jar_path
