# licensing/device_identity.py
"""Hardware identity acquisition and node-locking fingerprinting (fp_v1).

Binds licenses strictly to motherboard/SMBIOS identity.
Resilient to Windows reinstallation, RAM upgrades, SSD/HDD swaps, and network changes.
Uses ultra-fast native Win32 kernel32.GetSystemFirmwareTable (< 5 ms, zero PowerShell on primary path).
"""

import abc
import ctypes
from ctypes import wintypes
import datetime
import hashlib
import os
import re
import struct
import subprocess
import sys
import unicodedata
from typing import Dict, List, Optional, Tuple, Any

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

    norm = unicodedata.normalize("NFC", canonical_str).strip()
    norm = " ".join(norm.split())
    norm = norm.upper()

    digest = hashlib.sha256(f"DAQIQ-HWFP-V1|{norm}".encode("utf-8")).hexdigest().lower()
    return f"fp_v1:{digest}", tier


def get_all_available_fingerprint_tiers(
    uuid: Optional[str],
    serial: Optional[str],
    mfg: Optional[str] = None,
    prod: Optional[str] = None,
) -> Dict[str, str]:
    """Return dictionary of all valid tiers computed for the hardware."""
    tiers: Dict[str, str] = {}
    clean_uuid = _clean_string(uuid)
    clean_serial = _clean_string(serial)
    clean_mfg = _clean_string(mfg)
    clean_prod = _clean_string(prod)

    uuid_ok = is_valid_uuid(clean_uuid)
    serial_ok = is_valid_board_serial(clean_serial)
    model_ok = is_valid_model_info(clean_mfg, clean_prod)

    if uuid_ok and serial_ok:
        c1 = f"V1|UUID={clean_uuid}|BOARD={clean_serial}".upper()
        tiers["tier1"] = f"fp_v1:{hashlib.sha256(f'DAQIQ-HWFP-V1|{c1}'.encode('utf-8')).hexdigest().lower()}"
    if uuid_ok and model_ok:
        c2 = f"V1|UUID={clean_uuid}|BOARD_MODEL={clean_mfg}:{clean_prod}".upper()
        tiers["tier2"] = f"fp_v1:{hashlib.sha256(f'DAQIQ-HWFP-V1|{c2}'.encode('utf-8')).hexdigest().lower()}"
    if serial_ok and model_ok:
        c3 = f"V1|BOARD={clean_serial}|BOARD_MODEL={clean_mfg}:{clean_prod}".upper()
        tiers["tier3"] = f"fp_v1:{hashlib.sha256(f'DAQIQ-HWFP-V1|{c3}'.encode('utf-8')).hexdigest().lower()}"

    return tiers


class HardwareIdentitySource(abc.ABC):
    """Abstract interface for hardware fingerprint providers."""

    @abc.abstractmethod
    def get_fingerprint(self) -> str:
        """Return the calculated fp_v1:<64-hex> fingerprint."""
        pass

    def get_all_tiers(self) -> Dict[str, str]:
        """Return dict of all available tiers."""
        fp = self.get_fingerprint()
        return {"tier1": fp}


class NativeWindowsHardwareProvider(HardwareIdentitySource):
    """Fast native Windows SMBIOS reader using kernel32.GetSystemFirmwareTable (< 5 ms)."""

    def __init__(self):
        self._cached_components: Optional[Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]] = None

    def _query_native_smbios(self) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Extract UUID and BaseBoard directly from SMBIOS via GetSystemFirmwareTable."""
        uuid_str: Optional[str] = None
        serial_str: Optional[str] = None
        mfg_str: Optional[str] = None
        prod_str: Optional[str] = None

        try:
            kernel32 = ctypes.windll.kernel32
            RSMB = 0x52534D42  # 'RSMB'
            buf_size = kernel32.GetSystemFirmwareTable(RSMB, 0, None, 0)
            if not buf_size:
                return None, None, None, None

            buf = ctypes.create_string_buffer(buf_size)
            r = kernel32.GetSystemFirmwareTable(RSMB, 0, buf, buf_size)
            if r == 0:
                return None, None, None, None

            raw = bytes(buf)
            data = raw[8:]  # Skip RSMB header
            idx = 0
            while idx < len(data):
                if idx + 4 > len(data):
                    break
                header = data[idx : idx + 4]
                stype, length, handle = struct.unpack("<BBH", header)
                if length < 4 or idx + length > len(data):
                    break
                formatted = data[idx : idx + length]
                str_idx = idx + length
                strings: List[str] = []
                while str_idx < len(data) - 1:
                    if data[str_idx : str_idx + 1] == b"\x00":
                        if str_idx == idx + length:
                            str_idx += 1
                        break
                    end = data.find(b"\x00", str_idx)
                    if end == -1 or end > len(data):
                        break
                    s = data[str_idx:end].decode("latin-1", errors="replace").strip()
                    strings.append(s)
                    str_idx = end + 1
                    if str_idx < len(data) and data[str_idx : str_idx + 1] == b"\x00":
                        str_idx += 1
                        break
                idx = str_idx

                def get_str(str_index: int) -> str:
                    return strings[str_index - 1] if 0 < str_index <= len(strings) else ""

                if stype == 1 and length >= 0x18:
                    uuid_bytes = formatted[0x08:0x18]
                    d1, d2, d3 = struct.unpack("<IHH", uuid_bytes[:8])
                    d4 = uuid_bytes[8:10].hex()
                    d5 = uuid_bytes[10:16].hex()
                    uuid_str = f"{d1:08x}-{d2:04x}-{d3:04x}-{d4}-{d5}"
                elif stype == 2 and length >= 8:
                    mfg_str = get_str(formatted[4])
                    prod_str = get_str(formatted[5])
                    serial_str = get_str(formatted[7])
        except Exception:
            pass

        return uuid_str, serial_str, mfg_str, prod_str

    def _query_powershell_fallback(self) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Fallback querying Win32_ComputerSystemProduct and Win32_BaseBoard via CIM."""
        script = (
            "$u = (Get-CimInstance Win32_ComputerSystemProduct -OperationTimeoutSec 5 | Select-Object -ExpandProperty UUID) 2>$null; "
            "$b = (Get-CimInstance Win32_BaseBoard -OperationTimeoutSec 5 | Select-Object SerialNumber, Manufacturer, Product) 2>$null; "
            'Write-Output "UUID=$u"; '
            'Write-Output "SERIAL=$($b.SerialNumber)"; '
            'Write-Output "MFG=$($b.Manufacturer)"; '
            'Write-Output "PROD=$($b.Product)"'
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
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            proc = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5.0,
                creationflags=creationflags,
            )
            if proc.returncode != 0:
                return None, None, None, None
            u, s, m, p = None, None, None, None
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("UUID="):
                    u = line[5:].strip()
                elif line.startswith("SERIAL="):
                    s = line[7:].strip()
                elif line.startswith("MFG="):
                    m = line[4:].strip()
                elif line.startswith("PROD="):
                    p = line[5:].strip()
            return u, s, m, p
        except Exception:
            return None, None, None, None

    def get_components(self) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        if self._cached_components is None:
            u, s, m, p = self._query_native_smbios()
            if not u or not s:
                # If native didn't get both, try CIM fallback
                u_c, s_c, m_c, p_c = self._query_powershell_fallback()
                u = u or u_c
                s = s or s_c
                m = m or m_c
                p = p or p_c
            self._cached_components = (u, s, m, p)
        return self._cached_components

    def get_fingerprint(self) -> str:
        u, s, m, p = self.get_components()
        fp, _ = compute_hardware_fingerprint_from_components(u, s, m, p)
        return fp

    def get_all_tiers(self) -> Dict[str, str]:
        u, s, m, p = self.get_components()
        return get_all_available_fingerprint_tiers(u, s, m, p)


# Backwards compatibility alias
WindowsHardwareProvider = NativeWindowsHardwareProvider


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

    def get_all_tiers(self) -> Dict[str, str]:
        return get_all_available_fingerprint_tiers(
            self.uuid, self.serial, self.mfg, self.prod
        )


def get_system_hardware_fingerprint() -> str:
    """Convenience function returning the current machine's fp_v1 fingerprint."""
    if sys.platform == "win32":
        provider = NativeWindowsHardwareProvider()
    else:
        provider = MockHardwareProvider()
    return provider.get_fingerprint()


def get_system_hardware_fingerprint_with_tier() -> Tuple[str, str]:
    """Return (fingerprint, tier_id) for current system."""
    if sys.platform == "win32":
        provider = NativeWindowsHardwareProvider()
        u, s, m, p = provider.get_components()
        return compute_hardware_fingerprint_from_components(u, s, m, p)
    else:
        provider = MockHardwareProvider()
        return compute_hardware_fingerprint_from_components(
            provider.uuid, provider.serial, provider.mfg, provider.prod
        )


def create_device_request_dict(app_version: str = "4.9.1", device_label: str = "") -> Dict[str, Any]:
    """Generate exact .daqreq dictionary compatible with Daqiq-License-Generator."""
    fp, tier = get_system_hardware_fingerprint_with_tier()
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "request_version": 1,
        "product_id": "daqiq.desktop",
        "generated_at": now_iso,
        "device_fingerprint": fp,
        "device_label": device_label or f"صندوق فروشگاه ({tier})",
        "app_version": app_version,
        "hardware_tier": tier,
    }
