"""Tests for ending a print job, with and without the printer's answer."""

from unittest.mock import AsyncMock, patch

import pytest

from fichero.printer import PrinterClient, PrinterTimeout
from fichero.profiles import D1_4777

STATUS = bytes([0x10, 0xFF, 0x40])


def _client(replies):
    """A PrinterClient whose send() answers from *replies*, in order; None
    stands for no answer at all."""
    pc = PrinterClient(AsyncMock(), D1_4777)
    sent = []

    async def send(data, wait=False, timeout=2.0):
        sent.append(bytes(data))
        reply = replies.pop(0)
        if reply is None:
            raise PrinterTimeout("no answer")
        return reply

    pc.send = send
    return pc, sent


@pytest.mark.asyncio
async def test_answered_stop():
    pc, sent = _client([b"\xaa"])
    assert await pc.stop_print()
    assert sent == [D1_4777.stop_cmd]


@pytest.mark.asyncio
@patch("fichero.printer.asyncio.sleep", AsyncMock())
async def test_unanswered_stop_waits_for_printing_to_end():
    # D1-4777 over USB: no answer to stop, status says printing, then ready.
    pc, sent = _client([None, b"\x01", b"\x00"])
    assert await pc.stop_print()
    assert sent == [D1_4777.stop_cmd, STATUS, STATUS]


@pytest.mark.asyncio
@patch("fichero.printer.asyncio.sleep", AsyncMock())
async def test_late_answer_counts():
    pc, _ = _client([None, b"OK"])
    assert await pc.stop_print()


@pytest.mark.asyncio
@patch("fichero.printer.STOP_DONE_TIMEOUT", 0)
async def test_gives_up_eventually():
    pc, _ = _client([None])
    assert not await pc.stop_print()
