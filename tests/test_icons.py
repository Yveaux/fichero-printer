"""Tests for :name: icons in text labels."""

import io
import os
from unittest.mock import patch

import numpy as np
import pytest

from fichero import icons
from fichero.markup import parse


def spans(text):
    (line,) = parse(text)
    return [(s.text, s.icon) for s in line.spans]


class TestParse:
    def test_icon(self):
        assert spans(":bolt: 230V") == [("bolt", True), (" 230V", False)]

    def test_adjacent_icons(self):
        assert spans(":bolt::home:") == [("bolt", True), ("home", True)]

    def test_times_and_words_stay_text(self):
        assert spans("12:30") == [("12:30", False)]
        assert spans("a:b:c") == [("a:b:c", False)]
        assert spans("x :Bolt: y") == [("x :Bolt: y", False)]

    def test_escaped(self):
        assert spans(r"\:bolt:") == [(":bolt:", False)]

    def test_takes_style(self):
        (line,) = parse("**:warning: hot**")
        assert line.spans[0].icon and line.spans[0].style.bold


FAKE_CODEPOINTS = {"bolt": 0xEA0B, "build": 0xE869, "home": 0xE88A}


class TestLookup:
    def test_char(self):
        with patch("fichero.icons.codepoints", return_value=FAKE_CODEPOINTS):
            assert icons.char("bolt") == ""

    def test_unknown_suggests(self):
        with patch("fichero.icons.codepoints", return_value=FAKE_CODEPOINTS):
            with pytest.raises(icons.IconError, match=":bolt:"):
                icons.char("bolts")

    def test_search(self):
        with patch("fichero.icons.codepoints", return_value=FAKE_CODEPOINTS):
            assert icons.search("o") == ["bolt", "home"]
            assert icons.search(None) == ["bolt", "build", "home"]


class TestDownload:
    def test_downloads_once(self, tmp_path):
        with patch.dict(os.environ, {"FICHERO_CACHE": str(tmp_path)}), \
             patch("fichero.icons.urllib.request.urlopen",
                   return_value=io.BytesIO(b"bolt ea0b\n")) as urlopen:
            path = icons._fetch(icons.CODEPOINTS_FILE)
            assert open(path, "rb").read() == b"bolt ea0b\n"
            assert icons._fetch(icons.CODEPOINTS_FILE) == path
        urlopen.assert_called_once()
        assert os.listdir(tmp_path) == [icons.CODEPOINTS_FILE]

    def test_failed_download_leaves_nothing(self, tmp_path):
        with patch.dict(os.environ, {"FICHERO_CACHE": str(tmp_path)}), \
             patch("fichero.icons.urllib.request.urlopen", side_effect=OSError("offline")):
            with pytest.raises(icons.IconError, match="offline"):
                icons._fetch(icons.FONT_FILE)
        assert os.listdir(tmp_path) == []


@pytest.mark.skipif(
    not os.path.exists(os.path.join(icons.cache_dir(), icons.FONT_FILE)),
    reason="icon font not downloaded; run 'fichero icons' once",
)
def test_icon_renders_ink():
    from fichero.imaging import text_to_image

    kw = dict(rotate=90, printhead_px=384, label_height=120)
    ink = lambda im: int((np.array(im) == 0).sum())
    assert ink(text_to_image("A :bolt:", **kw)) > ink(text_to_image("A", **kw))
