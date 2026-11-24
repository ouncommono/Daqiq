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

# Canonical list of 10 core application tab feature keys + aliases
CORE_TAB_FEATURES = (
    "dashboard",
    "products",
    "batches",
    "sales",
    "services",
    "upgrades",
    "suppliers_payments",
    "reports",
    "employees",
    "settings",
)

# Granular sub-feature entitlements mapped to their parent tab for legacy/full backward compatibility
SUBFEATURE_PARENT_TAB: Dict[str, str] = {
    "excel_report_export": "reports",
    "partner_export": "products",
    "report_builder": "reports",
    "auto_backup": "settings",
    "manual_backup_restore": "settings",
    "database_encryption": "settings",
    "multi_database": "settings",
    "barcode_scanner": "sales",
    "audit_logs": "reports",
    "taxonomy_import_export": "settings",
    "custom_calendar_formats": "settings",
    "profit_analytics": "reports",
    "price_edit": "sales",
    "batch_delete": "batches",
}

ALL_LICENSE_FEATURES = CORE_TAB_FEATURES + tuple(SUBFEATURE_PARENT_TAB.keys())

TAB_MODULE_TO_FEATURE: Dict[str, str] = {
    "dashboard": "dashboard",
    "products": "products",
    "inventory": "products",
    "batches": "batches",
    "purchases": "batches",
    "sales": "sales",
    "services": "services",
    "upgrades": "upgrades",
    "suppliers": "suppliers_payments",
    "suppliers_payments": "suppliers_payments",
    "reports": "reports",
    "employees": "employees",
    "users": "employees",
    "settings": "settings",
}

FEATURE_LABELS_FA: Dict[str, str] = {
    "dashboard": "داشبورد",
    "products": "مدیریت کالاها",
    "batches": "ثبت خرید و محموله‌ها",
    "sales": "ثبت فروش",
    "services": "میز خدمت",
    "upgrades": "ارتقای کالا",
    "suppliers_payments": "تأمین‌کنندگان و پرداخت‌ها",
    "reports": "گزارش‌های جامع",
    "employees": "مدیریت کاربران",
    "settings": "تنظیمات",
    "excel_report_export": "خروجی اکسل گزارش‌ها",
    "partner_export": "خروجی موجودی همکار",
    "report_builder": "ساخت و ویرایش گزارش‌های سفارشی",
    "auto_backup": "پشتیبان‌گیری خودکار",
    "manual_backup_restore": "پشتیبان‌گیری و بازیابی دستی",
    "database_encryption": "رمزگذاری پایگاه داده",
    "multi_database": "مدیریت چند پایگاه داده",
    "barcode_scanner": "اسکنر بارکد",
    "audit_logs": "گزارش‌های ممیزی",
    "taxonomy_import_export": "ورود و خروج ساختار کالاها و خدمات",
    "custom_calendar_formats": "تغییر قالب تقویم و ساعت",
    "profit_analytics": "تحلیل سود و گزارش‌های سودآوری",
    "price_edit": "ویرایش قیمت فروش در فاکتور",
    "batch_delete": "حذف محموله خرید",
}


class LicenseService:
    """Central licensing service for Daqiq Desktop."""

    def __init__(
        self,
        store: Optional[LicenseStore] = None,
        verifier: Optional[LicenseVerifier] = None,
        hardware_provider: Optional[HardwareIdentitySource] = None,
        clock_provider: Optional[Callable[[], datetime.datetime]] = None,
        app_version: str = "4.9.5",
        store_name_provider: Optional[Callable[[], str]] = None,
    ):
        self.store = store or LicenseStore()
        self.verifier = verifier or LicenseVerifier()
        self._hardware_provider = hardware_provider
        self.clock_provider = clock_provider or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self.app_version = app_version
        self.store_name_provider = store_name_provider

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
            # Re-verify clock-rollback and time boundary even for cached valid results
            now_utc = self.clock_provider()
            env = self._last_result.license
            if env:
                is_sub = env.payload.license_type in ("subscription", "trial")
                skew_sec = (env.payload.max_clock_skew_hours or 24) * 3600
                try:
                    current_fp = self.get_hardware_fingerprint()
                    self.store.check_and_update_clock_state(
                        device_fingerprint=current_fp,
                        is_subscription=is_sub,
                        now_utc=now_utc,
                        tolerance_sec=skew_sec,
                    )
                except ClockRollbackError as e:
                    self._last_result = ValidationResult(
                        status=ValidationStatus.CLOCK_TAMPERED,
                        is_valid=False,
                        license=env,
                        message_fa=STATUS_MESSAGES_FA[ValidationStatus.CLOCK_TAMPERED],
                        detail=str(e),
                    )
                    return self._last_result
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
                detail="",
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
        """Export clean .daqreq JSON file to target path with live store_name sync."""
        resolved_store = (store_name or "").strip()
        if not resolved_store and self.store_name_provider is not None:
            try:
                resolved_store = str(self.store_name_provider() or "").strip()
            except Exception:
                resolved_store = ""
        req_dict = create_device_request_dict(
            app_version=self.app_version,
            device_label=device_label,
            store_name=resolved_store,
        )
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(req_dict, f, ensure_ascii=False, indent=2)

    def remove_license(self) -> bool:
        """Remove active license from disk and reset memory state."""
        ok = self.store.remove_license()
        self._last_result = None
        return ok

    def is_feature_enabled(self, feature_id: str) -> bool:
        """Check whether a tab module or granular sub-feature is authorized in the active license."""
        canonical_key = TAB_MODULE_TO_FEATURE.get(feature_id, feature_id)
        if self._last_result is None or not self._last_result.is_valid:
            res = self.check_license()
            if not res.is_valid:
                return False

        lic = self._last_result.license
        if not lic:
            return False

        features = lic.payload.features or {}
        if canonical_key in features:
            return bool(features[canonical_key])

        # Backward compatibility for legacy/full licenses that omit new granular sub-feature flags:
        # Sub-features default to their parent tab's authorization (or True if parent is enabled/full).
        if canonical_key in SUBFEATURE_PARENT_TAB:
            parent_tab = SUBFEATURE_PARENT_TAB[canonical_key]
            if parent_tab in features:
                return bool(features[parent_tab])
            return all(bool(features.get(t, False)) for t in CORE_TAB_FEATURES)

        # Core tab keys default to deny if explicitly omitted from a partial license
        return False

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
