# licensing/license_store.py
"""Database-independent persistent storage for Daqiq offline licenses and clock state.

Enforces deterministic ProgramData -> LocalAppData storage paths, atomic file writes,
and tamper-evident offline clock-rollback protection.
"""

import datetime
import hashlib
import hmac
import json
import os
import sys
import uuid
from typing import Optional, Tuple, Dict, Any

from .license_models import (
    LicenseEnvelope,
    StorageError,
    ClockRollbackError,
)

CLOCK_TOLERANCE_SECONDS = 900  # 15 minutes tolerance for standard clock jitter
CLOCK_STATE_FILENAME = "clock_state.json"
LICENSE_FILENAME = "license.daqlic"
HMAC_SECRET_CONSTANT = b"DAQIQ-CLOCK-GUARD-V1-SECRET-84729103"


def get_machine_wide_dir() -> str:
    """Return %PROGRAMDATA%\\Daqiq\\Licensing or cross-platform equivalent."""
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
    else:
        base = "/tmp"
    path = os.path.join(base, "Daqiq", "Licensing")
    return os.path.normpath(path)


def get_per_user_dir() -> str:
    """Return %LOCALAPPDATA%\\Daqiq\\Licensing or cross-platform equivalent."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~")
    path = os.path.join(base, "Daqiq", "Licensing")
    return os.path.normpath(path)


def _compute_clock_hmac(last_seen_iso: str, device_fingerprint: str) -> str:
    """Compute HMAC-SHA256 binding the high water mark to the device fingerprint."""
    key = hashlib.sha256(HMAC_SECRET_CONSTANT + device_fingerprint.encode("utf-8")).digest()
    msg = f"CLOCK|{last_seen_iso}|{device_fingerprint}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


class LicenseStore:
    """Manages persistent read/write operations for licenses and clock state."""

    def __init__(
        self,
        machine_dir: Optional[str] = None,
        user_dir: Optional[str] = None,
    ):
        self.machine_dir = machine_dir or get_machine_wide_dir()
        self.user_dir = user_dir or get_per_user_dir()

    def _resolve_read_path(self, filename: str) -> Optional[str]:
        """Check Machine-Wide location first, then fallback to Per-User location."""
        machine_file = os.path.join(self.machine_dir, filename)
        if os.path.isfile(machine_file):
            return machine_file

        user_file = os.path.join(self.user_dir, filename)
        if os.path.isfile(user_file):
            return user_file

        return None

    def _resolve_write_target(self, filename: str) -> Tuple[str, str]:
        """Determine writable target path (attempting Machine-Wide, falling back to Per-User)."""
        # Try Machine-Wide first
        try:
            os.makedirs(self.machine_dir, exist_ok=True)
            probe = os.path.join(self.machine_dir, f".probe_{uuid.uuid4().hex}.tmp")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("test")
            os.remove(probe)
            return self.machine_dir, os.path.join(self.machine_dir, filename)
        except (PermissionError, OSError):
            pass

        # Fallback to Per-User directory
        try:
            os.makedirs(self.user_dir, exist_ok=True)
            return self.user_dir, os.path.join(self.user_dir, filename)
        except Exception as e:
            raise StorageError(f"امکان ایجاد پوشه ذخیره‌سازی لایسنس وجود ندارد: {e}") from e

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

    def check_and_update_clock_state(
        self,
        device_fingerprint: str,
        is_subscription: bool,
        now_utc: Optional[datetime.datetime] = None,
        tolerance_sec: int = CLOCK_TOLERANCE_SECONDS,
    ) -> None:
        """Verify high water mark to prevent clock rollback on subscriptions, then update.

        Perpetual licenses are immune to clock-state errors.
        """
        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)

        clock_file = self._resolve_read_path(CLOCK_STATE_FILENAME)
        last_seen: Optional[datetime.datetime] = None

        if clock_file and os.path.isfile(clock_file):
            try:
                with open(clock_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    saved_iso = data.get("last_seen_utc")
                    saved_hmac = data.get("hmac_tag")
                    if saved_iso and saved_hmac:
                        expected_hmac = _compute_clock_hmac(saved_iso, device_fingerprint)
                        if hmac.compare_digest(saved_hmac, expected_hmac):
                            # Valid state
                            clean_iso = saved_iso.strip()
                            if clean_iso.endswith("Z"):
                                clean_iso = clean_iso[:-1] + "+00:00"
                            parsed = datetime.datetime.fromisoformat(clean_iso)
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                            last_seen = parsed
            except Exception:
                # Corrupted clock file: ignore safely (do not brick system)
                last_seen = None

        # Check for clock rollback on subscriptions
        if is_subscription and last_seen is not None:
            allowed_floor = last_seen - datetime.timedelta(seconds=tolerance_sec)
            if now_utc < allowed_floor:
                diff = int((last_seen - now_utc).total_seconds())
                raise ClockRollbackError(
                    f"عقب کشیدن ساعت سیستم تشخیص داده شد (اختلاف {diff} ثانیه). ساعت ویندوز را همگام کنید."
                )

        # Update high water mark
        new_high = now_utc
        if last_seen is not None and last_seen > now_utc:
            # If perpetual or within tolerance, do not decrement high water mark
            new_high = last_seen

        new_iso = new_high.strftime("%Y-%m-%dT%H:%M:%SZ")
        new_hmac = _compute_clock_hmac(new_iso, device_fingerprint)
        state_dict = {
            "version": 1,
            "last_seen_utc": new_iso,
            "hmac_tag": new_hmac,
        }

        try:
            target_dir, target_file = self._resolve_write_target(CLOCK_STATE_FILENAME)
            tmp_file = os.path.join(target_dir, f"{CLOCK_STATE_FILENAME}.{uuid.uuid4().hex}.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state_dict, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, target_file)
        except Exception:
            # Writing clock state should not crash the app if read was successful
            pass
