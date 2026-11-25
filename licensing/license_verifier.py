# licensing/license_verifier.py
"""Strict cryptographic verification and schema validation for Daqiq licenses."""

import base64
import copy
import datetime
import json
import math
import re
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
    KeyIntegrityError,
    PublicKeyNotConfiguredError,
)
from .keys import KeyRegistry

MAX_LICENSE_FILE_BYTES = 65536  # 64 KiB
DOMAIN_PREFIX = b"DAQIQ-LICENSE-V1\n"

# Persian customer-friendly status messages (concise, natural end-user copy)
STATUS_MESSAGES_FA: Dict[ValidationStatus, str] = {
    ValidationStatus.VALID: "لایسنس نرم‌افزار معتبر و فعال است.",
    ValidationStatus.MISSING: "لایسنس فعالی روی این سیستم ثبت نشده است. برای فعال‌سازی، فایل لایسنس خود را بارگذاری کنید.",
    ValidationStatus.NOT_YET_VALID: "تاریخ شروع اعتبار لایسنس هنوز فرا نرسیده است. لطفاً تاریخ سیستم خود را بررسی کنید.",
    ValidationStatus.EXPIRED: "اعتبار این لایسنس به پایان رسیده است. لطفاً برای تمدید با پشتیبانی تماس بگیرید.",
    ValidationStatus.INVALID_SIGNATURE: "فایل لایسنس معتبر نیست یا با این نسخه همخوانی ندارد.",
    ValidationStatus.UNAUTHORIZED_DEVICE: "این لایسنس برای این سیستم صادر نشده است.",
    ValidationStatus.HARDWARE_MISMATCH: "این لایسنس با مشخصات سخت‌افزاری این سیستم مطابقت ندارد.",
    ValidationStatus.WRONG_PRODUCT: "این فایل لایسنس متعلق به نرم‌افزار دقیق نیست.",
    ValidationStatus.UNSUPPORTED_FORMAT: "قالب فایل لایسنس پشتیبانی نمی‌شود.",
    ValidationStatus.UNSUPPORTED_APP_VERSION: "این نسخه از نرم‌افزار با لایسنس انتخاب‌شده سازگار نیست.",
    ValidationStatus.VERSION_INCOMPATIBLE: "نسخه نرم‌افزار با محدوده مجاز لایسنس سازگار نیست.",
    ValidationStatus.INVALID_ENTITLEMENT: "دسترسی‌های تعریف‌شده در لایسنس معتبر نیستند.",
    ValidationStatus.CORRUPTED_LICENSE: "فایل لایسنس معتبر نیست یا خوانا نمی‌باشد. لطفاً فایل صحیح را انتخاب کنید.",
    ValidationStatus.HARDWARE_IDENTITY_UNAVAILABLE: "امکان دریافت شناسه سخت‌افزاری این سیستم وجود ندارد.",
    ValidationStatus.CLOCK_ROLLBACK: "ساعت و تاریخ سیستم عقب کشیده شده است. لطفاً زمان ویندوز را تنظیم کنید.",
    ValidationStatus.CLOCK_TAMPERED: "ساعت و تاریخ سیستم با زمان ثبت‌شده همخوانی ندارد. لطفاً زمان ویندوز را همگام‌سازی کنید.",
    ValidationStatus.GRACE_PERIOD: "اعتبار لایسنس به پایان رسیده و نرم‌افزار در دوره مهلت موقت قرار دارد.",
    ValidationStatus.TRIAL: "نسخه آزمایشی فعال است.",
    ValidationStatus.PUBLIC_KEY_NOT_CONFIGURED: "تنظیمات کلید امنیتی نرم‌افزار کامل نیست.",
    ValidationStatus.KEY_INTEGRITY_ERROR: "یکپارچگی امنیتی نرم‌افزار تأیید نشد.",
    ValidationStatus.UNTRUSTED_KEY: "فایل لایسنس با امضای معتبر این نسخه صادر نشده است.",
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


_BIDI_STRIP_RE = re.compile(r"[\u200c\u200d\u200e\u200f\ufeff\u202a-\u202e\u2066-\u2069]")
_DIGIT_TRANSLATE = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DATE_ONLY_RE = re.compile(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$")


def _extract_non_bool_int(val: Any) -> Optional[int]:
    """Return int if *val* is an integer (excluding bool), else None."""
    if isinstance(val, bool) or not isinstance(val, int):
        return None
    return val


def parse_iso8601_utc(dt_str: str, *, end_of_day_if_date_only: bool = False) -> datetime.datetime:
    """Parse UTC ISO-8601 string or date-only string to timezone-aware UTC datetime."""
    if not isinstance(dt_str, str):
        raise ValueError("تاریخ باید به صورت رشته معتبر باشد.")
    clean = _BIDI_STRIP_RE.sub("", dt_str).translate(_DIGIT_TRANSLATE).strip()
    if not clean:
        raise ValueError("رشته تاریخ خالی است.")

    m_date = _DATE_ONLY_RE.match(clean)
    if m_date:
        year, month, day = int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
        if end_of_day_if_date_only:
            return datetime.datetime(year, month, day, 23, 59, 59, tzinfo=datetime.timezone.utc)
        return datetime.datetime(year, month, day, 0, 0, 0, tzinfo=datetime.timezone.utc)

    if clean.endswith(("Z", "z")):
        clean = clean[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt


class LicenseVerifier:
    """Strict cryptographic and entitlement verifier for Daqiq offline licenses."""

    def __init__(
        self,
        key_registry: Optional[KeyRegistry] = None,
        public_key_bytes: Optional[bytes] = None,
    ):
        if public_key_bytes is not None:
            self.key_registry = KeyRegistry(initial_keys={"test-injected-key": public_key_bytes})
        else:
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
        env_ver = _extract_non_bool_int(doc.get("envelope_version"))
        if env_ver != 1:
            raise LicensingError(f"نسخه envelope_version نامعتبر است: {doc.get('envelope_version')}")

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
        if _extract_non_bool_int(p_raw.get("format_version")) != 1:
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

        lic_type = p_raw.get("license_type") or p_raw.get("type") or p_raw.get("plan")
        if lic_type is None and p_raw.get("perpetual") is True:
            lic_type = "perpetual"
        if lic_type not in ("perpetual", "subscription", "trial", "timed"):
            raise LicensingError(f"نوع لایسنس نامعتبر است: {lic_type}")

        validity_block = p_raw.get("validity") if isinstance(p_raw.get("validity"), dict) else {}
        issued_at = p_raw.get("issued_at") or validity_block.get("issued_at")
        not_before = (
            p_raw.get("not_before")
            or validity_block.get("not_before")
            or p_raw.get("valid_from")
            or validity_block.get("valid_from")
            or issued_at
        )
        expires_at = (
            p_raw.get("expires_at")
            or p_raw.get("expires_at_utc")
            or p_raw.get("valid_until")
            or p_raw.get("expiry_date")
            or validity_block.get("expires_at")
            or validity_block.get("expires_at_utc")
            or validity_block.get("valid_until")
            or validity_block.get("expiry_date")
        )
        duration_days_raw = (
            p_raw.get("duration_days")
            if "duration_days" in p_raw
            else validity_block.get("duration_days")
        )

        if not issued_at or not not_before:
            raise LicensingError("تاریخ‌های صدور و شروع اعتبار لایسنس ضروری هستند.")
        try:
            parse_iso8601_utc(issued_at)
            dt_nb = parse_iso8601_utc(not_before)
        except (ValueError, TypeError) as e:
            raise LicensingError(f"فرمت تاریخ صدور یا شروع اعتبار نامعتبر است: {e}") from e

        if not expires_at and duration_days_raw is not None:
            dur_days = _extract_non_bool_int(duration_days_raw)
            if dur_days is None or dur_days <= 0:
                raise LicensingError("مدت اعتبار (duration_days) نامعتبر است.")
            expires_at = (dt_nb + datetime.timedelta(days=dur_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Perpetual vs Subscription / Trial / Timed check (fail closed on missing or invalid expiry)
        if lic_type == "perpetual" and expires_at is not None:
            raise LicensingError("لایسنس دائمی نباید تاریخ انقضا (expires_at) داشته باشد.")
        if lic_type in ("subscription", "trial", "timed"):
            if not expires_at:
                raise LicensingError("لایسنس اشتراکی یا آزمایشی باید دارای تاریخ انقضا (expires_at) باشد.")
            try:
                dt_exp = parse_iso8601_utc(expires_at, end_of_day_if_date_only=True)
            except (ValueError, TypeError) as e:
                raise LicensingError(f"فرمت تاریخ انقضای لایسنس نامعتبر است: {e}") from e
            if dt_exp <= dt_nb:
                raise LicensingError("تاریخ انقضای لایسنس باید بعد از تاریخ شروع آن باشد.")

        max_dev = _extract_non_bool_int(p_raw.get("max_devices"))
        if max_dev is None or max_dev < 1:
            raise LicensingError("تعداد دستگاه‌های مجاز (max_devices) باید عدد صحیح بزرگتر از صفر باشد.")

        raw_grace = p_raw.get("grace_period_days")
        if raw_grace is not None:
            grace_val = _extract_non_bool_int(raw_grace)
            if grace_val is None or grace_val < 0:
                raise LicensingError("مقدار دوره مهلت (grace_period_days) نامعتبر است.")

        raw_grace_mode = p_raw.get("grace_mode")
        if raw_grace_mode is not None and raw_grace_mode not in ("readonly", "full"):
            raise LicensingError(f"مقدار grace_mode نامعتبر است: {raw_grace_mode}")

        raw_warn = p_raw.get("expiry_warning_days")
        if raw_warn is not None:
            warn_val = _extract_non_bool_int(raw_warn)
            if warn_val is None or warn_val < 0:
                raise LicensingError("مقدار هشدار انقضا (expiry_warning_days) نامعتبر است.")

        raw_skew = p_raw.get("max_clock_skew_hours")
        if raw_skew is not None:
            skew_val = _extract_non_bool_int(raw_skew)
            if skew_val is None or skew_val < 0:
                raise LicensingError("مقدار انحراف ساعت مجاز (max_clock_skew_hours) نامعتبر است.")

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
            raw_payload_dict=copy.deepcopy(p_raw),
        )

        return LicenseEnvelope(
            envelope_version=env_ver,
            algorithm=algo,
            key_id=key_id,
            payload=payload,
            signature=sig_b64,
        )

    def verify_cryptographic_signature(self, envelope: LicenseEnvelope) -> None:
        """Verify the Ed25519 digital signature of the envelope against trusted keyring."""
        try:
            sig_bytes = base64.b64decode(envelope.signature, validate=True)
        except Exception as e:
            raise CryptoVerificationError(f"رمزگشایی امضای دیجیتال ناموفق بود: {e}") from e

        if len(sig_bytes) != 64:
            raise CryptoVerificationError(f"طول امضای دیجیتال باید ۶۴ بایت باشد؛ دریافت شد: {len(sig_bytes)}")

        signed_dict = (
            envelope.payload.raw_payload_dict
            if getattr(envelope.payload, "raw_payload_dict", None) is not None
            else envelope.payload.to_dict()
        )
        canonical_payload_bytes = canonicalize_payload(signed_dict)
        data_to_verify = DOMAIN_PREFIX + canonical_payload_bytes

        # 1. First try matching key_id if present in registry
        matched_pub_key = self.key_registry.get_public_key(envelope.key_id)
        if matched_pub_key is not None:
            try:
                matched_pub_key.verify(sig_bytes, data_to_verify)
                return
            except InvalidSignature:
                pass  # Fall through to check other trusted keys in keyring

        # 2. If key_id is omitted, not found, or failed, try all other registered keys
        all_keys = self.key_registry.get_all_public_keys()
        if not all_keys:
            raise PublicKeyNotConfiguredError("هیچ کلید عمومی معتبری در سامانه تنظیم نشده است.")

        for kid, alt_key in all_keys.items():
            if alt_key is not matched_pub_key:
                try:
                    alt_key.verify(sig_bytes, data_to_verify)
                    return
                except InvalidSignature:
                    continue

        raise CryptoVerificationError("امضای دیجیتال لایسنس با هیچ‌یک از کلیدهای عمومی معتبر همخوانی ندارد.")

    def validate_license(
        self,
        envelope: LicenseEnvelope,
        current_hardware_fingerprint: str,
        current_app_version: str = "4.9.10",
        now_utc: Optional[datetime.datetime] = None,
        available_hardware_tiers: Optional[Dict[str, str]] = None,
        high_water_mark_utc: Optional[datetime.datetime] = None,
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
        except PublicKeyNotConfiguredError as e:
            return ValidationResult(
                status=ValidationStatus.PUBLIC_KEY_NOT_CONFIGURED,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.PUBLIC_KEY_NOT_CONFIGURED],
                detail=str(e),
            )
        except KeyIntegrityError as e:
            return ValidationResult(
                status=ValidationStatus.KEY_INTEGRITY_ERROR,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.KEY_INTEGRITY_ERROR],
                detail=str(e),
            )
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

        # 5. Date boundaries & grace period check (single fail-closed evaluator)
        return self.evaluate_validity_window(
            envelope,
            now_utc=now_utc,
            high_water_mark_utc=high_water_mark_utc,
        )

    def evaluate_validity_window(
        self,
        envelope: LicenseEnvelope,
        now_utc: Optional[datetime.datetime] = None,
        high_water_mark_utc: Optional[datetime.datetime] = None,
    ) -> ValidationResult:
        """Evaluate issued_at, not_before, expires_at, and explicit grace strictly (fail-closed)."""
        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=datetime.timezone.utc)
        else:
            now_utc = now_utc.astimezone(datetime.timezone.utc)

        effective_now = now_utc
        if high_water_mark_utc is not None:
            hwm = (
                high_water_mark_utc.replace(tzinfo=datetime.timezone.utc)
                if high_water_mark_utc.tzinfo is None
                else high_water_mark_utc.astimezone(datetime.timezone.utc)
            )
            if hwm > effective_now:
                effective_now = hwm

        try:
            dt_issued = parse_iso8601_utc(envelope.payload.issued_at)
            dt_not_before = parse_iso8601_utc(envelope.payload.not_before)
        except (ValueError, TypeError) as e:
            return ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                detail=f"تاریخ صدور یا شروع اعتبار لایسنس نامعتبر است: {e}",
            )

        raw_skew = envelope.payload.max_clock_skew_hours
        if raw_skew is None:
            skew_hours = 24
        else:
            skew_int = _extract_non_bool_int(raw_skew)
            if skew_int is None or skew_int < 0:
                return ValidationResult(
                    status=ValidationStatus.CORRUPTED_LICENSE,
                    is_valid=False,
                    license=envelope,
                    message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                    detail="مقدار انحراف ساعت مجاز نامعتبر است.",
                )
            skew_hours = skew_int

        if now_utc < dt_not_before:
            return ValidationResult(
                status=ValidationStatus.NOT_YET_VALID,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.NOT_YET_VALID],
                detail=f"تاریخ شروع: {envelope.payload.not_before}، زمان جاری: {now_utc.isoformat()}",
            )

        anchor_floor = min(dt_issued, dt_not_before)
        is_sub_or_trial = envelope.payload.license_type in ("subscription", "trial", "timed")
        if is_sub_or_trial and now_utc < (anchor_floor - datetime.timedelta(hours=skew_hours)):
            return ValidationResult(
                status=ValidationStatus.CLOCK_TAMPERED,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CLOCK_TAMPERED],
                detail=f"زمان سیستم ({now_utc.isoformat()}) عقب‌تر از تاریخ شروع مجاز است.",
            )

        is_trial = envelope.payload.license_type == "trial"

        if is_sub_or_trial:
            if not envelope.payload.expires_at:
                return ValidationResult(
                    status=ValidationStatus.CORRUPTED_LICENSE,
                    is_valid=False,
                    license=envelope,
                    message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                    detail="لایسنس زمان‌دار یا دوره آزمایشی بدون تاریخ انقضا معتبر نیست.",
                )
            try:
                dt_expires = parse_iso8601_utc(
                    envelope.payload.expires_at,
                    end_of_day_if_date_only=True,
                )
            except (ValueError, TypeError) as e:
                return ValidationResult(
                    status=ValidationStatus.CORRUPTED_LICENSE,
                    is_valid=False,
                    license=envelope,
                    message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                    detail=f"تاریخ انقضای لایسنس نامعتبر است: {e}",
                )

            if dt_expires <= dt_not_before:
                return ValidationResult(
                    status=ValidationStatus.EXPIRED,
                    is_valid=False,
                    license=envelope,
                    message_fa=STATUS_MESSAGES_FA[ValidationStatus.EXPIRED],
                    detail="بازه زمانی اعتبار لایسنس معتبر نیست.",
                    days_remaining=0,
                    is_trial=is_trial,
                )

            raw_grace = envelope.payload.grace_period_days
            if raw_grace is None:
                grace_days = 0
            else:
                grace_int = _extract_non_bool_int(raw_grace)
                if grace_int is None or grace_int < 0:
                    return ValidationResult(
                        status=ValidationStatus.CORRUPTED_LICENSE,
                        is_valid=False,
                        license=envelope,
                        message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                        detail="مقدار دوره مهلت لایسنس نامعتبر است.",
                    )
                grace_days = grace_int

            grace_mode = envelope.payload.grace_mode or "readonly"
            if grace_mode not in ("readonly", "full"):
                grace_mode = "readonly"

            days_remaining = (dt_expires - effective_now).days
            grace_deadline = dt_expires + datetime.timedelta(days=grace_days)

            if effective_now >= dt_expires:
                if grace_days > 0 and effective_now < grace_deadline:
                    rem_seconds = max(0.0, (grace_deadline - effective_now).total_seconds())
                    grace_days_remaining = max(1, math.ceil(rem_seconds / 86400.0))
                    mode_fa = "فقط خواندنی" if grace_mode == "readonly" else "دسترسی کامل"
                    return ValidationResult(
                        status=ValidationStatus.GRACE_PERIOD,
                        is_valid=True,
                        license=envelope,
                        message_fa=(
                            f"اعتبار لایسنس به پایان رسیده و {grace_days_remaining} روز از دوره مهلت "
                            f"({mode_fa}) باقی مانده است."
                        ),
                        detail=f"انقضا: {envelope.payload.expires_at}، مهلت تا: {grace_deadline.isoformat()} ({grace_mode})",
                        in_grace_period=True,
                        grace_mode=grace_mode,
                        grace_days_remaining=grace_days_remaining,
                        days_remaining=0,
                        is_trial=is_trial,
                    )
                return ValidationResult(
                    status=ValidationStatus.EXPIRED,
                    is_valid=False,
                    license=envelope,
                    message_fa=STATUS_MESSAGES_FA[ValidationStatus.EXPIRED],
                    detail=f"تاریخ انقضا: {envelope.payload.expires_at}، زمان جاری: {effective_now.isoformat()}",
                    days_remaining=days_remaining,
                    is_trial=is_trial,
                )

            warning_window = (
                envelope.payload.expiry_warning_days
                if envelope.payload.expiry_warning_days is not None
                else 14
            )
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

        if envelope.payload.license_type != "perpetual":
            return ValidationResult(
                status=ValidationStatus.CORRUPTED_LICENSE,
                is_valid=False,
                license=envelope,
                message_fa=STATUS_MESSAGES_FA[ValidationStatus.CORRUPTED_LICENSE],
                detail=f"نوع لایسنس ناشناخته است: {envelope.payload.license_type}",
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
