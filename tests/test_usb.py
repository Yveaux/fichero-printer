"""Tests for the USB transport's device selection (no hardware needed)."""

from unittest.mock import patch

import pytest

from fichero import usb
from fichero.printer import PrinterNotFound, _pick_usb_printer
from fichero.profiles import D1_4777, D11S

D11S_PATH = r"\\?\usb#vid_09c5&pid_0200#1157f1a64006#{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"
OTHER_PATH = r"\\?\usb#vid_04f9&pid_0390#000000#{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"


def _find(paths):
    with patch("fichero.usb.sys.platform", "win32"), \
         patch.object(usb._win, "interface_paths", return_value=paths):
        return usb.find_usb_printers()


def test_finds_only_printers_a_profile_claims():
    found = _find([OTHER_PATH, D11S_PATH])
    assert [(p.path, p.profile) for p in found] == [(D11S_PATH, D11S)]


def test_unknown_printers_are_never_returned():
    assert _find([OTHER_PATH]) == []


def test_nothing_off_windows():
    with patch("fichero.usb.sys.platform", "linux"):
        assert usb.find_usb_printers() == []


PRINTER = usb.USBPrinter(D11S_PATH, 0x09C5, 0x0200, D11S)


def test_pick_any_supported():
    with patch("fichero.printer.find_usb_printers", return_value=[PRINTER]):
        assert _pick_usb_printer(None, required=False) is PRINTER


def test_pick_respects_forced_profile():
    with patch("fichero.printer.find_usb_printers", return_value=[PRINTER]):
        assert _pick_usb_printer(D1_4777, required=False) is None
        with pytest.raises(PrinterNotFound, match="d1-4777"):
            _pick_usb_printer(D1_4777, required=True)


def test_pick_none_plugged_in():
    with patch("fichero.printer.find_usb_printers", return_value=[]):
        assert _pick_usb_printer(None, required=False) is None
        with pytest.raises(PrinterNotFound, match="USB"):
            _pick_usb_printer(None, required=True)
