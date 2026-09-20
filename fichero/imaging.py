"""Image processing for Fichero D11s thermal label printer."""

import logging

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

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


def text_to_image(
    text: str,
    font_size: int = 30,
    label_height: int = 240,
    font: str | None = None,
    align: str = "center",
    line_spacing: int = 4,
    rotate: int = 0,
    printhead_px: int = DEFAULT_PROFILE.printhead_px,
) -> Image.Image:
    """Render crisp 1-bit text, centred on the label.

    *text* may contain newlines for multi-line labels.

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
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"  # disable antialiasing - pure 1-bit glyph rendering

    font_obj = load_font(font, font_size)

    # textbbox() delegates to multiline_textbbox() when text contains newlines;
    # spacing/align are ignored for single-line text.
    bbox = draw.textbbox((0, 0), text, font=font_obj, spacing=line_spacing, align=align)
    tw, th = round(bbox[2] - bbox[0]), round(bbox[3] - bbox[1])

    if tw > canvas_w or th > canvas_h:
        log.warning("Text block is %dx%dpx, label area is %dx%dpx - it will be cut off "
                    "(reduce --font-size, or raise --label-length)",
                    tw, th, canvas_w, canvas_h)

    # Centre on the ink bounding box, so the block sits optically centred
    # whether or not the text has ascenders or descenders.
    x = (canvas_w - tw) // 2 - bbox[0]
    y = (canvas_h - th) // 2 - bbox[1]
    draw.text((x, y), text, fill=0, font=font_obj, spacing=line_spacing, align=align)

    if img_rotation:
        img = img.rotate(img_rotation, expand=True)
    return img
