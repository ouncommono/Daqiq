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
from .keys import get_support_phone
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
    "print_invoices": "reports",
    "backup_export": "settings",
    "customers": "sales",
    "installments": "customers",
    "charts_analytics": "reports",
    "word_export": "reports",
    "checks_manage": "customers",
    "multi_item_invoices": "sales",
    "user_performance": "employees",
    "proforma_invoices": "sales",
    "supplier_installments": "suppliers_payments",
    "incidental_costs": "sales",
    "service_installments": "services",
}

OPTIONAL_DEFAULT_TRUE_FEATURES = frozenset({
    "print_invoices",
    "backup_export",
    "customers",
    "installments",
    "charts_analytics",
    "word_export",
    "checks_manage",
    "multi_item_invoices",
    "user_performance",
    "proforma_invoices",
    "supplier_installments",
    "incidental_costs",
    "service_installments",
})

ALL_LICENSE_FEATURES = CORE_TAB_FEATURES + tuple(SUBFEATURE_PARENT_TAB.keys())

TAB_MODULE_TO_FEATURE: Dict[str, str] = {
    "dashboard": "dashboard",
    "products": "products",
    "inventory": "products",
    "batches": "batches",
    "purchases": "batches",
    "sales": "sales",
    "proforma": "proforma_invoices",
    "services": "services",
    "upgrades": "upgrades",
    "suppliers": "suppliers_payments",
    "suppliers_payments": "suppliers_payments",
    "customers": "customers",
    "reports": "reports",
    "charts": "charts_analytics",
    "employees": "employees",
    "users": "employees",
    "settings": "settings",
}

FEATURE_LABELS_FA: Dict[str, str] = {
    "dashboard": "داشبورد",
    "products": "مدیریت کالاها",
    "inventory": "انبار و کالاها",
    "batches": "ثبت خرید و محموله‌ها",
    "purchases": "ثبت خرید و محموله‌ها",
    "sales": "ثبت فروش",
    "services": "میز خدمت",
    "upgrades": "ارتقای کالا",
    "suppliers": "تأمین‌کنندگان و پرداخت‌ها",
    "suppliers_payments": "تأمین‌کنندگان و پرداخت‌ها",
    "reports": "گزارش‌های جامع",
    "employees": "مدیریت کاربران",
    "users": "مدیریت کاربران",
    "settings": "تنظیمات",
    "excel_report_export": "خروجی اکسل گزارش‌ها",
    "partner_export": "خروجی موجودی همکار",
    "report_builder": "ساخت و ویرایش گزارش‌های سفارشی",
    "report_sales": "گزارش فروش",
    "report_purchases": "گزارش خریدها",
    "report_inventory": "گزارش موجودی انبار",
    "report_financial": "گزارش مالی و سود",
    "report_services": "گزارش خدمات فنی",
    "report_upgrades": "گزارش ارتقای کالا",
    "report_suppliers": "گزارش تأمین‌کنندگان",
    "report_debts": "گزارش بدهی و مطالبات",
    "report_exports": "خروجی اکسل گزارش‌ها",
    "auto_backup": "پشتیبان‌گیری خودکار",
    "manual_backup_restore": "پشتیبان‌گیری و بازیابی دستی",
    "backup_manage": "مدیریت پشتیبان‌گیری و بازیابی",
    "database_encryption": "رمزگذاری پایگاه داده",
    "database_security": "امنیت و رمزنگاری پایگاه داده",
    "security_settings": "تنظیمات امنیتی",
    "multi_database": "مدیریت چند پایگاه داده",
    "barcode_scanner": "اسکنر بارکد",
    "audit_logs": "گزارش‌های ممیزی",
    "taxonomy_import_export": "ورود و خروج ساختار کالاها و خدمات",
    "taxonomy_manage": "مدیریت دسته‌بندی کالاها و خدمات",
    "custom_calendar_formats": "تغییر قالب تقویم و ساعت",
    "profit_analytics": "تحلیل سود و گزارش‌های سودآوری",
    "price_edit": "ویرایش قیمت فروش در فاکتور",
    "price_history": "تاریخچه تغییرات قیمت",
    "batch_edit": "ویرایش محموله خرید",
    "batch_delete": "حذف محموله خرید",
    "sale_edit": "ویرایش فاکتور فروش",
    "sale_delete": "حذف فاکتور فروش",
    "product_edit": "ویرایش اطلاعات کالا",
    "product_delete": "حذف کالا",
    "service_edit": "ویرایش خدمات",
    "upgrade_edit": "ویرایش ارتقای کالا",
    "returns_manage": "مدیریت مرجوعی کالا",
    "supplier_manage": "مدیریت تأمین‌کنندگان",
    "employee_manage": "مدیریت کارکنان و سطوح دسترسی",
    "user_manage": "مدیریت کاربران",
    "inventory_export": "خروجی موجودی همکار و انبار",
    "multi_pc_lan": "اشتراک‌گذاری شبکه (چند کاربر همزمان)",
    "concurrent_edit": "مدیریت ویرایش همزمان",
    "dark_theme": "حالت تاریک",
    "light_theme": "حالت روشن",
    "print_invoices": "چاپ فاکتورها و گزارش‌ها",
    "backup_export": "پشتیبان‌گیری و خروجی اطلاعات",
    "customers": "مدیریت مشتریان",
    "installments": "فروش و پرداخت اقساطی",
    "charts_analytics": "گزارش‌های نموداری و تحلیل‌ها",
    "word_export": "خروجی قابل ویرایش Word",
    "checks_manage": "مدیریت چک‌ها",
    "multi_item_invoices": "ثبت فاکتور چندقلمی",
    "user_performance": "گزارش عملکرد کاربران",
    "proforma": "پیش‌فاکتورها",
    "proforma_invoices": "پیش‌فاکتورها و تبدیل به فاکتور فروش",
    "supplier_installments": "خرید اقساطی و اقساط تأمین‌کنندگان",
    "incidental_costs": "هزینه جانبی در فاکتورها",
    "service_installments": "فروش اقساطی خدمات",
}


def get_feature_label_fa(feature_id: str) -> str:
    """Return a clean Persian display label for any feature key (never leaks raw ASCII identifiers)."""
    raw = str(feature_id or "").strip()
    if not raw:
        return "بخش سیستمی"
    canonical = TAB_MODULE_TO_FEATURE.get(raw, raw)
    if raw in FEATURE_LABELS_FA:
        return FEATURE_LABELS_FA[raw]
    if canonical in FEATURE_LABELS_FA:
        return FEATURE_LABELS_FA[canonical]
    if canonical in SUBFEATURE_PARENT_TAB:
        parent = SUBFEATURE_PARENT_TAB[canonical]
        parent_label = FEATURE_LABELS_FA.get(parent, "سیستم")
        return f"زیرماژول {parent_label}"
    # Deterministic Persian fallback if an unexpected ASCII key appears in a future license
    return "قابلیت تخصصی سامانه"


def get_active_features_fa(features: Optional[Dict[str, Any]]) -> List[str]:
    """Return deduplicated Persian labels for all enabled features in a license."""
    if not isinstance(features, dict):
        return []
    labels: List[str] = []
    seen = set()
    for key, enabled in features.items():
        if not enabled:
            continue
        label = get_feature_label_fa(key)
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def get_grace_mode_label_fa(grace_mode: Optional[str]) -> str:
    """Translate internal grace_mode code into clear Persian copy."""
    return "کامل" if str(grace_mode or "").strip().lower() == "full" else "فقط خواندنی"


class LicenseService:
    """Central licensing service for Daqiq Desktop."""

    def __init__(
        self,
        store: Optional[LicenseStore] = None,
        verifier: Optional[LicenseVerifier] = None,
        hardware_provider: Optional[HardwareIdentitySource] = None,
        clock_provider: Optional[Callable[[], datetime.datetime]] = None,
        app_version: str = "5.0.2",
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
        self._last_anchor_sync_at: Optional[datetime.datetime] = None
        self._high_water_mark_utc: Optional[datetime.datetime] = None

    def get_active_key_fingerprints(self) -> List[Dict[str, str]]:
        """Return read-only key IDs and human-readable fingerprints."""
        return self.verifier.key_registry.get_active_key_fingerprints()

    def get_app_security_id_display(self) -> str:
        """Return the exact canonical 'شناسه امنیتی برنامه' shown in LicenseDialog and exported in .daqreq."""
        try:
            key_fps = self.get_active_key_fingerprints()
            if key_fps:
                displays = [
                    str(k.get("display") or k.get("fingerprint") or "").strip()
                    for k in key_fps
                    if (k.get("display") or k.get("fingerprint"))
                ]
                if displays:
                    return ", ".join(displays)
        except Exception:
            pass
        return "پیش‌فرض"

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
                need_anchor_sync = (
                    self._last_anchor_sync_at is None
                    or now_utc < self._last_anchor_sync_at
                    or (now_utc - self._last_anchor_sync_at).total_seconds() >= 60.0
                )
                if need_anchor_sync:
                    is_sub = env.payload.license_type in ("subscription", "trial", "timed")
                    skew_hours = (
                        env.payload.max_clock_skew_hours
                        if env.payload.max_clock_skew_hours is not None
                        else 24
                    )
                    skew_sec = max(0, int(skew_hours)) * 3600
                    try:
                        current_fp = self.get_hardware_fingerprint()
                        hwm = self.store.check_and_update_clock_state(
                            device_fingerprint=current_fp,
                            is_subscription=is_sub,
                            now_utc=now_utc,
                            tolerance_sec=skew_sec,
                        )
                        if self._high_water_mark_utc is None or hwm > self._high_water_mark_utc:
                            self._high_water_mark_utc = hwm
                        self._last_anchor_sync_at = now_utc
                    except ClockRollbackError as e:
                        self._last_result = ValidationResult(
                            status=ValidationStatus.CLOCK_TAMPERED,
                            is_valid=False,
                            license=env,
                            message_fa=STATUS_MESSAGES_FA[ValidationStatus.CLOCK_TAMPERED],
                            detail=str(e),
                        )
                        return self._last_result
                self._last_result = self.verifier.evaluate_validity_window(
                    env,
                    now_utc=now_utc,
                    high_water_mark_utc=self._high_water_mark_utc,
                )
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
        need_anchor_sync = (
            force_reload
            or self._last_anchor_sync_at is None
            or now_utc < self._last_anchor_sync_at
            or (now_utc - self._last_anchor_sync_at).total_seconds() >= 60.0
        )
        if need_anchor_sync:
            is_sub = envelope.payload.license_type in ("subscription", "trial", "timed")
            skew_hours = (
                envelope.payload.max_clock_skew_hours
                if envelope.payload.max_clock_skew_hours is not None
                else 24
            )
            skew_sec = max(0, int(skew_hours)) * 3600
            try:
                hwm = self.store.check_and_update_clock_state(
                    device_fingerprint=current_fp,
                    is_subscription=is_sub,
                    now_utc=now_utc,
                    tolerance_sec=skew_sec,
                )
                if self._high_water_mark_utc is None or hwm > self._high_water_mark_utc:
                    self._high_water_mark_utc = hwm
                self._last_anchor_sync_at = now_utc
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
            high_water_mark_utc=self._high_water_mark_utc,
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

        # 3. Validate signature, hardware, version & clock state BEFORE persisting
        now_utc = self.clock_provider()
        is_sub = envelope.payload.license_type in ("subscription", "trial", "timed")
        skew_hours = (
            envelope.payload.max_clock_skew_hours
            if envelope.payload.max_clock_skew_hours is not None
            else 24
        )
        skew_sec = max(0, int(skew_hours)) * 3600

        # Evaluate signature, device & bounds first before updating anchors
        val_res = self.verifier.validate_license(
            envelope=envelope,
            current_hardware_fingerprint=current_fp,
            current_app_version=self.app_version,
            now_utc=now_utc,
            available_hardware_tiers=tiers,
            high_water_mark_utc=self._high_water_mark_utc,
        )
        if not val_res.is_valid:
            # Candidate is invalid: do NOT write to disk!
            return val_res

        # 4. Verify & update redundant clock anchors BEFORE persisting (fail closed on rollback)
        try:
            hwm = self.store.check_and_update_clock_state(
                device_fingerprint=current_fp,
                is_subscription=is_sub,
                now_utc=now_utc,
                tolerance_sec=skew_sec,
            )
            if self._high_water_mark_utc is None or hwm > self._high_water_mark_utc:
                self._high_water_mark_utc = hwm
        except ClockRollbackError as e:
            return ValidationResult(
                status=ValidationStatus.CLOCK_TAMPERED,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CLOCK_TAMPERED],
                detail=str(e),
            )
        except Exception as e:
            return ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=envelope,
                message_fa="خطا در بررسی و ذخیره وضعیت ساعت امنیتی لایسنس.",
                detail=str(e),
            )

        # Re-evaluate against persisted HWM so <24h clock rollback never revives expired licenses
        val_res = self.verifier.evaluate_validity_window(
            envelope,
            now_utc=now_utc,
            high_water_mark_utc=self._high_water_mark_utc,
        )
        if not val_res.is_valid:
            return val_res

        # 5. Atomically persist validated license
        try:
            self.store.save_license_bytes_atomic(candidate_bytes)
        except Exception as e:
            return ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=envelope,
                message_fa="خطا در ذخیره‌سازی فایل لایسنس در سیستم.",
                detail=str(e),
            )

        self._last_anchor_sync_at = now_utc
        self._last_result = val_res
        return val_res

    def export_device_request_file(self, target_path: str, device_label: str = "", store_name: str = "") -> Dict[str, Any]:
        """Export canonical .daqreq JSON file including live store_name and exact app_security_id."""
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
            app_security_id=self.get_app_security_id_display(),
        )
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(req_dict, f, ensure_ascii=False, indent=2)
        return req_dict

    def remove_license(self) -> bool:
        """Remove active license from disk and reset memory state."""
        ok = self.store.remove_license()
        self._last_result = None
        self._last_anchor_sync_at = None
        self._high_water_mark_utc = None
        return ok

    def is_feature_enabled_for_result(self, feature_id: str, res: Optional[ValidationResult]) -> bool:
        """Evaluate feature entitlement against an already-computed ValidationResult."""
        canonical_key = TAB_MODULE_TO_FEATURE.get(feature_id, feature_id)
        if not res or not res.is_valid:
            return False

        lic = res.license
        if not lic:
            return False

        features = lic.payload.features or {}
        if canonical_key in features:
            return bool(features[canonical_key])

        if canonical_key in OPTIONAL_DEFAULT_TRUE_FEATURES:
            return True

        if canonical_key in SUBFEATURE_PARENT_TAB:
            parent_tab = SUBFEATURE_PARENT_TAB[canonical_key]
            if parent_tab in features:
                return bool(features[parent_tab])
            return all(bool(features.get(t, False)) for t in CORE_TAB_FEATURES)

        return False

    def is_feature_enabled(self, feature_id: str) -> bool:
        """Check whether a tab module or granular sub-feature is authorized in the active license."""
        return self.is_feature_enabled_for_result(feature_id, self.check_license())

    def is_write_allowed(self) -> bool:
        """Return True if write operations are permitted (False if readonly grace period)."""
        if self._last_result is None:
            self.check_license()
        if not self._last_result or not self._last_result.is_valid:
            return False
        if self._last_result.in_grace_period and self._last_result.grace_mode == "readonly":
            return False
        return True

    def get_support_phone(self) -> str:
        """Return configured vendor support phone number."""
        return get_support_phone()

    def get_locked_module_message_fa(self, feature_id: str) -> str:
        """Return clean Persian guidance for a module locked by current license entitlements."""
        label = get_feature_label_fa(feature_id)
        phone = self.get_support_phone()
        return (
            f"بخش «{label}» در لایسنس فعال فعلی غیرفعال است.\n"
            f"جهت فعال‌سازی یا ارتقای لایسنس با پشتیبانی تماس بگیرید: {phone}"
        )

    def get_active_license(self) -> Optional[LicenseEnvelope]:
        """Return the verified active LicenseEnvelope, if valid."""
        if self._last_result and self._last_result.is_valid:
            return self._last_result.license
        return None
