# fichero-printer

Web GUI, Python CLI, and protocol documentation for the Fichero D11s thermal label printer.

Blog post: [Reverse Engineering Action's Cheap Fichero Labelprinter](https://blog.dbuglife.com/reverse-engineering-fichero-label-printer/)

The [Fichero](https://www.action.com/nl-nl/p/3212141/fichero-labelprinter/) is a cheap Bluetooth thermal label printer sold at Action. Internally it's an AiYin D11s made by Xiamen Print Future Technology. The official app is closed-source and doesn't expose the protocol, so this project reverse-engineers it from the decompiled APK.

## The printer

- 96px wide printhead, 203 DPI
- Prints 1-bit raster images onto self-adhesive labels (14mm x 30mm default)
- Connects via BLE or Classic Bluetooth SPP
- 18500 Li-Ion battery (1200mAh), USB-C charging
- Bluetooth names: `FICHERO_5836`, `D11s_`

## Why not just use the app?

The Fichero app (`com.lj.fichero`) asks for 26 permissions. For a label printer. The notable ones:

```
ACCESS_FINE_LOCATION         Your precise GPS location
ACCESS_COARSE_LOCATION       Your approximate location
CAMERA                       Your camera
READ_EXTERNAL_STORAGE        Your files
WRITE_EXTERNAL_STORAGE       Your files (write)
READ_MEDIA_IMAGES            Your photos
INTERNET                     Full internet access
ACCESS_WIFI_STATE            Your WiFi info
CHANGE_WIFI_STATE            Change your WiFi settings
CHANGE_WIFI_MULTICAST_STATE  Multicast on your network
AD_ID                        Your advertising ID
ACCESS_ADSERVICES_AD_ID      More ad tracking
ACCESS_ADSERVICES_ATTRIBUTION  Ad attribution tracking
BIND_GET_INSTALL_REFERRER    Where you installed from
```

Some of these are reasonable. The location permissions exist because of how Android handles Bluetooth. Bluetooth signals can reveal where you physically are, think retail stores using Bluetooth beacons to track which aisle you're standing in. So Android won't let any app scan for Bluetooth devices unless it also has location permission. That's not the app being sneaky. That's Android being cautious.

The camera makes sense too. The app lets you scan barcodes and photograph things to print on labels.

The WiFi permissions are baggage from the underlying SDK. It powers over 159 different printer models, some of which connect over WiFi. The Fichero doesn't use WiFi at all, but the permissions are baked into the shared code.

Then there are four permissions that have nothing to do with printing. Your advertising ID is a unique number assigned to your phone that follows you across every app, letting ad networks build a profile of what you do. The app also wants ad attribution tracking (which apps you installed after seeing an ad) and your install referrer (how you found the app store listing). That's a label printer quietly feeding your activity to an ad network.

The package name is `com.lj.fichero` but the SDK inside is from a company called LuckPrinter (`com.luckprinter.sdk_new`). The app is what's called a white-label product: a generic app rebranded with the Fichero name and logo. The same codebase runs receipt printers, A4 thermal printers, and industrial label makers. It supports 159+ printer models across four manufacturers. Your little label printer's app is just a skin on top.

One more reason to ditch the app and talk to the printer directly.

## Web GUI

Try it at https://0xmh.github.io/fichero-printer/ - a full label designer with text, images, barcodes, QR codes, and drag-and-drop canvas editing. Built with Svelte 5 and Fabric.js, ported from the NiimBlue project (MIT).

Click the Bluetooth icon, pair with the printer, and start designing. Labels save to browser localStorage. Export as JSON or PNG.

Requires Web Bluetooth, so Chrome/Edge/Opera only. Firefox and Safari don't support it.

## CLI Setup

Requires Python 3.10+. Create a virtualenv and install the package into it:

```
python -m venv .venv
.venv/bin/pip install -e .
```

On Windows that second line is `.venv\Scripts\pip install -e .`

Activating the virtualenv puts a `fichero` command on your PATH:

```
source .venv/bin/activate              # Linux, macOS
source .venv/Scripts/activate          # Windows, Git Bash
.venv\Scripts\Activate.ps1             # Windows, PowerShell
```

Every example below assumes it is active. Without activating, call the executable
directly instead: `.venv/bin/fichero ...`, or `.venv/Scripts/fichero.exe ...` on
Windows.

## Setting up the printer

Turn the printer on and run:

```
fichero info
```

It scans Bluetooth LE for a device whose name starts with `FICHERO` or `D11s_`,
connects, and reports what it found:

```
Scanning for printer...
  Found FICHERO_5836_BLE at 22:99:17:BE:B0:21
  model: D11s
  firmware: 2.4.9
  battery: 100%
  status: ready
  shutdown: 20 min
```

Take the address from that output and put it in your environment. Later commands then
look for that one device instead of scanning by name:

```
export FICHERO_ADDR=22:99:17:BE:B0:21           # Linux, macOS, Git Bash
$env:FICHERO_ADDR = "22:99:17:BE:B0:21"         # Windows PowerShell
```

Put that line in your shell profile to make it stick. `--address` does the same for a
single command. Note this is the BLE address, not the `mac_classic` one that `info`
also prints.

The printer does not need to be paired in your operating system's Bluetooth settings,
and on Windows a pairing there can actually get in the way, because the OS holds the
connection and the device stops advertising.

### When the printer is not found

After a session closes the printer goes quiet for a few seconds, and now and then it
stays that way. If a command reports `No Fichero/D11s printer found` or
`Device with address ... was not found` while the printer is plainly switched on,
turn it off and on again and retry. The first connection after a power cycle takes
about five seconds; afterwards it is closer to two.

## A worked example: a strip of screw sizes

Four short lines on one 14x30mm label, reading across the label the way the web
designer lays them out:

```
fichero text --line "M3 x 20" --line "M3 x 18" --line "M3 x 12" --line "M3 x 8" \
    --font bahnschrift --font-size 23 --rotate 90
```

Add `--preview label.png` to that command to write the label to a file and skip the
printer entirely. Worth doing the first time, and whenever you change the font or the
number of lines.

Why these flags:

- `--rotate 90` turns the text a quarter turn, so each line runs across the 12mm
  height and the four lines stack down the 30mm length. Without it the lines would
  run along the length instead, and only about three would fit.
- `--font-size 23` keeps a line inside the 96px printhead: `M3 x 20` is 75px wide in
  Bahnschrift at that size, and all four lines together are 85px of the 240px length.
  The CLI warns if a block does not fit.
- `--font bahnschrift` is a narrow face, which buys a couple of characters per line
  over the default. Any installed font works; `fichero fonts` lists them.

## CLI Usage

```
fichero --help
```

### Printing

```
fichero text "Hello World"
fichero text "Fragile" --density 2 --copies 3
fichero text "Big Label" --font-size 40 --label-height 180
fichero image label.png
fichero image label.png --density 1 --copies 2
```

Density: 0=light, 1=medium (default), 2=thick.

Text labels accept `--font-size` (default 30) and `--label-length` in mm (default 30mm,
or `--label-height` in pixels).

### Fonts

By default text is rendered with Pillow's built-in font. `--font` takes a path to a
TrueType file, or the name of an installed font (the extension may be left off):

```
fichero text "Fragile" --font arialbd --font-size 34
fichero text "Serial 4711" --font consola
fichero text "Logo" --font /path/to/MyFont.ttf
fichero fonts          # list installed fonts you can name
```

`FICHERO_FONT` sets a default, so you don't have to pass `--font` every time.

### Multiple lines

Each `--line` adds a line:

```
fichero text --line "M3 x 20" --line "M3 x 18" --line "M3 x 12" --font-size 22
```

A literal `\n` in the positional text works too, for shells that make real newlines
awkward:

```
fichero text "Line one\nLine two"
```

`--align left|center|right` (default center) and `--line-spacing` (default 4px) control
the layout within the text block. The block itself is always centred on the label, in
both directions.

### Orientation

`--rotate` sets how the text sits on the label when you hold it the long way round, the
same way the web designer shows it:

- `0` (default) reads along the 30mm length. Lines stack across the 96px printhead, so
  about three fit at `--font-size 30`.
- `90` reads across the label, a quarter turn anticlockwise. Each line is limited to the
  96px printhead and the lines stack down the length, which is what you want for a stack
  of short lines:

```
fichero text --line "M3 x 20" --line "M3 x 18" --line "M3 x 12" --line "M3 x 8" \
    --font bahnschrift --font-size 23 --rotate 90
```

- `180` and `270` are those two upside down. Use them if a label comes out of the printer
  reading the wrong way for how you want to stick it on.

The CLI warns when the text block does not fit the label area. `FICHERO_ROTATE` sets a
default.

Note: the CLI used to turn the canvas anticlockwise on its way to the printer, while the
web client turns it clockwise (`ImageEncoder.rotateCW90`, `printDirection: "left"`), so
the two disagreed by 180 degrees. The CLI now follows the web client, and `--rotate`
angles mean the same thing in both.

### Previewing without printing

`--preview` renders the label to an image file and skips the printer entirely, which is
the quick way to tune font, size and line breaks:

```
fichero text --line "Kabel A12" --line "230V / 16A" --font consola --preview label.png
```

The preview is written in the printer's own orientation: 96px wide, and as many rows
tall as the label is long. Turn it a quarter turn anticlockwise to see it the way you
will hold the label.

### Device info

```
fichero info
fichero status
```

### Settings

```
fichero set density 2
fichero set shutdown 30
fichero set paper gap
```

- `density` - how dark the print is. 0 is faint, 1 is normal, 2 is the darkest. Higher density uses more battery and can smudge on some label stock.
- `shutdown` - how many minutes the printer waits before turning itself off when idle (1-480). Set it higher if you're tired of turning it back on between prints.
- `paper` - what kind of label stock you're using. `gap` is the default, for labels with spacing between them (the printer detects the gap to know where to stop). `black` is for rolls with a black mark between labels. `continuous` is for receipt-style rolls with no markings.

## Library Usage

```python
import asyncio
from fichero import connect, PrinterNotFound

async def main():
    async with connect() as pc:
        info = await pc.get_info()
        print(info)

asyncio.run(main())
```

The package exports `PrinterClient`, `connect`, `PrinterError`, `PrinterNotFound`, `PrinterTimeout`, `PrinterNotReady`, and `PrinterStatus`.

## TODO

- [ ] Emoji support in text labels. The default Pillow font has no emoji glyphs, so they render as squares. Needs two-pass rendering: split text into emoji/non-emoji segments, render emoji with Apple Color Emoji (macOS) or Noto Color Emoji (Linux) using `embedded_color=True`, then composite onto the label.

## Protocol and reverse engineering

See [docs/PROTOCOL.md](docs/PROTOCOL.md) for the full command reference, print sequence, and how this was reverse-engineered.

## License

MIT
