"""CLI for Fichero D11s thermal label printer."""

import argparse
import asyncio
import os
import sys

from PIL import Image

from fichero.imaging import image_to_raster, prepare_image, text_to_image
from fichero.printer import (
    DELAY_AFTER_DENSITY,
    DELAY_AFTER_FEED,
    DELAY_COMMAND_GAP,
    DELAY_RASTER_SETTLE,
    PAPER_GAP,
    PrinterClient,
    PrinterError,
    PrinterNotReady,
    connect,
)
from fichero.profiles import (
    DEFAULT_PROFILE,
    DOTS_PER_MM,
    PROFILES,
    PrinterProfile,
    profile_by_name,
    profile_names,
)


def _forced_profile(args: argparse.Namespace) -> PrinterProfile | None:
    """The profile named by --printer, or None to detect it from the printer."""
    name = getattr(args, "printer", None)
    return profile_by_name(name) if name else None


def _offline_profile(args: argparse.Namespace) -> PrinterProfile:
    """Profile to render against when not connecting, as for --preview."""
    return _forced_profile(args) or DEFAULT_PROFILE


def _resolve_label_height(args: argparse.Namespace, profile: PrinterProfile) -> int:
    """Label length in pixels, from --label-length (mm), --label-height (px),
    or the profile's own default."""
    if args.label_length is not None:
        return args.label_length * DOTS_PER_MM
    if args.label_height is not None:
        return args.label_height
    return profile.default_label_px


def _resolve_rotate(args: argparse.Namespace, profile: PrinterProfile) -> int:
    """Rotation from --rotate, FICHERO_ROTATE, or the profile's own default."""
    if args.rotate is not None:
        return args.rotate
    env = os.environ.get("FICHERO_ROTATE")
    if env:
        return int(env)
    return profile.default_rotate


async def do_print(
    pc: PrinterClient,
    img: Image.Image,
    density: int = 1,
    paper: int = PAPER_GAP,
    copies: int = 1,
    dither: bool = True,
    max_rows: int = 240,
) -> bool:
    profile = pc.profile
    img = prepare_image(img, max_rows=max_rows, dither=dither,
                        printhead_px=profile.printhead_px)
    rows = img.height
    raster = image_to_raster(img, printhead_px=profile.printhead_px)

    print(f"  Image: {img.width}x{rows}, {len(raster)} bytes, {copies} copies")

    await pc.set_density(density)
    await asyncio.sleep(DELAY_AFTER_DENSITY)

    for copy_num in range(copies):
        if copies > 1:
            print(f"  Copy {copy_num + 1}/{copies}...")

        # Check status before each copy (matches decompiled app behaviour)
        status = await pc.get_status()
        if not status.ok:
            raise PrinterNotReady(f"Printer not ready: {status}")

        # Print sequence from the decompiled APK. The enable/stop commands and
        # the final feed come from the profile, because they differ per model.
        await pc.set_paper_type(paper)
        await asyncio.sleep(DELAY_COMMAND_GAP)
        await pc.wakeup()
        await asyncio.sleep(DELAY_COMMAND_GAP)
        await pc.enable()
        await asyncio.sleep(DELAY_COMMAND_GAP)

        # Raster image: GS v 0 m xL xH yL yH <data>
        cols = profile.bytes_per_row
        yl = rows & 0xFF
        yh = (rows >> 8) & 0xFF
        header = bytes([0x1D, 0x76, 0x30, 0x00,
                        cols & 0xFF, (cols >> 8) & 0xFF, yl, yh])
        await pc.send_chunked(header + raster)

        await asyncio.sleep(DELAY_RASTER_SETTLE)
        await pc.finish_label()
        await asyncio.sleep(DELAY_AFTER_FEED)

        ok = await pc.stop_print()
        if not ok:
            print("  WARNING: no OK/0xAA from stop command")

    return True


async def cmd_info(args: argparse.Namespace) -> None:
    async with connect(args.address, classic=args.classic, channel=args.channel) as pc:
        info = await pc.get_info()
        for k, v in info.items():
            print(f"  {k}: {v}")

        print()
        all_info = await pc.get_all_info()
        for k, v in all_info.items():
            print(f"  {k}: {v}")


async def cmd_status(args: argparse.Namespace) -> None:
    async with connect(args.address, classic=args.classic, channel=args.channel) as pc:
        status = await pc.get_status()
        print(f"  Status: {status}")
        print(f"  Raw: 0x{status.raw:02X} ({status.raw:08b})")
        print(f"  printing={status.printing} cover_open={status.cover_open} "
              f"no_paper={status.no_paper} low_battery={status.low_battery} "
              f"overheated={status.overheated} charging={status.charging}")


def _resolve_text(args: argparse.Namespace) -> str:
    """Join positional words into one line; each --line adds another line.

    A literal backslash-n in the positional text is also treated as a line
    break, so shells that cannot produce a real newline can still make
    multi-line labels.
    """
    lines = []
    if args.text:
        joined = " ".join(args.text).replace("\\n", "\n")
        lines.extend(joined.split("\n"))
    lines.extend(args.line or [])
    if not lines:
        raise SystemExit("  ERROR: give some text, either positionally or via --line")
    return "\n".join(lines)


def _render_text(args: argparse.Namespace, text: str, profile: PrinterProfile):
    """Render *text* for *profile*, returning the image and its row count."""
    label_h = _resolve_label_height(args, profile)
    img = text_to_image(text, font_size=args.font_size, label_height=label_h,
                        font=args.font, align=args.align,
                        line_spacing=args.line_spacing,
                        rotate=_resolve_rotate(args, profile),
                        printhead_px=profile.printhead_px)
    return img, label_h


async def cmd_text(args: argparse.Namespace) -> None:
    text = _resolve_text(args)

    # Rendering needs the printhead width, so when we are going to print we
    # connect first and render for whatever printer answered.
    if args.preview:
        profile = _offline_profile(args)
        img, _ = _render_text(args, text, profile)
        img.save(args.preview)
        print(f"Preview written to {args.preview} ({img.width}x{img.height}) "
              f"for {profile.name}, not printing.")
        return

    async with connect(args.address, classic=args.classic, channel=args.channel,
                       profile=_forced_profile(args)) as pc:
        _announce_profile(pc)
        img, label_h = _render_text(args, text, pc.profile)
        shown = text.replace("\n", " / ")
        print(f'Printing "{shown}"...')
        ok = await do_print(pc, img, args.density, paper=args.paper,
                            copies=args.copies, dither=False, max_rows=label_h)
        print("Done." if ok else "FAILED.")


def _announce_profile(pc: PrinterClient) -> None:
    p = pc.profile
    how = "detected" if pc.profile_detected else "assumed"
    print(f"  Printer: {p.name} ({how}), {p.printhead_px}px / {p.printhead_mm:.0f}mm head")
    if not pc.profile_detected:
        print("  Pass --printer to pick a profile if this one is wrong "
              f"({', '.join(profile_names())})")


def cmd_fonts(args: argparse.Namespace) -> None:
    """List font files Pillow can resolve by bare name."""
    seen = set()
    for directory in _font_dirs():
        if not os.path.isdir(directory):
            continue
        for entry in sorted(os.listdir(directory)):
            if entry.lower().endswith((".ttf", ".ttc", ".otf")) and entry not in seen:
                seen.add(entry)
                print(f"  {entry}")
    if not seen:
        print("  No font files found; pass a full path to --font instead.")


def _font_dirs() -> list[str]:
    windir = os.environ.get("WINDIR")
    dirs = []
    if windir:
        dirs.append(os.path.join(windir, "fonts"))
        dirs.append(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts"))
    dirs += ["/usr/share/fonts", "/usr/local/share/fonts",
             os.path.expanduser("~/.fonts"), "/Library/Fonts",
             os.path.expanduser("~/Library/Fonts")]
    return dirs


async def cmd_image(args: argparse.Namespace) -> None:
    img = Image.open(args.path)
    async with connect(args.address, classic=args.classic, channel=args.channel,
                       profile=_forced_profile(args)) as pc:
        _announce_profile(pc)
        label_h = _resolve_label_height(args, pc.profile)
        print(f"Printing {args.path}...")
        ok = await do_print(pc, img, args.density, paper=args.paper,
                            copies=args.copies, dither=not args.no_dither,
                            max_rows=label_h)
        print("Done." if ok else "FAILED.")


def cmd_profiles(args: argparse.Namespace) -> None:
    """List the printer profiles this package knows."""
    for p in PROFILES:
        feed = "form feed" if p.feed_dots is None else f"{p.feed_dots} dots"
        print(f"  {p.name}")
        print(f"      {p.description}")
        print(f"      models        {', '.join(p.models)}")
        print(f"      printhead     {p.printhead_px}px / {p.printhead_mm:.0f}mm")
        print(f"      label         {p.default_label_mm}mm, default rotate {p.default_rotate}")
        print(f"      feed          {feed}")
        print(f"      paper type    {'yes' if p.supports_paper_type else 'not supported'}")
        if p.aliases:
            print(f"      aliases       {', '.join(p.aliases)}")


async def cmd_set(args: argparse.Namespace) -> None:
    async with connect(args.address, classic=args.classic, channel=args.channel) as pc:
        if args.setting == "density":
            val = int(args.value)
            if not 0 <= val <= 2:
                print("  ERROR: density must be 0, 1, or 2")
                return
            ok = await pc.set_density(val)
            print(f"  Set density={args.value}: {'OK' if ok else 'FAILED'}")
        elif args.setting == "shutdown":
            val = int(args.value)
            if not 1 <= val <= 480:
                print("  ERROR: shutdown must be 1-480 minutes")
                return
            ok = await pc.set_shutdown_time(val)
            print(f"  Set shutdown={args.value}min: {'OK' if ok else 'FAILED'}")
        elif args.setting == "paper":
            types = {"gap": 0, "black": 1, "continuous": 2}
            if args.value in types:
                val = types[args.value]
            else:
                try:
                    val = int(args.value)
                except ValueError:
                    print("  ERROR: paper must be gap, black, continuous, or 0-2")
                    return
                if not 0 <= val <= 2:
                    print("  ERROR: paper must be gap, black, continuous, or 0-2")
                    return
            ok = await pc.set_paper_type(val)
            print(f"  Set paper={args.value}: {'OK' if ok else 'FAILED'}")


def _add_paper_arg(parser: argparse.ArgumentParser) -> None:
    """Add --paper argument to a subparser."""
    parser.add_argument(
        "--paper", type=str, default="gap",
        help="Paper type: gap (default), black, continuous",
    )


def _parse_paper(value: str) -> int:
    """Convert paper string/int to protocol value."""
    types = {"gap": 0, "black": 1, "continuous": 2}
    if value in types:
        return types[value]
    try:
        val = int(value)
        if 0 <= val <= 2:
            return val
    except ValueError:
        pass
    print(f"  WARNING: unknown paper type '{value}', using gap")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Fichero D11s Label Printer")
    parser.add_argument("--address", default=os.environ.get("FICHERO_ADDR"),
                        help="BLE address (skip scanning, or set FICHERO_ADDR)")
    parser.add_argument("--classic", action="store_true",
                        default=os.environ.get("FICHERO_TRANSPORT", "").lower() == "classic",
                        help="Use Classic Bluetooth (RFCOMM) instead of BLE (Linux only, "
                             "or set FICHERO_TRANSPORT=classic)")
    parser.add_argument("--channel", type=int, default=1,
                        help="RFCOMM channel (default: 1, only used with --classic)")
    parser.add_argument("--printer", default=os.environ.get("FICHERO_PRINTER"),
                        help="Force a printer profile instead of detecting it from the "
                             f"model ({', '.join(profile_names())}), or set "
                             "FICHERO_PRINTER. Also picks the profile that --preview "
                             "renders for")
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="Show device info")
    p_info.set_defaults(func=cmd_info)

    p_status = sub.add_parser("status", help="Show detailed status")
    p_status.set_defaults(func=cmd_status)

    p_text = sub.add_parser("text", help="Print text label")
    p_text.add_argument("text", nargs="*", help="Text to print")
    p_text.add_argument("--density", type=int, default=2, choices=[0, 1, 2],
                        help="Print density: 0=light, 1=medium, 2=thick")
    p_text.add_argument("--copies", type=int, default=1, help="Number of copies")
    p_text.add_argument("--font-size", type=int, default=30, help="Font size in points")
    p_text.add_argument("--font", default=os.environ.get("FICHERO_FONT"),
                        help="TrueType font: file path or installed name such as "
                             "'arialbd' (or set FICHERO_FONT). Default: Pillow's "
                             "built-in font")
    p_text.add_argument("--line", action="append", metavar="TEXT",
                        help="Add another line of text; repeat for more lines")
    p_text.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=None,
                        help="How the text sits on the label: 0 reads along the feed "
                             "direction, 90 reads across it with the lines stacked "
                             "down the label. Default: whatever the printer profile "
                             "says reads naturally (or set FICHERO_ROTATE)")
    p_text.add_argument("--align", choices=["left", "center", "right"], default="center",
                        help="Horizontal alignment of multi-line text (default: center)")
    p_text.add_argument("--line-spacing", type=int, default=4,
                        help="Extra pixels between lines (default: 4)")
    p_text.add_argument("--preview", metavar="PATH",
                        help="Save the rendered label to an image file instead of printing")
    p_text.add_argument("--label-length", type=int, default=None,
                        help="Label length in mm. Default: the profile's own size")
    p_text.add_argument("--label-height", type=int, default=None,
                        help="Label length in pixels (prefer --label-length)")
    _add_paper_arg(p_text)
    p_text.set_defaults(func=cmd_text)

    p_image = sub.add_parser("image", help="Print image file")
    p_image.add_argument("path", help="Path to image file")
    p_image.add_argument("--density", type=int, default=2, choices=[0, 1, 2],
                         help="Print density: 0=light, 1=medium, 2=thick")
    p_image.add_argument("--copies", type=int, default=1, help="Number of copies")
    p_image.add_argument("--no-dither", action="store_true",
                         help="Disable Floyd-Steinberg dithering (use simple threshold)")
    p_image.add_argument("--label-length", type=int, default=None,
                         help="Label length in mm. Default: the profile's own size")
    p_image.add_argument("--label-height", type=int, default=None,
                         help="Max image height in pixels (prefer --label-length)")
    _add_paper_arg(p_image)
    p_image.set_defaults(func=cmd_image)

    p_fonts = sub.add_parser("fonts", help="List installed fonts usable with --font")
    p_fonts.set_defaults(func=cmd_fonts, sync=True)

    p_profiles = sub.add_parser("profiles", help="List known printer profiles")
    p_profiles.set_defaults(func=cmd_profiles, sync=True)

    p_set = sub.add_parser("set", help="Change printer settings")
    p_set.add_argument("setting", choices=["density", "shutdown", "paper"],
                       help="Setting to change")
    p_set.add_argument("value", help="New value")
    p_set.set_defaults(func=cmd_set)

    args = parser.parse_args()

    # Resolve --paper string to int for print commands
    if hasattr(args, "paper") and isinstance(args.paper, str):
        args.paper = _parse_paper(args.paper)

    try:
        if getattr(args, "sync", False):
            args.func(args)
        else:
            asyncio.run(args.func(args))
    except (PrinterError, ValueError) as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
