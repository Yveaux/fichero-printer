"""Markdown-style inline formatting for text labels.

Supported, per line:

- ``**bold**``
- ``*italic*`` or ``_italic_``
- ``__underline__``
- ``~~strikethrough~~``
- ``# heading``, ``## heading``, ``### heading`` at the start of a line: a
  bold line in a larger size

Markers nest and combine (``***bold italic***``, ``**__bold underline__**``).
A backslash makes the next character literal (``\\*`` prints an asterisk).
A marker that is never closed is printed as-is, and ``_`` inside a word
(``file_name``) is left alone, so ordinary text rarely needs escaping.
"""

import re
from dataclasses import dataclass, replace

# Font size multiplier per heading level.
HEADING_SCALE = {1: 1.6, 2: 1.3, 3: 1.15}

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_ESCAPABLE = set("\\*_~#")

# Longest first, so "**" is not read as two "*".
_MARKERS = ("**", "__", "~~", "*", "_")
_MARKER_STYLE = {"**": "bold", "__": "underline", "~~": "strike",
                 "*": "italic", "_": "italic"}


@dataclass(frozen=True)
class Style:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False


@dataclass
class Span:
    text: str
    style: Style


@dataclass
class Line:
    spans: list[Span]
    scale: float = 1.0

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)


def parse(text: str) -> list[Line]:
    """Split *text* into lines of styled spans."""
    return [_parse_line(line) for line in text.split("\n")]


def plain(text: str) -> list[Line]:
    """The same structure as parse(), with every character taken literally."""
    return [Line([Span(line, Style())]) for line in text.split("\n")]


def _parse_line(line: str) -> Line:
    scale = 1.0
    base = Style()
    m = _HEADING_RE.match(line)
    if m:
        scale = HEADING_SCALE[len(m.group(1))]
        base = Style(bold=True)
        line = m.group(2)
    return Line(_parse_inline(line, base), scale)


def _parse_inline(line: str, base: Style) -> list[Span]:
    # Tokens are ("text", str) or ("marker", str, can_open, can_close).
    tokens = []
    i = 0
    buf = []
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] in _ESCAPABLE:
            buf.append(line[i + 1])
            i += 2
            continue
        marker = next((mk for mk in _MARKERS if line.startswith(mk, i)), None)
        if marker:
            before = line[i - 1] if i > 0 else " "
            after = line[i + len(marker)] if i + len(marker) < len(line) else " "
            can_open, can_close = _flanking(marker, before, after)
            if can_open or can_close:
                if buf:
                    tokens.append(("text", "".join(buf)))
                    buf = []
                tokens.append(("marker", marker, can_open, can_close))
                i += len(marker)
                continue
        buf.append(ch)
        i += 1
    if buf:
        tokens.append(("text", "".join(buf)))

    # Pair openers with closers; anything left unpaired is literal text.
    paired = set()
    open_stack: list[int] = []
    for idx, tok in enumerate(tokens):
        if tok[0] != "marker":
            continue
        _, marker, can_open, can_close = tok
        if can_close:
            match = next((j for j in reversed(open_stack) if tokens[j][1] == marker), None)
            if match is not None:
                open_stack.remove(match)
                paired.update((match, idx))
                continue
        if can_open:
            open_stack.append(idx)

    spans: list[Span] = []
    style = base
    for idx, tok in enumerate(tokens):
        if tok[0] == "marker" and idx in paired:
            attr = _MARKER_STYLE[tok[1]]
            style = replace(style, **{attr: not getattr(style, attr)})
            # A heading stays bold however its own ** markers toggle.
            if base.bold and attr == "bold":
                style = replace(style, bold=True)
            continue
        text = tok[1]
        if spans and spans[-1].style == style:
            spans[-1].text += text
        else:
            spans.append(Span(text, style))
    return spans or [Span("", base)]


def _flanking(marker: str, before: str, after: str) -> tuple[bool, bool]:
    """Whether a marker between *before* and *after* may open or close a span.

    Like Markdown: an opener must be followed by non-space, a closer preceded
    by it, and an underscore marker must not sit inside a word.
    """
    can_open = not after.isspace()
    can_close = not before.isspace()
    if marker.startswith("_"):
        can_open = can_open and not before.isalnum()
        can_close = can_close and not after.isalnum()
    return can_open, can_close
