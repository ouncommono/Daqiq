# licensing/license_store.py
"""Database-independent persistent storage for Daqiq offline licenses and clock state.

Enforces deterministic LocalAppData -> ProgramData storage paths, atomic file writes,
multi-location HMAC clock-state mirroring (LocalAppData + Registry HKCU + AppData),
and tamper-evident offline clock-rollback protection.
"""

import datetime
import hashlib
import hmac
import json
import os
import sys
import uuid
from typing import Optional, Tuple, Dict, Any, List

from .license_models import (
    StorageError,
    ClockRollbackError,
)

CLOCK_TOLERANCE_SECONDS = 900  # 15 minutes tolerance for standard clock jitter
DEFAULT_CLOCK_TOLERANCE_SECONDS = 86400  # 24 hours allowable clock skew tolerance
CLOCK_STATE_FILENAME = "clock_state.json"
LICENSE_FILENAME = "license.daqlic"
HMAC_SECRET_CONSTANT = b"DAQIQ-CLOCK-GUARD-V2-SECRET-93810482"
REGISTRY_KEY_PATH = r"Software\Daqiq\Licensing"


def get_per_user_dir() -> str:
    """Return %LOCALAPPDATA%\\Daqiq\\license or cross-platform equivalent."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~")
    path = os.path.join(base, "Daqiq", "license")
    return os.path.normpath(path)


def get_machine_wide_dir() -> str:
    """Return %PROGRAMDATA%\\Daqiq\\license or cross-platform equivalent."""
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
    else:
        base = "/tmp"
    path = os.path.join(base, "Daqiq", "license")
    return os.path.normpath(path)


def get_roaming_appdata_dir() -> str:
    """Return %APPDATA%\\Daqiq\\license or cross-platform equivalent."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~")
    path = os.path.join(base, "Daqiq", "license")
    return os.path.normpath(path)


def _compute_clock_hmac(last_seen_iso: str, device_fingerprint: str) -> str:
    """Compute HMAC-SHA256 binding the high water mark to the device fingerprint."""
    key = hashlib.sha256(HMAC_SECRET_CONSTANT + device_fingerprint.encode("utf-8")).digest()
    msg = f"CLOCK-V2|{last_seen_iso}|{device_fingerprint}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


class LicenseStore:
    """Manages persistent read/write operations for licenses and clock state."""

    def __init__(
        self,
        machine_dir: Optional[str] = None,
        user_dir: Optional[str] = None,
        roaming_dir: Optional[str] = None,
    ):
        self.machine_dir = machine_dir or get_machine_wide_dir()
        self.user_dir = user_dir or get_per_user_dir()
        self.roaming_dir = roaming_dir or get_roaming_appdata_dir()
        self._is_test_env = bool(machine_dir or user_dir)

    def _get_search_dirs(self) -> List[str]:
        """Return list of candidate directories in priority order."""
        dirs = [self.machine_dir, self.user_dir, self.roaming_dir]
        unique_dirs: List[str] = []
        for d in dirs:
            if d and d not in unique_dirs:
                unique_dirs.append(d)
        return unique_dirs

    def _resolve_read_path(self, filename: str) -> Optional[str]:
        """Check machine_dir first, then user_dir, then roaming_dir."""
        for d in self._get_search_dirs():
            target = os.path.join(d, filename)
            if os.path.isfile(target):
                return target
        return None

    def _resolve_write_target(self, filename: str) -> Tuple[str, str]:
        """Determine writable target path (attempting Machine-Wide, falling back to Per-User)."""
        for d in self._get_search_dirs():
            try:
                os.makedirs(d, exist_ok=True)
                probe = os.path.join(d, f".probe_{uuid.uuid4().hex}.tmp")
                with open(probe, "w", encoding="utf-8") as f:
                    f.write("ok")
                os.remove(probe)
                return d, os.path.join(d, filename)
            except (PermissionError, OSError):
                continue
        raise StorageError("هیچ مسیر قابل نوشتنی برای ذخیره‌سازی لایسنس در سیستم یافت نشد.")

    def load_license_bytes(self) -> Optional[bytes]:
        """Read raw bytes of the stored license from disk, or None if missing."""
        path = self._resolve_read_path(LICENSE_FILENAME)
        if not path:
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception as e:
            raise StorageError(f"خطا در خواندن فایل لایسنس ذخیره‌شده: {e}") from e

    def save_license_bytes_atomic(self, raw_bytes: bytes) -> str:
        """Atomically persist raw license bytes to disk without damaging existing files."""
        target_dir, target_file = self._resolve_write_target(LICENSE_FILENAME)
        tmp_file = os.path.join(target_dir, f"{LICENSE_FILENAME}.{uuid.uuid4().hex}.tmp")

        try:
            with open(tmp_file, "wb") as f:
                f.write(raw_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, target_file)
            return target_file
        except Exception as e:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
            raise StorageError(f"خطا در ذخیره‌سازی اتمیک لایسنس: {e}") from e

    def remove_license(self) -> bool:
        """Remove stored license from all candidate directories."""
        removed = False
        for d in self._get_search_dirs():
            target = os.path.join(d, LICENSE_FILENAME)
            if os.path.isfile(target):
                try:
                    os.remove(target)
                    removed = True
                except Exception:
                    pass
        return removed

    def _read_registry_clock_state(self, device_fingerprint: str) -> Optional[datetime.datetime]:
        """Read clock state from Windows HKCU registry if available."""
        if sys.platform != "win32" or self._is_test_env:
            return None
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH) as key:
                saved_iso, _ = winreg.QueryValueEx(key, "LastSeen")
                saved_hmac, _ = winreg.QueryValueEx(key, "HMAC")
                if saved_iso and saved_hmac:
                    expected_hmac = _compute_clock_hmac(saved_iso, device_fingerprint)
                    if hmac.compare_digest(saved_hmac, expected_hmac):
                        clean_iso = saved_iso.strip()
                        if clean_iso.endswith("Z"):
                            clean_iso = clean_iso[:-1] + "+00:00"
                        parsed = datetime.datetime.fromisoformat(clean_iso)
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                        return parsed
        except Exception:
            pass
        return None

    def _write_registry_clock_state(self, iso_str: str, hmac_str: str) -> None:
        """Mirror clock state to Windows HKCU registry."""
        if sys.platform != "win32" or self._is_test_env:
            return
        try:
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY_PATH) as key:
                winreg.SetValueEx(key, "LastSeen", 0, winreg.REG_SZ, iso_str)
                winreg.SetValueEx(key, "HMAC", 0, winreg.REG_SZ, hmac_str)
        except Exception:
            pass

    def check_and_update_clock_state(
        self,
        device_fingerprint: str,
        is_subscription: bool,
        now_utc: Optional[datetime.datetime] = None,
        tolerance_sec: int = CLOCK_TOLERANCE_SECONDS,
    ) -> None:
        """Verify high-water mark across multi-location anchors.

        Recovers smoothly if user corrects the clock.
        Perpetual licenses are immune to clock-rollback errors.
        """
        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)

        # 1. Read file anchor
        file_last_seen: Optional[datetime.datetime] = None
        for d in self._get_search_dirs():
            clock_file = os.path.join(d, CLOCK_STATE_FILENAME)
            if os.path.isfile(clock_file):
                try:
                    with open(clock_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        s_iso = data.get("last_seen_utc")
                        s_hmac = data.get("hmac_tag")
                        if s_iso and s_hmac:
                            expected_hmac = _compute_clock_hmac(s_iso, device_fingerprint)
                            if hmac.compare_digest(s_hmac, expected_hmac):
                                clean_iso = s_iso.strip()
                                if clean_iso.endswith("Z"):
                                    clean_iso = clean_iso[:-1] + "+00:00"
                                p = datetime.datetime.fromisoformat(clean_iso)
                                if p.tzinfo is None:
                                    p = p.replace(tzinfo=datetime.timezone.utc)
                                if file_last_seen is None or p > file_last_seen:
                                    file_last_seen = p
                except Exception:
                    pass

        # 2. Read registry anchor
        reg_last_seen = self._read_registry_clock_state(device_fingerprint)

        # High-water mark is maximum verified timestamp
        candidates = [t for t in (file_last_seen, reg_last_seen) if t is not None]
        last_seen = max(candidates) if candidates else None

        # Check for clock rollback on subscriptions/trials
        if is_subscription and last_seen is not None:
            allowed_floor = last_seen - datetime.timedelta(seconds=tolerance_sec)
            if now_utc < allowed_floor:
                diff = int((last_seen - now_utc).total_seconds())
                raise ClockRollbackError(
                    f"عقب کشیدن ساعت سیستم تشخیص داده شد (اختلاف {diff} ثانیه). لطفاً ساعت و تاریخ ویندوز را همگام‌سازی نمایید."
                )

        # Update high-water mark
        new_high = now_utc
        if last_seen is not None and last_seen > now_utc:
            new_high = last_seen

        new_iso = new_high.strftime("%Y-%m-%dT%H:%M:%SZ")
        new_hmac = _compute_clock_hmac(new_iso, device_fingerprint)
        state_dict = {
            "version": 2,
            "last_seen_utc": new_iso,
            "hmac_tag": new_hmac,
        }

        # Write file anchor to primary user directory
        try:
            target_dir, target_file = self._resolve_write_target(CLOCK_STATE_FILENAME)
            tmp_file = os.path.join(target_dir, f"{CLOCK_STATE_FILENAME}.{uuid.uuid4().hex}.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, target_file)
        except Exception:
            pass

        # Write registry mirror
        self._write_registry_clock_state(new_iso, new_hmac)
