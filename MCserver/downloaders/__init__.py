from .paper import PaperDownloader
from .purpur import PurpurDownloader
from .vanilla import VanillaDownloader

# import the rest...

DOWNLOADERS = {
    "vanilla": VanillaDownloader,
    "paper": PaperDownloader,
    "purpur": PurpurDownloader,
    # …
}


def get_downloader(name: str):
    try:
        return DOWNLOADERS[name.lower()]
    except KeyError:
        raise ValueError(f"No downloader for '{name}'")
