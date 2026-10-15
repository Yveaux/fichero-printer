"""USB transport, through the printer-class driver Windows binds to the printer.

A D11s plugged in over USB-C shows up as a USB printer, and Windows' own
usbprint driver passes raw bytes both ways: commands go out with WriteFile and
the printer's answers come back with ReadFile, just as over Bluetooth but with
no scanning, pairing or connection to stall. Only devices whose USB vendor and
product ids a profile lists are opened, so no other printer ever receives
these bytes.

Windows only for now; elsewhere find_usb_printers() returns nothing.
"""

import asyncio
import ctypes
import logging
import re
import sys
import threading
import uuid
from dataclasses import dataclass

from fichero.profiles import PROFILES, PrinterProfile

log = logging.getLogger(__name__)

READ_POLL_MS = 200     # how long one read waits before checking for shutdown
WRITE_TIMEOUT_MS = 10_000


@dataclass(frozen=True)
class USBPrinter:
    path: str
    """Windows device interface path, opened with CreateFile."""
    vid: int
    pid: int
    profile: PrinterProfile

    def __str__(self) -> str:
        return f"{self.profile.name} on USB ({self.vid:04X}:{self.pid:04X})"


def _profile_for_ids(vid: int, pid: int) -> PrinterProfile | None:
    for profile in PROFILES:
        if (vid, pid) in profile.usb_ids:
            return profile
    return None


def find_usb_printers() -> list[USBPrinter]:
    """Supported printers plugged in over USB, those a profile claims by id."""
    if sys.platform != "win32":
        return []
    found = []
    for path in _win.interface_paths():
        m = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", path, re.IGNORECASE)
        if not m:
            continue
        vid, pid = int(m.group(1), 16), int(m.group(2), 16)
        profile = _profile_for_ids(vid, pid)
        if profile is not None:
            found.append(USBPrinter(path, vid, pid, profile))
    return found


class USBClient:
    """USB transport with the async context manager and write_gatt_char /
    start_notify interface PrinterClient expects from BleakClient."""

    is_classic = True  # a byte stream: big chunks, no BLE pacing

    def __init__(self, printer: USBPrinter):
        self.printer = printer
        self._handle = None
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None

    async def __aenter__(self) -> "USBClient":
        from fichero.printer import PrinterError

        try:
            self._handle = _win.open(self.printer.path)
        except OSError as e:
            raise PrinterError(f"Could not open {self.printer}: {e}") from e
        return self

    async def __aexit__(self, *exc) -> None:
        self._stop.set()
        if self._reader is not None:
            await asyncio.to_thread(self._reader.join, 2.0)
            self._reader = None
        if self._handle is not None:
            _win.close(self._handle)
            self._handle = None

    async def write_gatt_char(self, _uuid: str, data: bytes, response: bool = False) -> None:
        from fichero.printer import PrinterError

        try:
            await asyncio.to_thread(_win.write, self._handle, bytes(data), WRITE_TIMEOUT_MS)
        except OSError as e:
            raise PrinterError(f"USB write failed: {e}") from e

    async def start_notify(self, _uuid: str, callback) -> None:
        loop = asyncio.get_running_loop()

        def reader() -> None:
            while not self._stop.is_set():
                try:
                    data = _win.read(self._handle, 512, READ_POLL_MS)
                except OSError as e:
                    log.debug("USB read stopped: %s", e)
                    return
                if data:
                    loop.call_soon_threadsafe(callback, None, bytearray(data))

        self._reader = threading.Thread(target=reader, name="fichero-usb-reader", daemon=True)
        self._reader.start()


class _Win32:
    """The handful of SetupAPI and overlapped file calls the transport needs."""

    # GUID_DEVINTERFACE_USBPRINT: the interface usbprint exposes per printer.
    USBPRINT = "28d78fad-5a12-11d1-ae5b-0000f803a8c2"
    ERROR_IO_PENDING = 997
    WAIT_OBJECT_0 = 0

    def __init__(self):
        self._ready = False

    def _load(self) -> None:
        if self._ready:
            return
        import ctypes.wintypes as wt

        self.wt = wt

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        class InterfaceData(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID),
                        ("Flags", wt.DWORD), ("Reserved", ctypes.c_void_p)]

        class Overlapped(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                        ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD), ("hEvent", wt.HANDLE)]

        self.GUID, self.InterfaceData, self.Overlapped = GUID, InterfaceData, Overlapped

        sa = self.setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
        sa.SetupDiGetClassDevsW.restype = wt.HANDLE
        sa.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
        sa.SetupDiEnumDeviceInterfaces.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID),
                                                   wt.DWORD, ctypes.POINTER(InterfaceData)]
        sa.SetupDiGetDeviceInterfaceDetailW.argtypes = [wt.HANDLE, ctypes.POINTER(InterfaceData),
                                                        ctypes.c_void_p, wt.DWORD,
                                                        ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
        sa.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]

        k = self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = wt.HANDLE
        k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                  wt.DWORD, wt.HANDLE]
        k.CreateEventW.restype = wt.HANDLE
        k.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        k.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        k.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        k.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(wt.DWORD), wt.BOOL]
        k.CancelIoEx.argtypes = [wt.HANDLE, ctypes.c_void_p]
        k.CloseHandle.argtypes = [wt.HANDLE]
        self._ready = True

    def _guid(self, text: str):
        g = self.GUID()
        ctypes.memmove(ctypes.byref(g), uuid.UUID(text).bytes_le, 16)
        return g

    def interface_paths(self) -> list[str]:
        self._load()
        guid = self._guid(self.USBPRINT)
        DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x2, 0x10
        devs = self.setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                                  DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
        if devs in (None, ctypes.c_void_p(-1).value):
            return []
        paths = []
        try:
            index = 0
            while True:
                data = self.InterfaceData()
                data.cbSize = ctypes.sizeof(data)
                if not self.setupapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(guid),
                                                                 index, ctypes.byref(data)):
                    break
                index += 1
                need = self.wt.DWORD()
                self.setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(data), None, 0,
                                                              ctypes.byref(need), None)
                detail = ctypes.create_string_buffer(need.value)
                # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W: the fixed part only.
                ctypes.cast(detail, ctypes.POINTER(self.wt.DWORD))[0] = (
                    8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6)
                if self.setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(data), detail,
                                                                 need, None, None):
                    paths.append(ctypes.wstring_at(ctypes.addressof(detail) + 4))
        finally:
            self.setupapi.SetupDiDestroyDeviceInfoList(devs)
        return paths

    def open(self, path: str):
        self._load()
        GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
        SHARE_READ_WRITE, OPEN_EXISTING, FILE_FLAG_OVERLAPPED = 0x3, 3, 0x40000000
        handle = self.kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, SHARE_READ_WRITE,
                                           None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def close(self, handle) -> None:
        self.kernel32.CloseHandle(handle)

    def _io(self, fn, handle, buf, size: int, timeout_ms: int) -> int | None:
        """Run one overlapped read or write; None when it timed out."""
        k = self.kernel32
        ov = self.Overlapped()
        ov.hEvent = k.CreateEventW(None, True, False, None)
        done = self.wt.DWORD()
        try:
            if not fn(handle, buf, size, None, ctypes.byref(ov)):
                err = ctypes.get_last_error()
                if err != self.ERROR_IO_PENDING:
                    raise ctypes.WinError(err)
            if k.WaitForSingleObject(ov.hEvent, timeout_ms) != self.WAIT_OBJECT_0:
                k.CancelIoEx(handle, ctypes.byref(ov))
                k.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(done), True)
                return None
            if not k.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(done), False):
                raise ctypes.WinError(ctypes.get_last_error())
            return done.value
        finally:
            k.CloseHandle(ov.hEvent)

    def write(self, handle, data: bytes, timeout_ms: int) -> None:
        written = self._io(self.kernel32.WriteFile, handle, data, len(data), timeout_ms)
        if written is None:
            raise TimeoutError(f"no room for {len(data)} bytes within {timeout_ms}ms")
        if written != len(data):
            raise OSError(f"wrote {written} of {len(data)} bytes")

    def read(self, handle, size: int, timeout_ms: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        got = self._io(self.kernel32.ReadFile, handle, buf, size, timeout_ms)
        return buf.raw[:got] if got else b""


_win = _Win32()
