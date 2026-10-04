"""Material Icons for text labels, written as :name: in the text.

The font is Google's Material Icons (Apache 2.0), the same set the web
designer offers. It is downloaded on first use into a per-user cache rather
than shipped with the package.
"""

import difflib
import logging
import os
import sys
import tempfile
import urllib.request
from functools import lru_cache

from PIL import ImageFont

log = logging.getLogger(__name__)

# Pinned to one commit so everyone renders the same glyphs under the same names.
_BASE_URL = ("https://raw.githubusercontent.com/google/material-design-icons/"
             "f7bd4f25f3764883717c09a1fd867f560c9a9581/font/")
FONT_FILE = "MaterialIcons-Regular.ttf"
CODEPOINTS_FILE = "MaterialIcons-Regular.codepoints"

# How far below the cap height the middle of an icon sits, as a fraction of
# the font size: centres an icon on capitals and digits rather than on the
# baseline, where icon fonts put the bottom of the glyph.
_ICON_MIDDLE = 0.36


class IconError(ValueError):
    """An icon name that does not exist, or a font that could not be fetched."""


def cache_dir() -> str:
    """Where the downloaded font is kept: FICHERO_CACHE, or the platform's
    per-user cache directory."""
    if os.environ.get("FICHERO_CACHE"):
        return os.environ["FICHERO_CACHE"]
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "fichero")


def _fetch(name: str) -> str:
    """Path to a cached font file, downloading it the first time."""
    directory = cache_dir()
    path = os.path.join(directory, name)
    if os.path.exists(path):
        return path
    os.makedirs(directory, exist_ok=True)
    url = _BASE_URL + name
    print(f"  Downloading {name} (first use) to {directory}", file=sys.stderr)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
    except OSError as e:
        raise IconError(f"Could not download the icon font from {url}: {e}") from e
    # Write under a temporary name first, so a broken download never sits in
    # the cache looking like a good file.
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=name + ".")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path


@lru_cache(maxsize=1)
def codepoints() -> dict[str, int]:
    """Every icon name and its character in the font."""
    result = {}
    with open(_fetch(CODEPOINTS_FILE), encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                result[parts[0]] = int(parts[1], 16)
    return result


def char(name: str) -> str:
    """The font character for icon *name*, or IconError naming close matches."""
    points = codepoints()
    if name not in points:
        close = difflib.get_close_matches(name, points, n=3, cutoff=0.6)
        hint = f", did you mean {', '.join(f':{c}:' for c in close)}?" if close else ""
        raise IconError(f"Unknown icon :{name}:{hint} (list them with 'fichero icons')")
    return chr(points[name])


@lru_cache(maxsize=None)
def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_fetch(FONT_FILE), size)


def search(term: str | None = None) -> list[str]:
    """Icon names containing *term*, all of them when it is empty."""
    names = sorted(codepoints())
    if not term:
        return names
    term = term.lower()
    return [n for n in names if term in n]


def baseline_offset(size: int) -> int:
    """Pixels to move an icon's baseline down from the text baseline, so the
    icon sits centred on the text's capitals."""
    # Every icon is drawn in the same square, ascent above the baseline and
    # descent below it, so centre that square rather than any one glyph.
    ascent, descent = font(size).getmetrics()
    icon_middle = (descent - ascent) / 2
    return round(-size * _ICON_MIDDLE - icon_middle)
