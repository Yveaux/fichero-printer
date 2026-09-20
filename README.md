# fichero-printer

Web GUI, Python CLI, and protocol documentation for the Fichero D11s thermal label printer.

Blog post: [Reverse Engineering Action's Cheap Fichero Labelprinter](https://blog.dbuglife.com/reverse-engineering-fichero-label-printer/)

The [Fichero](https://www.action.com/nl-nl/p/3212141/fichero-labelprinter/) is a cheap Bluetooth thermal label printer sold at Action. Internally it's an AiYin D11s made by Xiamen Print Future Technology. The official app is closed-source and doesn't expose the protocol, so this project reverse-engineers it from the decompiled APK.

## Supported printers

The protocol is shared across a family of white-label thermal printers, but the
details differ per model. Each supported model has a profile, and the CLI picks
the right one from the model string the printer reports, so normally you do not
have to say which printer you have.

| Profile | Printer | Printhead | Labels | Notes |
|---|---|---|---|---|
| `d11s` | Fichero (Action), AiYin D11s | 96px / 12mm | 14x30mm | Head spans the short side |
| `d1-4777` | Crafts&Co 4777 | 384px / 48mm | 50x15mm | Head spans the long side |

```
fichero profiles          # what each profile does
```

`--printer NAME` forces one, which is how you drive a model that is not in the
list yet, and how `--preview` knows what to render for. See
[Adding a printer](#adding-a-printer) to teach the package a new model.

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

It scans Bluetooth LE for the names the known profiles advertise under - `FICHERO`,
`D11s_`, `CRAFTS&CO`, `D1-4777` - connects to the first one that answers, and reports
what it found.

A Fichero D11s:

```
Scanning for printer...
  Found FICHERO_5836_BLE at 22:99:17:BE:B0:21
  model: D11s
  firmware: 2.4.9
  battery: 100%
  status: ready
  shutdown: 20 min
```

A Crafts&Co 4777:

```
Scanning for printer...
  Found CRAFTS&CO|4777_BLE at 5E:55:09:10:A9:5C
  model: D1-4777
  firmware: V1.08
  battery: 94%
  status: ready
  shutdown: -1 min
```

`shutdown: -1` on the 4777 is not an error; that model does not implement the
auto-off setting.

Take the address from that output and put it in your environment. Later commands then
look for that one device instead of scanning by name:

```
export FICHERO_ADDR=22:99:17:BE:B0:21           # Linux, macOS, Git Bash
$env:FICHERO_ADDR = "22:99:17:BE:B0:21"         # Windows PowerShell
```

Put that line in your shell profile to make it stick. `--address` does the same for a
single command. Note this is the BLE address, not the `mac_classic` one that `info`
also prints.

### Two printers at once

With more than one printer switched on, a plain scan takes whichever advertises first.
`--printer` narrows the scan to one profile's names, so you get the one you meant
without looking up addresses:

```
fichero --printer d1-4777 info
fichero --printer d11s text "Hello"
```

An address still wins over both, and is worth setting when you mostly use one printer.

The printer does not need to be paired in your operating system's Bluetooth settings,
and on Windows a pairing there can actually get in the way, because the OS holds the
connection and the device stops advertising.

### When the printer is not found

After a session closes the printer goes quiet for a few seconds, and now and then it
stays that way. If a command reports `No supported printer found` or
`Device with address ... was not found` while the printer is plainly switched on,
turn it off and on again and retry. Give it a moment: a freshly powered-on printer
can take the better part of ten seconds to start advertising, and the first connection
after that runs to about five seconds. Once it is awake, finding it takes well under
a second.

## Worked examples

Both examples print a strip of screw sizes. They differ because the two printers
hold their labels the other way round, which is exactly what the profiles absorb.

### Fichero D11s, 14x30mm

Four short lines, reading across the label the way the web designer lays them out:

```
fichero text --line "M3 x 20" --line "M3 x 18" --line "M3 x 12" --line "M3 x 8" \
    --font bahnschrift --font-size 23 --rotate 90
```

This head spans the 12mm side, so text normally runs along the 30mm length and
`--rotate 90` is what turns it a quarter turn. `--font-size 23` keeps a line inside
the 96px head: `M3 x 20` is 75px wide in Bahnschrift, and the four lines together
are 85px of the 240px length.

### Crafts&Co 4777, 50x15mm

```
fichero text --line "M3 x 20" --line "M3 x 18" --font bahnschrift --font-size 30
```

No `--rotate` here. This head spans the 48mm side, so ordinary horizontal lines
already read the right way and the profile makes that the default. There is room
for roughly 48mm of text per line, and about three lines at this size within the
15mm feed.

### Either printer

Add `--preview label.png` to skip the printer and write the rendered label to a
file. Worth doing the first time and whenever you change the font or the number of
lines. Offline there is no printer to ask, so pair it with `--printer`:

```
fichero --printer d1-4777 text --line "M3 x 20" --line "M3 x 18" --preview label.png
```

`--font bahnschrift` is a narrow face, which buys a couple of characters per line
over the default. Any installed font works; `fichero fonts` lists them. The CLI
warns when a text block does not fit the label.

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
same way the web designer shows it. Each profile has its own default, whichever reads
naturally on that printer's labels: `0` on the D11s, `90` on the D1-4777.

- `0` reads along the feed direction. Lines stack across the printhead.
- `90` reads across the label, a quarter turn anticlockwise. Each line is limited to the
  printhead width and the lines stack down the label, which is what you want for a stack
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

## Adding a printer

A profile is a dataclass in [fichero/profiles.py](fichero/profiles.py); adding a
model means adding an entry to `PROFILES`. The fields that matter:

| Field | How to find it |
|---|---|
| `models` | What `fichero info` prints as `model`. A trailing `*` matches as a prefix |
| `printhead_px` | Print a full-width ruler and read where it stops. Too wide and the printer rejects the whole raster |
| `enable_cmd` / `stop_cmd` | `AIYIN_*` or `LUJIANG_*`. Wrong pair = the label feeds blank |
| `supports_paper_type` | False when `10 FF 84` goes unanswered |
| `feed_dots` | `None` uses the `1D 0C` form feed. A number feeds that many dots, for labels whose raster fills the whole label |
| `default_label_mm` | The label length along the feed direction |
| `default_rotate` | `0` when the head spans the short side of the label, `90` when it spans the long side |

Until a profile exists, drive the printer with `--printer` on whichever existing
profile is closest and override the rest from the command line.

The blank-label case is worth knowing in advance: with the wrong device class the
printer accepts the raster, feeds the paper and never heats the head. It looks like
a hardware fault and is not one.

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

The package exports `PrinterClient`, `connect`, `PrinterError`, `PrinterNotFound`, `PrinterTimeout`, `PrinterNotReady`, `PrinterStatus`, `PrinterProfile` and `profile_by_name`.

`connect()` detects the profile and leaves it on the client, so `pc.profile` tells
you the printhead width to render for. Pass `profile=` to force one:

```python
from fichero import connect, profile_by_name

async with connect(profile=profile_by_name("d1-4777")) as pc:
    print(pc.profile.printhead_px, pc.profile_detected)
```

## TODO

- [ ] Emoji support in text labels. The default Pillow font has no emoji glyphs, so they render as squares. Needs two-pass rendering: split text into emoji/non-emoji segments, render emoji with Apple Color Emoji (macOS) or Noto Color Emoji (Linux) using `embedded_color=True`, then composite onto the label.

## Protocol and reverse engineering

See [docs/PROTOCOL.md](docs/PROTOCOL.md) for the full command reference, print sequence, and how this was reverse-engineered.

## License

MIT
