"""Image processing for Fichero D11s thermal label printer."""

import logging
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from fichero import markup
from fichero.profiles import DEFAULT_PROFILE

log = logging.getLogger(__name__)


def floyd_steinberg_dither(img: Image.Image) -> Image.Image:
    """Floyd-Steinberg error-diffusion dithering to 1-bit.

    Same algorithm as PrinterImageProcessor.ditherFloydSteinberg() in the
    decompiled Fichero APK: distributes quantisation error to neighbouring
    pixels with weights 7/16, 3/16, 5/16, 1/16.
    """
    arr = np.array(img, dtype=np.float32)
    h, w = arr.shape

    for y in range(h):
        for x in range(w):
            old = arr[y, x]
            new = 0.0 if old < 128 else 255.0
            arr[y, x] = new
            err = old - new
            if x + 1 < w:
                arr[y, x + 1] += err * 7 / 16
            if y + 1 < h:
                if x - 1 >= 0:
                    arr[y + 1, x - 1] += err * 3 / 16
                arr[y + 1, x] += err * 5 / 16
                if x + 1 < w:
                    arr[y + 1, x + 1] += err * 1 / 16

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="L")


def prepare_image(
    img: Image.Image,
    max_rows: int = 240,
    dither: bool = True,
    printhead_px: int = DEFAULT_PROFILE.printhead_px,
) -> Image.Image:
    """Scale any image to the printhead width, 1-bit, black on white.

    When *dither* is True (default), uses Floyd-Steinberg error diffusion
    for better quality on photos and gradients.  Set False for crisp text.
    """
    img = img.convert("L")
    w, h = img.size
    new_h = int(h * (printhead_px / w))
    img = img.resize((printhead_px, new_h), Image.LANCZOS)

    if new_h > max_rows:
        log.warning("Image height %dpx exceeds max %dpx, cropping bottom", new_h, max_rows)
        img = img.crop((0, 0, printhead_px, max_rows))

    img = ImageOps.autocontrast(img, cutoff=1)

    if dither:
        img = floyd_steinberg_dither(img)

    # Pack to 1-bit.  PIL mode "1" tobytes() uses 0-bit=black, 1-bit=white,
    # but the printer wants 1-bit=black.  Mapping dark->1 via point() inverts
    # the PIL convention so the final packed bits match what the printer needs.
    img = img.point(lambda x: 1 if x < 128 else 0, "1")
    return img


def image_to_raster(
    img: Image.Image, printhead_px: int = DEFAULT_PROFILE.printhead_px
) -> bytes:
    """Pack 1-bit image into raw raster bytes, MSB first."""
    if img.mode != "1":
        raise ValueError(f"Expected mode '1', got '{img.mode}'")
    if img.width != printhead_px:
        raise ValueError(f"Expected width {printhead_px}, got {img.width}")
    return img.tobytes()


def load_font(name: str | None, font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType font by path or name, falling back to Pillow's default.

    A bare name like "arial" or "consolab.ttf" is resolved by Pillow against
    the system font directories, so the extension may be left off.
    """
    if not name:
        return ImageFont.load_default(size=font_size)

    candidates = [name]
    if not name.lower().endswith((".ttf", ".ttc", ".otf")):
        candidates += [name + ".ttf", name + ".ttc", name + ".otf"]

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, font_size)
        except OSError:
            continue

    raise ValueError(f"Font not found: {name!r}")


# File name suffixes a font family uses for its bold/italic faces. The short
# ones are Windows' own (arialbd, ariali, arialbi, consolab, consolaz).
_VARIANT_SUFFIXES = {
    (True, False): ["bd", "b", "-Bold", "Bold", "_Bold", " Bold"],
    (False, True): ["i", "-Italic", "-Oblique", "Italic", "-It", " Italic"],
    (True, True): ["bi", "z", "-BoldItalic", "-BoldOblique", "BoldItalic", " Bold Italic"],
}
_REGULAR_SUFFIXES = ("-Regular", "-Roman", "-Book", "Regular", " Regular")

# Slant of a synthesised italic, in pixels sideways per pixel up.
_FAKE_ITALIC_SLANT = 0.2


class FontFamily:
    """Regular, bold, italic and bold-italic faces of one font, at any size.

    A face that cannot be found is synthesised: bold by drawing the glyphs
    a few pixels apart, italic by shearing them.
    """

    def __init__(self, name: str | None, bold: str | None = None,
                 italic: str | None = None, bold_italic: str | None = None):
        self.name = name
        self._explicit = {(True, False): bold, (False, True): italic,
                          (True, True): bold_italic}
        self._files: dict[tuple[bool, bool], str | None] = {}
        self._cache: dict[tuple, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}

    def get(self, bold: bool, italic: bool, size: int):
        """Return (font, fake_bold, fake_italic) for a style and size."""
        key = (bold, italic)
        face = key
        if key != (False, False) and self._file(key) is None:
            # Fall back to the nearest face that exists and fake the rest.
            for alt in ((bold, False), (False, italic), (False, False)):
                if alt == (False, False) or self._file(alt) is not None:
                    face = alt
                    break
        font = self._load(face, size)
        return font, bold and not face[0], italic and not face[1]

    def _load(self, face: tuple[bool, bool], size: int):
        cache_key = (face, size)
        if cache_key not in self._cache:
            if face == (False, False):
                self._cache[cache_key] = load_font(self.name, size)
            else:
                self._cache[cache_key] = ImageFont.truetype(self._file(face), size)
        return self._cache[cache_key]

    def _file(self, face: tuple[bool, bool]) -> str | None:
        if face not in self._files:
            self._files[face] = self._find(face)
        return self._files[face]

    def _find(self, face: tuple[bool, bool]) -> str | None:
        explicit = self._explicit.get(face)
        if explicit:
            return load_font(explicit, 10).path
        if not self.name:
            return None
        regular = load_font(self.name, 10).path
        stem, ext = os.path.splitext(regular)
        for suffix in _REGULAR_SUFFIXES:
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        for suffix in _VARIANT_SUFFIXES[face]:
            candidate = stem + suffix + ext
            try:
                ImageFont.truetype(candidate, 10)
            except OSError:
                continue
            log.debug("Using %s for %s", candidate, face)
            return candidate
        return None


def _paste_ink(canvas: Image.Image, ink: Image.Image, xy: tuple[int, int]) -> None:
    """Paste the black pixels of *ink* (black on white) onto *canvas*."""
    mask = ImageOps.invert(ink).point(lambda v: 255 if v >= 128 else 0)
    canvas.paste(0, (xy[0], xy[1], xy[0] + ink.width, xy[1] + ink.height), mask)


def _draw_span(canvas: Image.Image, x: float, baseline: int, text: str, font,
               fake_bold: int, fake_italic: bool, ascent: int, descent: int) -> None:
    """Draw *text* with its baseline at *baseline*, starting at *x*."""
    if not text:
        return
    if not fake_italic:
        draw = ImageDraw.Draw(canvas)
        draw.fontmode = "1"
        for dx in range(fake_bold + 1):
            draw.text((x + dx, baseline), text, fill=0, font=font, anchor="ls")
        return

    # Render on its own strip, shear it about the baseline, paste it back.
    width = int(font.getlength(text)) + fake_bold + 1
    pad_l = int(_FAKE_ITALIC_SLANT * descent) + 1
    pad_r = int(_FAKE_ITALIC_SLANT * ascent) + 1
    strip = Image.new("L", (width + pad_l + pad_r, ascent + descent), 255)
    draw = ImageDraw.Draw(strip)
    draw.fontmode = "1"
    for dx in range(fake_bold + 1):
        draw.text((pad_l + dx, ascent), text, fill=0, font=font, anchor="ls")
    s = _FAKE_ITALIC_SLANT
    strip = strip.transform(strip.size, Image.AFFINE, (1, s, -s * ascent, 0, 1, 0),
                            resample=Image.BILINEAR, fillcolor=255)
    _paste_ink(canvas, strip, (int(x) - pad_l, baseline - ascent))


def _render_markup(lines: list[markup.Line], family: FontFamily, font_size: int,
                   align: str, line_spacing: int) -> Image.Image:
    """Lay out styled lines on a generous white canvas, black ink."""
    laid_out = []  # (line, size, ascent, descent, width, pieces)
    for line in lines:
        size = max(1, round(font_size * line.scale))
        ascent, descent = family.get(False, False, size)[0].getmetrics()
        pieces = []
        x = 0.0
        for span in line.spans:
            st = span.style
            font, fake_bold, fake_italic = family.get(st.bold, st.italic, size)
            bold_px = max(1, size // 12) if fake_bold else 0
            advance = font.getlength(span.text) + bold_px
            pieces.append((x, advance, span, font, bold_px, fake_italic))
            x += advance
        laid_out.append((size, ascent, descent, x, pieces))

    block_w = max((w for _, _, _, w, _ in laid_out), default=0)
    block_h = sum(a + d for _, a, d, _, _ in laid_out) + line_spacing * (len(laid_out) - 1)
    margin = max(font_size, *(s for s, *_ in laid_out)) if laid_out else font_size

    img = Image.new("L", (int(block_w) + 2 * margin, int(block_h) + 2 * margin), 255)
    draw = ImageDraw.Draw(img)
    y = margin
    for size, ascent, descent, width, pieces in laid_out:
        if align == "left":
            x0 = margin
        elif align == "right":
            x0 = margin + block_w - width
        else:
            x0 = margin + (block_w - width) / 2
        baseline = y + ascent
        thickness = max(1, size // 15)
        for x, advance, span, font, bold_px, fake_italic in pieces:
            _draw_span(img, x0 + x, baseline, span.text, font, bold_px, fake_italic,
                       ascent, descent)
            left, right = round(x0 + x), round(x0 + x + advance) - 1
            if span.style.underline and span.text.strip():
                top = baseline + max(1, descent // 3)
                draw.rectangle((left, top, right, top + thickness - 1), fill=0)
            if span.style.strike and span.text.strip():
                top = baseline - round(size * 0.3) - thickness // 2
                draw.rectangle((left, top, right, top + thickness - 1), fill=0)
        y += ascent + descent + line_spacing
    return img


def text_to_image(
    text: str,
    font_size: int = 30,
    label_height: int = 240,
    font: "str | FontFamily | None" = None,
    align: str = "center",
    line_spacing: int = 4,
    rotate: int = 0,
    printhead_px: int = DEFAULT_PROFILE.printhead_px,
    use_markup: bool = True,
) -> Image.Image:
    """Render crisp 1-bit text, centred on the label.

    *text* may contain newlines for multi-line labels, and Markdown-style
    formatting (see fichero.markup) unless *use_markup* is False. *font* is
    a font name or path, or a FontFamily to also pick its bold and italic
    faces explicitly.

    *rotate* is how the text sits on the label when you hold it the long way
    round, like the web designer shows it:

    - 0 reads along the feed direction; lines stack across the printhead, so
      tall multi-line blocks need a smaller *font_size*.
    - 90 reads across the label, a quarter turn anticlockwise; each line is
      limited to the printhead width and the lines stack down the label,
      which is what you want for a stack of short lines.
    - 180 and 270 are those two upside down.

    Which of the two reads naturally depends on the printer: a D11s prints
    across the short side of its label, a D1-4777 across the long side, so
    each profile carries the *rotate* its labels want.

    The printer always receives a *printhead_px*-wide image, so the canvas is
    laid out in whichever direction survives the rotation.
    """
    if rotate not in (0, 90, 180, 270):
        raise ValueError(f"rotate must be 0, 90, 180 or 270, got {rotate}")

    # Rotation applied to the canvas to get the printer's 96px-wide raster.
    # The web client turns the label canvas clockwise (ImageEncoder.rotateCW90
    # with printDirection "left"), which is PIL's rotate(270), so the label
    # edge that prints first is the left one - same as the designer shows it.
    img_rotation = (rotate + 270) % 360
    if img_rotation in (90, 270):
        canvas_w, canvas_h = label_height, printhead_px
    else:
        canvas_w, canvas_h = printhead_px, label_height

    img = Image.new("L", (canvas_w, canvas_h), 255)

    family = font if isinstance(font, FontFamily) else FontFamily(font)
    lines = markup.parse(text) if use_markup else markup.plain(text)
    block = _render_markup(lines, family, font_size, align, line_spacing)

    # Centre on the ink bounding box, so the block sits optically centred
    # whether or not the text has ascenders or descenders.
    bbox = ImageOps.invert(block).getbbox()
    if bbox:
        block = block.crop(bbox)
        tw, th = block.size
        if tw > canvas_w or th > canvas_h:
            log.warning("Text block is %dx%dpx, label area is %dx%dpx - it will be cut off "
                        "(reduce --font-size, or raise --label-length)",
                        tw, th, canvas_w, canvas_h)
        _paste_ink(img, block, ((canvas_w - tw) // 2, (canvas_h - th) // 2))

    if img_rotation:
        img = img.rotate(img_rotation, expand=True)
    return img
