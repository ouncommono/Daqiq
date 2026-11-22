# licensing/license_verifier.py
"""Strict cryptographic verification and schema validation for Daqiq licenses."""

import base64
import datetime
import json
import unicodedata
from typing import Any, Dict, List, Optional, Tuple, Set
from packaging import version as pkg_version
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

from .license_models import (
    CustomerInfo,
    LicensePayload,
    LicenseEnvelope,
    ValidationStatus,
    ValidationResult,
    LicensingError,
    CryptoVerificationError,
)
from .keys import KeyRegistry

MAX_LICENSE_FILE_BYTES = 65536  # 64 KiB
DOMAIN_PREFIX = b"DAQIQ-LICENSE-V1\n"

# Persian customer-friendly status messages
STATUS_MESSAGES_FA: Dict[ValidationStatus, str] = {
    ValidationStatus.VALID: "لایسنس نرم‌افزار معتبر است.",
    ValidationStatus.MISSING: "فایل لایسنس یافت نشد. لطفاً فایل لایسنس (.daqlic) را وارد کنید.",
    ValidationStatus.NOT_YET_VALID: "تاریخ شروع اعتبار لایسنس هنوز فرا نرسیده است. ساعت و تاریخ سیستم خود را بررسی کنید.",
    ValidationStatus.EXPIRED: "اعتبار اشتراک لایسنس به پایان رسیده است. لطفاً جهت تمدید با پشتیبانی تماس بگیرید.",
    ValidationStatus.INVALID_SIGNATURE: "امضای دیجیتال لایسنس نامعتبر است یا محتوای فایل دستکاری شده است.",
    ValidationStatus.UNAUTHORIZED_DEVICE: "این لایسنس برای سخت‌افزار این رایانه صادر نشده است.",
    ValidationStatus.HARDWARE_MISMATCH: "شناسه سخت‌افزاری دستگاه با شناسه‌های مجاز در لایسنس همخوانی ندارد.",
    ValidationStatus.WRONG_PRODUCT: "این فایل لایسنس متعلق به این نرم‌افزار نیست.",
    ValidationStatus.UNSUPPORTED_FORMAT: "فرمت ساختاری فایل لایسنس پشتیبانی نمی‌شود.",
    ValidationStatus.UNSUPPORTED_APP_VERSION: "این نسخه از برنامه با لایسنس فعال سازگار نیست (نیاز به ارتقا یا تمدید لایسنس).",
    ValidationStatus.VERSION_INCOMPATIBLE: "نسخه نرم‌افزار با محدوده مجاز لایسنس سازگار نیست.",
    ValidationStatus.INVALID_ENTITLEMENT: "دسترسی‌های تعریف‌شده در لایسنس نامعتبر هستند.",
    ValidationStatus.CORRUPTED_LICENSE: "فایل لایسنس خوانا نیست یا ساختار آن آسیب دیده است.",
    ValidationStatus.HARDWARE_IDENTITY_UNAVAILABLE: "شناسه سخت‌افزاری دستگاه قابل دسترسی نیست.",
    ValidationStatus.CLOCK_ROLLBACK: "عقب کشیدن ساعت سیستم شناسایی شد. لطفاً ساعت و تاریخ ویندوز را همگام‌سازی کنید.",
    ValidationStatus.CLOCK_TAMPERED: "دستکاری یا عقب کشیدن ساعت سیستم شناسایی شد.",
    ValidationStatus.GRACE_PERIOD: "لایسنس در دوره مهلت موقت (Grace Period) قرار دارد.",
    ValidationStatus.TRIAL: "نسخه آزمایشی فعال است.",
}


def _reject_duplicate_keys(pairs: List[Tuple[Any, Any]]) -> Dict[Any, Any]:
    """JSON object_pairs_hook that raises ValueError on duplicate keys."""
    res = {}
    for key, value in pairs:
        if key in res:
            raise ValueError(f"کلید تکراری در فایل لایسنس مجاز نیست: {key}")
        res[key] = value
    return res


def _reject_constant(c: str) -> None:
    """JSON parse_constant hook rejecting NaN, Infinity, -Infinity."""
    raise ValueError(f"مقدار غیراستاندارد در لایسنس مجاز نیست: {c}")


def _assert_no_floats(obj: Any, path: str = "payload") -> None:
    """Recursively ensure no float values exist in the payload."""
    if isinstance(obj, float):
        raise ValueError(f"مقدار اعشاری (float) در لایسنس مجاز نیست: {path}")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _assert_no_floats(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _assert_no_floats(item, f"{path}[{i}]")


def normalize_value_nfc(val: Any) -> Any:
    """Recursively normalize all strings and dictionary keys to Unicode NFC."""
    if isinstance(val, str):
        return unicodedata.normalize("NFC", val)
    if isinstance(val, dict):
        return {
            unicodedata.normalize("NFC", str(k)): normalize_value_nfc(v)
            for k, v in val.items()
        }
    if isinstance(val, list):
        return [normalize_value_nfc(item) for item in val]
    return val


def canonicalize_payload(payload_dict: Dict[str, Any]) -> bytes:
    """Serialize normalized payload dictionary to canonical UTF-8 bytes."""
    _assert_no_floats(payload_dict)
    normalized = normalize_value_nfc(payload_dict)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def parse_iso8601_utc(dt_str: str) -> datetime.datetime:
    """Parse UTC ISO-8601 string (e.g. 2026-11-22T00:00:00Z) to timezone-aware datetime."""
    clean = dt_str.strip()
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt


class LicenseVerifier:
    """Strict cryptographic and entitlement verifier for Daqiq offline licenses."""

    def __init__(self, key_registry: Optional[KeyRegistry] = None):
        self.key_registry = key_registry or KeyRegistry()

    def parse_envelope_from_bytes(self, raw_bytes: bytes) -> LicenseEnvelope:
        """Parse raw bytes or compact base64 token into a validated LicenseEnvelope."""
        if len(raw_bytes) > MAX_LICENSE_FILE_BYTES:
            raise LicensingError(
                f"حجم فایل لایسنس ({len(raw_bytes)} بایت) بیش از حد مجاز (۶۴ کیلوبایت) است."
            )
        try:
            text = raw_bytes.decode("utf-8-sig" if raw_bytes.startswith(b"\xef\xbb\xbf") else "utf-8").strip()
        except UnicodeDecodeError as e:
            raise LicensingError(f"فایل لایسنس با استاندارد متنی UTF-8 سازگار نیست: {e}") from e

        # Check if text is a compact base64-encoded token of JSON
        if not text.startswith("{") and len(text) > 20:
            try:
                decoded_text = base64.b64decode(text.encode("ascii")).decode("utf-8").strip()
                if decoded_text.startswith("{"):
                    text = decoded_text
            except Exception:
                pass

        try:
            doc = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
        except Exception as e:
            raise LicensingError(f"خطا در خواندن ساختار JSON فایل لایسنس: {e}") from e

        if not isinstance(doc, dict):
            raise LicensingError("ساختار لایسنس باید یک شیء JSON معتبر باشد.")

        # Envelope fields
        env_ver = doc.get("envelope_version")
        if env_ver != 1:
            raise LicensingError(f"نسخه envelope_version نامعتبر است: {env_ver}")

        algo = doc.get("algorithm")
        if algo != "Ed25519":
            raise LicensingError(f"الگوریتم رمزنگاری نامعتبر است: {algo}")

        key_id = doc.get("key_id")
        if not key_id or not isinstance(key_id, str):
            raise LicensingError("شناسه کلید key_id نامعتبر است.")

        sig_b64 = doc.get("signature")
        if not sig_b64 or not isinstance(sig_b64, str):
            raise LicensingError("امضای دیجیتال signature نامعتبر است.")

        p_raw = doc.get("payload")
        if not isinstance(p_raw, dict):
            raise LicensingError("بخش payload لایسنس معتبر نیست.")

        try:
            _assert_no_floats(p_raw)
        except ValueError as e:
            raise LicensingError(str(e)) from e

        # Validate payload fields
        if p_raw.get("format_version") != 1:
            raise LicensingError("نسخه format_version در payload باید ۱ باشد.")
        if p_raw.get("product_id") != "daqiq.desktop":
            raise LicensingError(f"شناسه محصول نامعتبر است: {p_raw.get('product_id')}")
        if p_raw.get("key_id") != key_id:
            raise LicensingError("شناسه کلید در envelope و payload همخوانی ندارند.")

        lic_id = p_raw.get("license_id")
        if not lic_id or not isinstance(lic_id, str):
            raise LicensingError("شناسه لایسنس license_id نامعتبر است.")

        cust_raw = p_raw.get("customer") or {}
        if not isinstance(cust_raw, dict) or not cust_raw.get("name"):
            raise LicensingError("مشخصات نام مشتری در لایسنس یافت نشد.")
        cust = CustomerInfo(
            name=str(cust_raw["name"]),
            organization=cust_raw.get("organization"),
            contact=cust_raw.get("contact"),
        )

        lic_type = p_raw.get("license_type")
        if lic_type not in ("perpetual", "subscription", "trial"):
            raise LicensingError(f"نوع لایسنس نامعتبر است: {lic_type}")

        issued_at = p_raw.get("issued_at")
        not_before = p_raw.get("not_before")
        expires_at = p_raw.get("expires_at")

        if not issued_at or not not_before:
            raise LicensingError("تاریخ‌های صدور و شروع اعتبار لایسنس ضروری هستند.")

        # Perpetual vs Subscription / Trial check
        if lic_type == "perpetual" and expires_at is not None:
            raise LicensingError("لایسنس دائمی نباید تاریخ انقضا (expires_at) داشته باشد.")
        if lic_type in ("subscription", "trial"):
            if not expires_at:
                raise LicensingError("لایسنس اشتراکی یا آزمایشی باید دارای تاریخ انقضا (expires_at) باشد.")
            dt_nb = parse_iso8601_utc(not_before)
            dt_exp = parse_iso8601_utc(expires_at)
            if dt_exp <= dt_nb:
                raise LicensingError("تاریخ انقضای لایسنس باید بعد از تاریخ شروع آن باشد.")

        max_dev = p_raw.get("max_devices")
        if not isinstance(max_dev, int) or max_dev < 1:
            raise LicensingError("تعداد دستگاه‌های مجاز (max_devices) باید عدد صحیح بزرگتر از صفر باشد.")

        fps = p_raw.get("device_fingerprints")
        if not isinstance(fps, list) or len(fps) == 0:
            raise LicensingError("لیست شناسه‌های دستگاه مجاز (device_fingerprints) خالی است.")
        if len(fps) != len(set(fps)):
            raise LicensingError("شناسه‌های دستگاه تکراری در لایسنس مجاز نیست.")
        if len(fps) > max_dev:
            raise LicensingError("تعداد شناسه‌های دستگاه بیش از سقف مجاز (max_devices) است.")

        features_raw = p_raw.get("features")
        if not isinstance(features_raw, dict):
            raise LicensingError("ساختار ماژول‌ها و دسترسی‌ها (features) نامعتبر است.")
        features: Dict[str, bool] = {}
        for fk, fv in features_raw.items():
            if not isinstance(fv, bool):
                raise LicensingError(f"مقدار دسترسی ماژول {fk} باید بولی (True/False) باشد.")
            features[str(fk)] = fv

        # Known standard keys
        standard_keys = {
            "customer",
            "device_fingerprints",
            "expires_at",
            "features",
            "format_version",
            "issued_at",
            "key_id",
            "license_id",
            "license_type",
            "max_app_version",
            "max_devices",
            "min_app_version",
            "not_before",
            "product_id",
            "match_policy",
            "grace_period_days",
            "grace_mode",
            "expiry_warning_days",
            "max_clock_skew_hours",
            "quotas",
            "metadata",
        }
        extra_fields = {k: v for k, v in p_raw.items() if k not in standard_keys}

        payload = LicensePayload(
            format_version=p_raw["format_version"],
            product_id=p_raw["product_id"],
            license_id=lic_id,
            key_id=key_id,
            customer=cust,
            license_type=lic_type,
            issued_at=issued_at,
            not_before=not_before,
            expires_at=expires_at,
            max_devices=max_dev,
            device_fingerprints=fps,
            features=features,
            min_app_version=p_raw.get("min_app_version"),
            max_app_version=p_raw.get("max_app_version"),
            match_policy=p_raw.get("match_policy"),
            grace_period_days=p_raw.get("grace_period_days"),
            grace_mode=p_raw.get("grace_mode"),
            expiry_warning_days=p_raw.get("expiry_warning_days"),
            max_clock_skew_hours=p_raw.get("max_clock_skew_hours"),
            quotas=p_raw.get("quotas"),
            metadata=p_raw.get("metadata"),
            extra_fields=extra_fields,
        )

        return LicenseEnvelope(
            envelope_version=env_ver,
            algorithm=algo,
            key_id=key_id,
            payload=payload,
            signature=sig_b64,
        )

    def verify_cryptographic_signature(self, envelope: LicenseEnvelope) -> None:
        """Verify the Ed25519 digital signature of the envelope."""
        pub_key = self.key_registry.get_public_key(envelope.key_id)
        if not pub_key:
            raise CryptoVerificationError(
                f"کلید عمومی معتبر برای شناسه {envelope.key_id} در سامانه یافت نشد."
            )

        try:
            sig_bytes = base64.b64decode(envelope.signature, validate=True)
        except Exception as e:
            raise CryptoVerificationError(f"رمزگشایی امضای دیجیتال ناموفق بود: {e}") from e

        if len(sig_bytes) != 64:
            raise CryptoVerificationError(f"طول امضای دیجیتال باید ۶۴ بایت باشد؛ دریافت شد: {len(sig_bytes)}")

        canonical_payload_bytes = canonicalize_payload(envelope.payload.to_dict())
        data_to_verify = DOMAIN_PREFIX + canonical_payload_bytes

        try:
            pub_key.verify(sig_bytes, data_to_verify)
        except InvalidSignature as e:
            raise CryptoVerificationError("امضای دیجیتال لایسنس نامعتبر است.") from e

    def validate_license(
        self,
        envelope: LicenseEnvelope,
        current_hardware_fingerprint: str,
        current_app_version: str = "4.9.1",
        now_utc: Optional[datetime.datetime] = None,
        available_hardware_tiers: Optional[Dict[str, str]] = None,
    ) -> ValidationResult:
        """Complete evaluation of envelope, hardware match, version and date boundaries."""
        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)

        # 1. Product check
        if envelope.payload.product_id != "daqiq.desktop":
            return ValidationResult(
                status=ValidationStatus.WRONG_PRODUCT,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.WRONG_PRODUCT],
                detail=f"Expected 'daqiq.desktop', got '{envelope.payload.product_id}'",
            )

        # 2. Cryptographic signature check
        try:
            self.verify_cryptographic_signature(envelope)
        except CryptoVerificationError as e:
            return ValidationResult(
                status=ValidationStatus.INVALID_SIGNATURE,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.INVALID_SIGNATURE],
                detail=str(e),
            )

        # 3. Hardware node-lock check with match policy
        norm_current_fp = unicodedata.normalize("NFC", current_hardware_fingerprint).strip().lower()
        authorized_fps: Set[str] = {
            unicodedata.normalize("NFC", fp).strip().lower()
            for fp in envelope.payload.device_fingerprints
        }

        match_policy = (envelope.payload.match_policy or "standard").lower()
        hardware_matched = False

        if norm_current_fp in authorized_fps:
            hardware_matched = True
        elif match_policy in ("standard", "relaxed") and available_hardware_tiers:
            # Check secondary tiers
            for tier_name, tier_fp in available_hardware_tiers.items():
                if match_policy == "standard" and tier_name not in ("tier1", "tier2", "tier3"):
                    continue
                if unicodedata.normalize("NFC", tier_fp).strip().lower() in authorized_fps:
                    hardware_matched = True
                    break

        if not hardware_matched:
            return ValidationResult(
                status=ValidationStatus.UNAUTHORIZED_DEVICE,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.UNAUTHORIZED_DEVICE],
                detail="شناسه دستگاه با فهرست سخت‌افزارهای مجاز در لایسنس همخوانی ندارد.",
            )

        # 4. App version bounds check
        try:
            curr_v = pkg_version.parse(current_app_version)
            if envelope.payload.min_app_version:
                min_v = pkg_version.parse(envelope.payload.min_app_version)
                if curr_v < min_v:
                    return ValidationResult(
                        status=ValidationStatus.UNSUPPORTED_APP_VERSION,
                        is_valid=False,
                        license=envelope,
                        message_fa=STATUS_MESSAGES_FA[ValidationStatus.UNSUPPORTED_APP_VERSION],
                        detail=f"نسخه برنامه ({current_app_version}) کمتر از حداقل نسخه مجاز ({envelope.payload.min_app_version}) است.",
                    )
            if envelope.payload.max_app_version:
                max_v = pkg_version.parse(envelope.payload.max_app_version)
                if curr_v > max_v:
                    return ValidationResult(
                        status=ValidationStatus.UNSUPPORTED_APP_VERSION,
                        is_valid=False,
                        license=envelope,
                        message_fa=STATUS_MESSAGES_FA[ValidationStatus.UNSUPPORTED_APP_VERSION],
                        detail=f"نسخه برنامه ({current_app_version}) بیشتر از حداکثر نسخه مجاز ({envelope.payload.max_app_version}) است.",
                    )
        except Exception as e:
            return ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                detail=f"خطا در بررسی نسخه برنامه: {e}",
            )

        # 5. Date boundaries check
        dt_not_before = parse_iso8601_utc(envelope.payload.not_before)
        if now_utc < dt_not_before:
            return ValidationResult(
                status=ValidationStatus.NOT_YET_VALID,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.NOT_YET_VALID],
                detail=f"تاریخ شروع: {envelope.payload.not_before}، زمان جاری: {now_utc.isoformat()}",
            )

        is_trial = envelope.payload.license_type == "trial"

        if envelope.payload.license_type in ("subscription", "trial"):
            if not envelope.payload.expires_at:
                return ValidationResult(
                    status=ValidationStatus.CORRUPTED_LICENSE,
                    is_valid=False,
                    license=envelope,
                    message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                    detail="اشتراک یا دوره آزمایشی بدون تاریخ انقضا معتبر نیست.",
                )
            dt_expires = parse_iso8601_utc(envelope.payload.expires_at)
            days_remaining = (dt_expires - now_utc).days

            # Grace period logic
            grace_days = envelope.payload.grace_period_days or 0
            grace_mode = envelope.payload.grace_mode or "readonly"
            grace_deadline = dt_expires + datetime.timedelta(days=grace_days)

            if now_utc >= dt_expires:
                if grace_days > 0 and now_utc < grace_deadline:
                    # Within Grace Period
                    return ValidationResult(
                        status=ValidationStatus.GRACE_PERIOD,
                        is_valid=True,
                        license=envelope,
                        message_fa="اعتبار لایسنس به پایان رسیده و در دوره مهلت (Grace Period) قرار دارد.",
                        detail=f"انقضا: {envelope.payload.expires_at}، مهلت تا: {grace_deadline.isoformat()} ({grace_mode})",
                        in_grace_period=True,
                        grace_mode=grace_mode,
                        days_remaining=0,
                        is_trial=is_trial,
                    )
                else:
                    return ValidationResult(
                        status=ValidationStatus.EXPIRED,
                        is_valid=False,
                        license=envelope,
                        message_fa=STATUS_MESSAGES_FA[ValidationStatus.EXPIRED],
                        detail=f"تاریخ انقضا: {envelope.payload.expires_at}، زمان جاری: {now_utc.isoformat()}",
                        days_remaining=days_remaining,
                        is_trial=is_trial,
                    )

            # Active subscription/trial
            warning_window = envelope.payload.expiry_warning_days if envelope.payload.expiry_warning_days is not None else 14
            msg = "نسخه آزمایشی فعال است." if is_trial else STATUS_MESSAGES_FA[ValidationStatus.VALID]
            if 0 <= days_remaining <= warning_window:
                msg += f" (توجه: {days_remaining} روز تا پایان اعتبار باقیمانده است)"

            return ValidationResult(
                status=ValidationStatus.TRIAL if is_trial else ValidationStatus.VALID,
                is_valid=True,
                license=envelope,
                message_fa=msg,
                detail="",
                days_remaining=days_remaining,
                is_trial=is_trial,
            )

        return ValidationResult(
            status=ValidationStatus.VALID,
            is_valid=True,
            license=envelope,
            message_fa=STATUS_MESSAGES_FA[ValidationStatus.VALID],
            detail="",
            days_remaining=None,
            is_trial=False,
        )
