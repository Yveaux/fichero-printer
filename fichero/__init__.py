"""Fichero D11s thermal label printer - BLE + Classic Bluetooth interface."""

from fichero.printer import (
    RFCOMM_CHANNEL,
    PrinterClient,
    PrinterError,
    PrinterNotFound,
    PrinterNotReady,
    PrinterStatus,
    PrinterTimeout,
    RFCOMMClient,
    connect,
)
from fichero.profiles import (
    PROFILES,
    PrinterProfile,
    profile_by_name,
    profile_for_model,
)

__all__ = [
    "PROFILES",
    "PrinterProfile",
    "profile_by_name",
    "profile_for_model",
    "RFCOMM_CHANNEL",
    "PrinterClient",
    "PrinterError",
    "PrinterNotFound",
    "PrinterNotReady",
    "PrinterStatus",
    "PrinterTimeout",
    "RFCOMMClient",
    "connect",
]
