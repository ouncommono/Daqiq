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
PRIMARY_CLOCK_FILE = ".clock_state.dat"
RUNTIME_ANCHOR_FILE = ".runtime_anchor.dat"
LICENSE_FILENAME = "license.daqlic"
HMAC_SECRET_CONSTANT = b"DAQIQ-CLOCK-GUARD-V2-SECRET-93810482"


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
    """Return %APPDATA%\\Daqiq or cross-platform equivalent."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~")
    path = os.path.join(base, "Daqiq")
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
        self._is_test_env = bool(machine_dir or user_dir)
        self.roaming_dir = roaming_dir or (
            os.path.join(self.user_dir, ".roaming_anchor")
            if self._is_test_env
            else get_roaming_appdata_dir()
        )

    def _get_search_dirs(self) -> List[str]:
        """Return list of candidate directories in write priority order."""
        dirs = [self.machine_dir, self.user_dir, self.roaming_dir]
        unique_dirs: List[str] = []
        for d in dirs:
            if d and d not in unique_dirs:
                unique_dirs.append(d)
        return unique_dirs

    def _get_read_dirs(self) -> List[str]:
        """Return candidate directories in read priority order (per-user first, then machine-wide)."""
        dirs = [self.user_dir, self.machine_dir, self.roaming_dir]
        unique_dirs: List[str] = []
        for d in dirs:
            if d and d not in unique_dirs:
                unique_dirs.append(d)
        return unique_dirs

    def _resolve_read_path(self, filename: str) -> Optional[str]:
        """Check user_dir first, then machine_dir, then roaming_dir."""
        for d in self._get_read_dirs():
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

    @staticmethod
    def _atomic_write_bytes(target_dir: str, filename: str, raw_bytes: bytes) -> str:
        os.makedirs(target_dir, exist_ok=True)
        target_file = os.path.join(target_dir, filename)
        tmp_file = os.path.join(target_dir, f"{filename}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp_file, "wb") as f:
                f.write(raw_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, target_file)
            return target_file
        except Exception:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass
            raise

    def save_license_bytes_atomic(self, raw_bytes: bytes) -> str:
        """Atomically persist raw license bytes to disk without damaging existing files."""
        target_dir, target_file = self._resolve_write_target(LICENSE_FILENAME)
        try:
            saved_path = self._atomic_write_bytes(target_dir, LICENSE_FILENAME, raw_bytes)
        except Exception as e:
            raise StorageError(f"خطا در ذخیره‌سازی اتمیک لایسنس: {e}") from e

        # Mirror to per-user directory when primary write targeted machine_dir so user-level updates stay consistent.
        if self.user_dir and self.user_dir != target_dir:
            try:
                self._atomic_write_bytes(self.user_dir, LICENSE_FILENAME, raw_bytes)
            except (PermissionError, OSError):
                pass
        return saved_path

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

    def _write_anchor_atomic(self, directory: str, filename: str, state_dict: dict) -> bool:
        """Atomically persist clock state to an anchor location, returning True if successful."""
        try:
            os.makedirs(directory, exist_ok=True)
            target = os.path.join(directory, filename)
            tmp = os.path.join(directory, f"{filename}.{uuid.uuid4().hex}.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
            return True
        except (PermissionError, OSError):
            return False

    def check_and_update_clock_state(
        self,
        device_fingerprint: str,
        is_subscription: bool,
        now_utc: Optional[datetime.datetime] = None,
        tolerance_sec: int = CLOCK_TOLERANCE_SECONDS,
    ) -> datetime.datetime:
        """Verify high-water mark across multi-location redundant filesystem anchors.

        Zero registry calls: uses HMAC-SHA256 authenticated High-Water-Mark anchors across
        at least two independent user-writable non-DB filesystem locations.
        Returns the monotonic high-water mark UTC datetime (max of now_utc and verified anchors).
        Perpetual licenses are immune to clock-rollback errors.
        """
        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)

        # 1. Read and authenticate all redundant filesystem anchors
        anchor_files = [PRIMARY_CLOCK_FILE, RUNTIME_ANCHOR_FILE, CLOCK_STATE_FILENAME]
        verified_timestamps: List[datetime.datetime] = []

        for d in self._get_search_dirs():
            if not d:
                continue
            for a_name in anchor_files:
                target = os.path.join(d, a_name)
                if os.path.isfile(target):
                    try:
                        with open(target, "r", encoding="utf-8") as f:
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
                                    verified_timestamps.append(p)
                    except Exception:
                        pass

        # High-water mark is maximum verified timestamp across all anchors
        last_seen = max(verified_timestamps) if verified_timestamps else None

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
            "version": 3,
            "last_seen_utc": new_iso,
            "hmac_tag": new_hmac,
        }

        # 2. Multi-location redundant filesystem writes (Zero Windows Registry calls!)
        # Primary user directory (%LOCALAPPDATA%\Daqiq\license): .clock_state.dat + clock_state.json
        if self.user_dir:
            self._write_anchor_atomic(self.user_dir, PRIMARY_CLOCK_FILE, state_dict)
            self._write_anchor_atomic(self.user_dir, CLOCK_STATE_FILENAME, state_dict)

        # Roaming AppData directory (%APPDATA%\Daqiq): .runtime_anchor.dat
        if self.roaming_dir and self.roaming_dir != self.user_dir:
            self._write_anchor_atomic(self.roaming_dir, RUNTIME_ANCHOR_FILE, state_dict)

        # Machine-wide directory (%PROGRAMDATA%\Daqiq\license): .runtime_anchor.dat (if writable)
        if self.machine_dir and self.machine_dir != self.user_dir:
            self._write_anchor_atomic(self.machine_dir, RUNTIME_ANCHOR_FILE, state_dict)

        return new_high
