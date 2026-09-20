"""Per-model printer profiles.

The protocol is shared across a family of white-label thermal printers, but the
details differ per model: how wide the printhead is, which enable/stop commands
the device class answers to, whether it knows about paper types, and how it gets
the finished label out to the tear edge. Sending the wrong enable command is the
nastiest of these, because the printer accepts the raster, feeds the paper and
prints nothing at all.

A profile collects those differences. `profile_for_model()` picks one from the
string `10 FF 20 F0` returns, so a supported printer needs no configuration.

Adding a model means adding a `PrinterProfile` to `PROFILES` below. Work out its
values with a calibration print: a full-width ruler shows the printhead size, and
a wrong device class shows up as a blank label.
"""

from dataclasses import dataclass, field

DOTS_PER_MM = 8  # 203 DPI

# Device classes, from the decompiled LuckPrinter SDK. The enable/stop pair has
# to match the class or the printer silently refuses to heat.
AIYIN_ENABLE = bytes([0x10, 0xFF, 0xFE, 0x01])
AIYIN_STOP = bytes([0x10, 0xFF, 0xFE, 0x45])
LUJIANG_ENABLE = bytes([0x10, 0xFF, 0xF1, 0x03])
LUJIANG_STOP = bytes([0x10, 0xFF, 0xF1, 0x45])


@dataclass(frozen=True)
class PrinterProfile:
    """Everything that differs between models of this printer family."""

    name: str
    """Short name for --printer and for messages."""

    models: tuple[str, ...] = ()
    """Model strings this profile claims, matched case-insensitively against
    the reply to `10 FF 20 F0`. A trailing `*` matches as a prefix."""

    ble_name_prefixes: tuple[str, ...] = ()
    """Bluetooth names this model advertises under, as prefixes. A scan looks
    for every profile's prefixes, so a new model is only discoverable once its
    own are listed here."""

    description: str = ""

    printhead_px: int = 96
    """Printable width in dots. The raster is always this wide."""

    enable_cmd: bytes = AIYIN_ENABLE
    stop_cmd: bytes = AIYIN_STOP

    supports_paper_type: bool = True
    """False when `10 FF 84` goes unanswered, as on the D1-4777."""

    feed_dots: int | None = None
    """Dots to advance after printing, to bring the label to the tear edge.
    None uses the `1D 0C` form feed instead, which advances to the next gap."""

    default_label_mm: int = 30
    """Label length along the feed direction."""

    default_rotate: int = 0
    """Text orientation that reads naturally on this printer's labels. On a
    printer whose head spans the short side of the label, text runs along the
    feed direction (0). On one whose head spans the long side, the lines run
    across the head and stack down the feed instead (90)."""

    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def bytes_per_row(self) -> int:
        return self.printhead_px // 8

    @property
    def printhead_mm(self) -> float:
        return self.printhead_px / DOTS_PER_MM

    @property
    def default_label_px(self) -> int:
        return self.default_label_mm * DOTS_PER_MM

    def matches(self, model: str) -> bool:
        model = model.strip().lower()
        for candidate in self.models:
            candidate = candidate.lower()
            if candidate.endswith("*"):
                if model.startswith(candidate[:-1]):
                    return True
            elif model == candidate:
                return True
        return False


D11S = PrinterProfile(
    name="d11s",
    models=("D11s", "D12*"),
    ble_name_prefixes=("FICHERO", "D11s_"),
    description="Fichero / AiYin D11s, 14x30mm labels",
    printhead_px=96,
    enable_cmd=AIYIN_ENABLE,
    stop_cmd=AIYIN_STOP,
    supports_paper_type=True,
    feed_dots=None,
    default_label_mm=30,
    default_rotate=0,
    aliases=("fichero",),
)

D1_4777 = PrinterProfile(
    name="d1-4777",
    models=("D1-4777",),
    ble_name_prefixes=("CRAFTS&CO", "D1-4777"),
    description="Crafts&Co 4777, 50x15mm labels",
    printhead_px=384,
    enable_cmd=LUJIANG_ENABLE,
    stop_cmd=LUJIANG_STOP,
    supports_paper_type=False,
    # This model does not support paper types and never seeks the gap itself,
    # so raster rows plus this feed have to add up to the label pitch exactly,
    # or every label prints a little further along the roll than the last.
    # 15mm label + 7.9mm gap = 183 dots, minus 120 raster rows.
    feed_dots=63,
    default_label_mm=15,
    default_rotate=90,
    aliases=("craftsco", "crafts&co"),
)

PROFILES: tuple[PrinterProfile, ...] = (D11S, D1_4777)

DEFAULT_PROFILE = D11S
"""Used when the model is unknown, and for offline work such as --preview."""


def profile_for_model(model: str) -> PrinterProfile | None:
    """Return the profile claiming *model*, or None if no profile does."""
    for profile in PROFILES:
        if profile.matches(model):
            return profile
    return None


def profile_by_name(name: str) -> PrinterProfile:
    """Look up a profile by its name or one of its aliases."""
    wanted = name.strip().lower()
    for profile in PROFILES:
        if wanted == profile.name or wanted in profile.aliases:
            return profile
    known = ", ".join(p.name for p in PROFILES)
    raise ValueError(f"Unknown printer profile {name!r}. Known profiles: {known}")


def profile_names() -> list[str]:
    return [p.name for p in PROFILES]


def all_name_prefixes() -> tuple[str, ...]:
    """Every Bluetooth name prefix any profile advertises under."""
    seen: list[str] = []
    for profile in PROFILES:
        for prefix in profile.ble_name_prefixes:
            if prefix not in seen:
                seen.append(prefix)
    return tuple(seen)
