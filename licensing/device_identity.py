# licensing/device_identity.py
"""Hardware identity acquisition and node-locking fingerprinting (fp_v1).

Binds licenses strictly to motherboard/SMBIOS identity.
Resilient to Windows reinstallation, RAM upgrades, SSD/HDD swaps, and network changes.
"""

import abc
import hashlib
import os
import re
import subprocess
import sys
import unicodedata
from typing import Optional, Tuple
from .license_models import HardwareIdentityUnavailableError

# Strict placeholder and invalid value lists
INVALID_UUID_PATTERNS = {
    "",
    "00000000-0000-0000-0000-000000000000",
    "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "03000200-0400-0500-0006-000700080009",  # Common default AMI placeholder
}

INVALID_SERIAL_KEYWORDS = {
    "",
    "none",
    "n/a",
    "na",
    "not applicable",
    "not specified",
    "default string",
    "to be filled by o.e.m.",
    "system serial number",
    "chassis serial number",
    "base board serial number",
    "oem",
    "invalid",
    "unknown",
    "0",
    "00000000",
    "123456789",
}

UUID_REGEX = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _clean_string(value: Optional[str]) -> str:
    """Trim, NFC-normalize, and collapse whitespace."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFC", str(value)).strip()
    return " ".join(normalized.split())


def is_valid_uuid(uuid_str: Optional[str]) -> bool:
    """Check if UUID string is valid and not an OEM placeholder."""
    cleaned = _clean_string(uuid_str).lower()
    if not cleaned or cleaned in INVALID_UUID_PATTERNS:
        return False
    if not UUID_REGEX.match(cleaned):
        return False
    # Reject repeated characters like 11111111-1111-...
    stripped = cleaned.replace("-", "")
    if len(set(stripped)) <= 1:
        return False
    return True


def is_valid_board_serial(serial_str: Optional[str]) -> bool:
    """Check if Motherboard Serial is valid and not an OEM placeholder."""
    cleaned = _clean_string(serial_str).lower()
    if not cleaned or cleaned in INVALID_SERIAL_KEYWORDS:
        return False
    # Reject single-character repetitions like 'XXXXXXX' or '........'
    cleaned_no_punct = re.sub(r"[\s\-_./]", "", cleaned)
    if len(cleaned_no_punct) < 3 or len(set(cleaned_no_punct)) <= 1:
        return False
    return True


def is_valid_model_info(mfg: Optional[str], prod: Optional[str]) -> bool:
    """Check if motherboard manufacturer and product strings are meaningful."""
    c_mfg = _clean_string(mfg).lower()
    c_prod = _clean_string(prod).lower()
    if not c_mfg or not c_prod:
        return False
    if c_mfg in INVALID_SERIAL_KEYWORDS or c_prod in INVALID_SERIAL_KEYWORDS:
        return False
    return True


def compute_hardware_fingerprint_from_components(
    uuid: Optional[str],
    serial: Optional[str],
    mfg: Optional[str] = None,
    prod: Optional[str] = None,
) -> Tuple[str, str]:
    """Compute fp_v1 fingerprint and return (fingerprint, tier_id).

    Tiers:
    - Tier 1: Valid UUID + Valid Board Serial
    - Tier 2: Valid UUID + Valid Board Model (Mfg:Prod)
    - Tier 3: Valid Board Serial + Valid Board Model (Mfg:Prod)
    - Hard Fail: raises HardwareIdentityUnavailableError
    """
    clean_uuid = _clean_string(uuid)
    clean_serial = _clean_string(serial)
    clean_mfg = _clean_string(mfg)
    clean_prod = _clean_string(prod)

    uuid_ok = is_valid_uuid(clean_uuid)
    serial_ok = is_valid_board_serial(clean_serial)
    model_ok = is_valid_model_info(clean_mfg, clean_prod)

    canonical_str = ""
    tier = ""

    if uuid_ok and serial_ok:
        tier = "tier1"
        canonical_str = f"v1|uuid={clean_uuid}|board={clean_serial}"
    elif uuid_ok and model_ok:
        tier = "tier2"
        canonical_str = f"v1|uuid={clean_uuid}|board_model={clean_mfg}:{clean_prod}"
    elif serial_ok and model_ok:
        tier = "tier3"
        canonical_str = f"v1|board={clean_serial}|board_model={clean_mfg}:{clean_prod}"
    else:
        raise HardwareIdentityUnavailableError(
            "شناسه سخت‌افزاری پایدار مادربورد/بایوس قابل دریافت نیست یا با مقادیر غیراختصاصی شرکت سازنده پر شده است."
        )

    # Normalize canonical string: NFC, trimmed, uppercase ASCII
    norm = unicodedata.normalize("NFC", canonical_str).strip()
    norm = " ".join(norm.split())
    norm = norm.upper()

    digest = hashlib.sha256(f"DAQIQ-HWFP-V1|{norm}".encode("utf-8")).hexdigest().lower()
    return f"fp_v1:{digest}", tier


class HardwareIdentitySource(abc.ABC):
    """Abstract interface for hardware fingerprint providers."""

    @abc.abstractmethod
    def get_fingerprint(self) -> str:
        """Return the calculated fp_v1:<64-hex> fingerprint."""
        pass


class WindowsHardwareProvider(HardwareIdentitySource):
    """Acquires SMBIOS hardware identity via Windows CIM/WMI with hard timeouts."""

    def __init__(self, timeout_sec: float = 5.0):
        self.timeout_sec = timeout_sec

    def _query_wmi(self) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Query Win32_ComputerSystemProduct and Win32_BaseBoard via PowerShell CIM."""
        script = (
            "$u = (Get-CimInstance Win32_ComputerSystemProduct | Select-Object -ExpandProperty UUID) 2>$null; "
            "$b = (Get-CimInstance Win32_BaseBoard | Select-Object SerialNumber, Manufacturer, Product) 2>$null; "
            "Write-Output \"UUID=$u\"; "
            "Write-Output \"SERIAL=$($b.SerialNumber)\"; "
            "Write-Output \"MFG=$($b.Manufacturer)\"; "
            "Write-Output \"PROD=$($b.Product)\""
        )
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ]

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                creationflags=creationflags,
            )
        except Exception as e:
            raise HardwareIdentityUnavailableError(
                f"اجرای دستور بررسی مشخصات سخت‌افزاری سیستم با خطا متوقف شد: {e}"
            ) from e

        if proc.returncode != 0:
            raise HardwareIdentityUnavailableError(
                f"پرس‌وجوی مشخصات سیستم با کد خطای {proc.returncode} خاتمه یافت."
            )

        uuid, serial, mfg, prod = None, None, None, None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("UUID="):
                uuid = line[5:].strip()
            elif line.startswith("SERIAL="):
                serial = line[7:].strip()
            elif line.startswith("MFG="):
                mfg = line[4:].strip()
            elif line.startswith("PROD="):
                prod = line[5:].strip()

        return uuid, serial, mfg, prod

    def get_fingerprint(self) -> str:
        """Acquire Windows SMBIOS identity and compute fp_v1 fingerprint."""
        uuid, serial, mfg, prod = self._query_wmi()
        fp, _ = compute_hardware_fingerprint_from_components(uuid, serial, mfg, prod)
        return fp


class MockHardwareProvider(HardwareIdentitySource):
    """Test provider with deterministic hardware components."""

    def __init__(
        self,
        uuid: Optional[str] = "4C4C4544-004A-4810-804E-C6C04F4B3232",
        serial: Optional[str] = "CN1296385A0123",
        mfg: Optional[str] = "Dell Inc.",
        prod: Optional[str] = "0M5R01",
    ):
        self.uuid = uuid
        self.serial = serial
        self.mfg = mfg
        self.prod = prod

    def get_fingerprint(self) -> str:
        fp, _ = compute_hardware_fingerprint_from_components(
            self.uuid, self.serial, self.mfg, self.prod
        )
        return fp


def get_system_hardware_fingerprint() -> str:
    """Convenience function returning the current machine's fp_v1 fingerprint."""
    if sys.platform == "win32":
        provider = WindowsHardwareProvider()
    else:
        # Fallback for non-Windows development/testing environments
        provider = MockHardwareProvider()
    return provider.get_fingerprint()
