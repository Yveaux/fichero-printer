"""Tests for Markdown-style text formatting."""

import numpy as np

from fichero.imaging import text_to_image
from fichero.markup import HEADING_SCALE, Style, parse


def spans(text):
    (line,) = parse(text)
    return [(s.text, s.style) for s in line.spans]


B = Style(bold=True)
I = Style(italic=True)
U = Style(underline=True)
S = Style(strike=True)
N = Style()


class TestInline:
    def test_plain(self):
        assert spans("Hello World") == [("Hello World", N)]

    def test_each_marker(self):
        assert spans("a **b** c") == [("a ", N), ("b", B), (" c", N)]
        assert spans("*i*") == [("i", I)]
        assert spans("_i_") == [("i", I)]
        assert spans("__u__") == [("u", U)]
        assert spans("~~s~~") == [("s", S)]

    def test_bold_italic(self):
        assert spans("***x***") == [("x", Style(bold=True, italic=True))]

    def test_nested(self):
        assert spans("**a __b__**") == [("a ", B), ("b", Style(bold=True, underline=True))]

    def test_unclosed_marker_is_literal(self):
        assert spans("**open") == [("**open", N)]

    def test_lone_asterisk_between_spaces(self):
        assert spans("3 * 4 = 12") == [("3 * 4 = 12", N)]

    def test_underscore_inside_word(self):
        assert spans("my_file_name") == [("my_file_name", N)]

    def test_escape(self):
        assert spans(r"\*not italic\*") == [("*not italic*", N)]


class TestHeadings:
    def test_levels(self):
        for level, scale in HEADING_SCALE.items():
            (line,) = parse("#" * level + " Title")
            assert line.scale == scale
            assert [(s.text, s.style) for s in line.spans] == [("Title", B)]

    def test_needs_space(self):
        (line,) = parse("#1")
        assert line.scale == 1.0 and line.text == "#1"

    def test_escaped(self):
        (line,) = parse(r"\# not a heading")
        assert line.scale == 1.0 and line.text == "# not a heading"

    def test_stays_bold(self):
        (line,) = parse("# a **b** c")
        assert all(s.style.bold for s in line.spans)


def test_multiline():
    lines = parse("**a**\nb")
    assert [line.text for line in lines] == ["a", "b"]


def test_formatting_changes_ink():
    plain = text_to_image("Hello", rotate=90, printhead_px=384, label_height=120)
    bold = text_to_image("**Hello**", rotate=90, printhead_px=384, label_height=120)
    literal = text_to_image("**Hello**", rotate=90, printhead_px=384,
                            label_height=120, use_markup=False)
    ink = lambda im: im.histogram()[0]
    assert ink(bold) > ink(plain)
    assert ink(literal) > ink(plain)
    assert bold.tobytes() != literal.tobytes()


def test_blank_lines_push_text():
    kw = dict(rotate=90, printhead_px=384, label_height=200)
    ink_rows = lambda im: np.nonzero((np.array(im) == 0).any(axis=1))[0].tolist()
    centred = ink_rows(text_to_image("M8", **kw))
    pushed_up = ink_rows(text_to_image("M8\n\n\n", **kw))
    pushed_down = ink_rows(text_to_image("\n\n\nM8", **kw))
    assert pushed_up[0] < centred[0] < pushed_down[0]


def test_valign():
    kw = dict(printhead_px=384, label_height=200)
    for rotate in (0, 90, 180, 270):
        ink_rows = lambda im: np.nonzero((np.array(im.rotate(-((rotate + 270) % 360),
                                          expand=True)) == 0).any(axis=1))[0]
        top = ink_rows(text_to_image("M8", valign="top", rotate=rotate, **kw))
        mid = ink_rows(text_to_image("M8", rotate=rotate, **kw))
        bottom = ink_rows(text_to_image("M8", valign="bottom", rotate=rotate, **kw))
        assert top[0] == 0
        assert top[0] < mid[0] < bottom[0]
