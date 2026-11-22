# licensing/license_policy.py
"""High-level LicenseService orchestrating verification, storage, hardware identity, and entitlements."""

import datetime
import os
from typing import Callable, Dict, Optional

from .license_models import (
    LicenseEnvelope,
    ValidationStatus,
    ValidationResult,
    LicensingError,
    HardwareIdentityUnavailableError,
    ClockRollbackError,
)
from .license_store import LicenseStore
from .license_verifier import LicenseVerifier, STATUS_MESSAGES_FA
from .device_identity import HardwareIdentitySource, get_system_hardware_fingerprint

# Canonical list of 10 feature keys mapped directly to Daqiq application tabs
TAB_MODULE_TO_FEATURE: Dict[str, str] = {
    "dashboard": "dashboard",
    "products": "products",
    "batches": "batches",
    "sales": "sales",
    "services": "services",
    "upgrades": "upgrades",
    "suppliers": "suppliers_payments",
    "suppliers_payments": "suppliers_payments",
    "reports": "reports",
    "employees": "employees",
    "settings": "settings",
}


class LicenseService:
    """Central licensing service for Daqiq Desktop."""

    def __init__(
        self,
        store: Optional[LicenseStore] = None,
        verifier: Optional[LicenseVerifier] = None,
        hardware_provider: Optional[HardwareIdentitySource] = None,
        clock_provider: Optional[Callable[[], datetime.datetime]] = None,
        app_version: str = "4.9.0",
    ):
        self.store = store or LicenseStore()
        self.verifier = verifier or LicenseVerifier()
        self._hardware_provider = hardware_provider
        self.clock_provider = clock_provider or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self.app_version = app_version

        self._cached_fingerprint: Optional[str] = None
        self._last_result: Optional[ValidationResult] = None

    def get_hardware_fingerprint(self) -> str:
        """Acquire or return cached fp_v1 device fingerprint."""
        if self._cached_fingerprint is None:
            if self._hardware_provider is not None:
                self._cached_fingerprint = self._hardware_provider.get_fingerprint()
            else:
                self._cached_fingerprint = get_system_hardware_fingerprint()
        return self._cached_fingerprint

    def check_license(self, force_reload: bool = False) -> ValidationResult:
        """Load stored license, acquire hardware identity, verify signature and boundaries."""
        if not force_reload and self._last_result is not None and self._last_result.is_valid:
            # Re-verify time boundary even for cached valid results
            now_utc = self.clock_provider()
            env = self._last_result.license
            if env and env.payload.license_type == "subscription" and env.payload.expires_at:
                from .license_verifier import parse_iso8601_utc
                dt_exp = parse_iso8601_utc(env.payload.expires_at)
                if now_utc >= dt_exp:
                    self._last_result = ValidationResult(
                        status=ValidationStatus.EXPIRED,
                        is_valid=False,
                        license=env,
                        message_fa=STATUS_MESSAGES_FA[ValidationStatus.EXPIRED],
                        detail=f"Subscription expired at {env.payload.expires_at}",
                    )
                    return self._last_result
            return self._last_result

        # 1. Acquire hardware fingerprint
        try:
            current_fp = self.get_hardware_fingerprint()
        except HardwareIdentityUnavailableError as e:
            res = ValidationResult(
                status=ValidationStatus.HARDWARE_IDENTITY_UNAVAILABLE,
                is_valid=False,
                license=None,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.HARDWARE_IDENTITY_UNAVAILABLE],
                detail=str(e),
            )
            self._last_result = res
            return res

        # 2. Read license file from store
        try:
            raw_bytes = self.store.load_license_bytes()
        except Exception as e:
            res = ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=None,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                detail=f"Error reading license file: {e}",
            )
            self._last_result = res
            return res

        if not raw_bytes:
            res = ValidationResult(
                status=ValidationStatus.MISSING,
                is_valid=False,
                license=None,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.MISSING],
                detail="فایل لایسنس بر روی سیستم موجود نیست.",
            )
            self._last_result = res
            return res

        # 3. Parse license envelope
        try:
            envelope = self.verifier.parse_envelope_from_bytes(raw_bytes)
        except LicensingError as e:
            res = ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=None,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                detail=str(e),
            )
            self._last_result = res
            return res

        # 4. Check clock-rollback state
        now_utc = self.clock_provider()
        is_sub = envelope.payload.license_type == "subscription"
        try:
            self.store.check_and_update_clock_state(
                device_fingerprint=current_fp,
                is_subscription=is_sub,
                now_utc=now_utc,
            )
        except ClockRollbackError as e:
            res = ValidationResult(
                status=ValidationStatus.CLOCK_ROLLBACK,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CLOCK_ROLLBACK],
                detail=str(e),
            )
            self._last_result = res
            return res

        # 5. Cryptographic and semantic validation
        val_result = self.verifier.validate_license(
            envelope=envelope,
            current_hardware_fingerprint=current_fp,
            current_app_version=self.app_version,
            now_utc=now_utc,
        )
        self._last_result = val_result
        return val_result

    def import_license_file(self, file_path: str) -> ValidationResult:
        """Validate candidate license completely BEFORE persisting.

        Existing valid licenses are never overwritten by an invalid candidate.
        """
        if not os.path.isfile(file_path):
            return ValidationResult(
                status=ValidationStatus.MISSING,
                is_valid=False,
                license=None,
                message_fa="فایل انتخاب‌شده در مسیر مشخص‌شده وجود ندارد.",
                detail=f"File not found: {file_path}",
            )

        try:
            with open(file_path, "rb") as f:
                candidate_bytes = f.read()
        except Exception as e:
            return ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=None,
                message_fa="امکان خواندن فایل انتخاب‌شده وجود ندارد.",
                detail=str(e),
            )

        # 1. Parse envelope
        try:
            envelope = self.verifier.parse_envelope_from_bytes(candidate_bytes)
        except LicensingError as e:
            return ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=None,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                detail=str(e),
            )

        # 2. Acquire hardware identity
        try:
            current_fp = self.get_hardware_fingerprint()
        except HardwareIdentityUnavailableError as e:
            return ValidationResult(
                status=ValidationStatus.HARDWARE_IDENTITY_UNAVAILABLE,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.HARDWARE_IDENTITY_UNAVAILABLE],
                detail=str(e),
            )

        # 3. Validate signature and boundaries
        now_utc = self.clock_provider()
        val_res = self.verifier.validate_license(
            envelope=envelope,
            current_hardware_fingerprint=current_fp,
            current_app_version=self.app_version,
            now_utc=now_utc,
        )

        if not val_res.is_valid:
            # Candidate is invalid: do NOT write to disk!
            return val_res

        # 4. Atomically persist validated license
        try:
            self.store.save_license_bytes_atomic(candidate_bytes)
            self.store.check_and_update_clock_state(
                device_fingerprint=current_fp,
                is_subscription=(envelope.payload.license_type == "subscription"),
                now_utc=now_utc,
            )
        except Exception as e:
            return ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=envelope,
                message_fa="خطا در ذخیره‌سازی فایل لایسنس در سیستم.",
                detail=str(e),
            )

        self._last_result = val_res
        return val_res

    def is_feature_enabled(self, feature_id: str) -> bool:
        """Check whether a specific module/tab feature is authorized in the active license."""
        canonical_key = TAB_MODULE_TO_FEATURE.get(feature_id, feature_id)
        if self._last_result is None or not self._last_result.is_valid:
            # Re-check if not evaluated yet
            res = self.check_license()
            if not res.is_valid:
                return False

        lic = self._last_result.license
        if not lic:
            return False

        # Default deny: omitted keys evaluate to False
        return bool(lic.payload.features.get(canonical_key, False))

    def get_active_license(self) -> Optional[LicenseEnvelope]:
        """Return the verified active LicenseEnvelope, if valid."""
        if self._last_result and self._last_result.is_valid:
            return self._last_result.license
        return None
