# licensing/license_policy.py
"""High-level LicenseService orchestrating verification, storage, hardware identity, and entitlements."""

import datetime
import json
import os
from typing import Callable, Dict, List, Optional, Any

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
from .device_identity import (
    HardwareIdentitySource,
    get_system_hardware_fingerprint,
    get_system_hardware_fingerprint_with_tier,
    create_device_request_dict,
)

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
        app_version: str = "4.9.2",
    ):
        self.store = store or LicenseStore()
        self.verifier = verifier or LicenseVerifier()
        self._hardware_provider = hardware_provider
        self.clock_provider = clock_provider or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self.app_version = app_version

        self._cached_fingerprint: Optional[str] = None
        self._cached_tiers: Optional[Dict[str, str]] = None
        self._last_result: Optional[ValidationResult] = None

    def get_active_key_fingerprints(self) -> List[Dict[str, str]]:
        """Return read-only key IDs and human-readable fingerprints."""
        return self.verifier.key_registry.get_active_key_fingerprints()

    def get_hardware_fingerprint(self) -> str:
        """Acquire or return cached fp_v1 device fingerprint."""
        if self._cached_fingerprint is None:
            if self._hardware_provider is not None:
                self._cached_fingerprint = self._hardware_provider.get_fingerprint()
            else:
                self._cached_fingerprint = get_system_hardware_fingerprint()
        return self._cached_fingerprint

    def get_hardware_tiers(self) -> Dict[str, str]:
        """Return dict of available hardware tiers."""
        if self._cached_tiers is None:
            if self._hardware_provider is not None:
                self._cached_tiers = self._hardware_provider.get_all_tiers()
            else:
                fp, tier = get_system_hardware_fingerprint_with_tier()
                self._cached_tiers = {tier: fp}
        return self._cached_tiers

    def check_license(self, force_reload: bool = False) -> ValidationResult:
        """Load stored license, acquire hardware identity, verify signature and boundaries."""
        if not force_reload and self._last_result is not None and self._last_result.is_valid:
            # Re-verify time boundary even for cached valid results
            now_utc = self.clock_provider()
            env = self._last_result.license
            if env and env.payload.license_type in ("subscription", "trial") and env.payload.expires_at:
                from .license_verifier import parse_iso8601_utc
                dt_exp = parse_iso8601_utc(env.payload.expires_at)
                grace_days = env.payload.grace_period_days if env.payload.grace_period_days is not None else 7
                grace_deadline = dt_exp + datetime.timedelta(days=grace_days)
                if now_utc >= grace_deadline:
                    self._last_result = ValidationResult(
                        status=ValidationStatus.EXPIRED,
                        is_valid=False,
                        license=env,
                        message_fa=STATUS_MESSAGES_FA[ValidationStatus.EXPIRED],
                        detail=f"Subscription expired at {env.payload.expires_at}",
                        days_remaining=0,
                        is_trial=(env.payload.license_type == "trial"),
                    )
                    return self._last_result
                elif now_utc >= dt_exp:
                    # In grace period
                    self._last_result = ValidationResult(
                        status=ValidationStatus.GRACE_PERIOD,
                        is_valid=True,
                        license=env,
                        message_fa=STATUS_MESSAGES_FA[ValidationStatus.GRACE_PERIOD],
                        detail=f"In grace period until {grace_deadline.isoformat()}",
                        in_grace_period=True,
                        grace_mode=env.payload.grace_mode or "readonly",
                        days_remaining=0,
                        is_trial=(env.payload.license_type == "trial"),
                    )
                    return self._last_result
            return self._last_result

        # 1. Acquire hardware fingerprint
        try:
            current_fp = self.get_hardware_fingerprint()
            tiers = self.get_hardware_tiers()
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
        is_sub = envelope.payload.license_type in ("subscription", "trial")
        skew_sec = (envelope.payload.max_clock_skew_hours or 24) * 3600
        try:
            self.store.check_and_update_clock_state(
                device_fingerprint=current_fp,
                is_subscription=is_sub,
                now_utc=now_utc,
                tolerance_sec=skew_sec,
            )
        except ClockRollbackError as e:
            res = ValidationResult(
                status=ValidationStatus.CLOCK_TAMPERED,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CLOCK_TAMPERED],
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
            available_hardware_tiers=tiers,
        )
        self._last_result = val_result
        return val_result

    def import_license_file(self, file_path: str) -> ValidationResult:
        """Validate candidate license file completely BEFORE persisting."""
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

        return self.import_license_bytes(candidate_bytes)

    def import_license_token(self, token_text: str) -> ValidationResult:
        """Validate candidate text token or JSON string and persist if valid."""
        clean = (token_text or "").strip()
        if not clean:
            return ValidationResult(
                status=ValidationStatus.MISSING,
                is_valid=False,
                license=None,
                message_fa="متن لایسنس یا توکن وارد نشده است.",
            )
        return self.import_license_bytes(clean.encode("utf-8"))

    def import_license_bytes(self, candidate_bytes: bytes) -> ValidationResult:
        """Validate candidate raw bytes completely BEFORE persisting."""
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
            tiers = self.get_hardware_tiers()
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
            available_hardware_tiers=tiers,
        )

        if not val_res.is_valid:
            # Candidate is invalid: do NOT write to disk!
            return val_res

        # 4. Atomically persist validated license
        try:
            self.store.save_license_bytes_atomic(candidate_bytes)
            skew_sec = (envelope.payload.max_clock_skew_hours or 24) * 3600
            self.store.check_and_update_clock_state(
                device_fingerprint=current_fp,
                is_subscription=(envelope.payload.license_type in ("subscription", "trial")),
                now_utc=now_utc,
                tolerance_sec=skew_sec,
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

    def export_device_request_file(self, target_path: str, device_label: str = "", store_name: str = "") -> None:
        """Export .daqreq JSON file to target path."""
        req_dict = create_device_request_dict(app_version=self.app_version, device_label=device_label, store_name=store_name)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(req_dict, f, ensure_ascii=False, indent=2)

    def remove_license(self) -> bool:
        """Remove active license from disk and reset memory state."""
        ok = self.store.remove_license()
        self._last_result = None
        return ok

    def is_feature_enabled(self, feature_id: str) -> bool:
        """Check whether a specific module/tab feature is authorized in the active license."""
        canonical_key = TAB_MODULE_TO_FEATURE.get(feature_id, feature_id)
        if self._last_result is None or not self._last_result.is_valid:
            res = self.check_license()
            if not res.is_valid:
                return False

        lic = self._last_result.license
        if not lic:
            return False

        # Default deny: omitted keys evaluate to False
        return bool(lic.payload.features.get(canonical_key, False))

    def is_write_allowed(self) -> bool:
        """Return True if write operations are permitted (False if readonly grace period)."""
        if self._last_result is None:
            self.check_license()
        if not self._last_result or not self._last_result.is_valid:
            return False
        if self._last_result.in_grace_period and self._last_result.grace_mode == "readonly":
            return False
        return True

    def get_active_license(self) -> Optional[LicenseEnvelope]:
        """Return the verified active LicenseEnvelope, if valid."""
        if self._last_result and self._last_result.is_valid:
            return self._last_result.license
        return None
