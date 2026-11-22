# licensing/license_models.py
"""Immutable data models, statuses, and exceptions for Daqiq offline licensing.

Compatible with Daqiq Desktop and Daqiq-License-Generator protocol.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Any


class LicensingError(Exception):
    """Base exception for all licensing errors."""
    pass


class CryptoVerificationError(LicensingError):
    """Raised when signature verification or cryptographic checks fail."""
    pass


class HardwareIdentityUnavailableError(LicensingError):
    """Raised when stable motherboard/SMBIOS identity cannot be acquired."""
    pass


class ClockRollbackError(LicensingError):
    """Raised when system clock rollback or manipulation is detected."""
    pass


class StorageError(LicensingError):
    """Raised when license storage read/write operations fail."""
    pass


class ValidationStatus(str, Enum):
    """Validation outcome status codes covering all licensing states."""
    VALID = "VALID"
    MISSING = "MISSING"
    NOT_YET_VALID = "NOT_YET_VALID"
    EXPIRED = "EXPIRED"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    UNAUTHORIZED_DEVICE = "UNAUTHORIZED_DEVICE"
    HARDWARE_MISMATCH = "HARDWARE_MISMATCH"
    WRONG_PRODUCT = "WRONG_PRODUCT"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    UNSUPPORTED_APP_VERSION = "UNSUPPORTED_APP_VERSION"
    VERSION_INCOMPATIBLE = "VERSION_INCOMPATIBLE"
    INVALID_ENTITLEMENT = "INVALID_ENTITLEMENT"
    CORRUPTED_LICENSE = "CORRUPTED_LICENSE"
    HARDWARE_IDENTITY_UNAVAILABLE = "HARDWARE_IDENTITY_UNAVAILABLE"
    CLOCK_ROLLBACK = "CLOCK_ROLLBACK"
    CLOCK_TAMPERED = "CLOCK_TAMPERED"
    GRACE_PERIOD = "GRACE_PERIOD"
    TRIAL = "TRIAL"


@dataclass(frozen=True)
class CustomerInfo:
    """Customer identity associated with the license."""
    name: str
    organization: Optional[str] = None
    contact: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contact": self.contact,
            "name": self.name,
            "organization": self.organization,
        }


@dataclass(frozen=True)
class LicensePayload:
    """Inner payload signed by the vendor Ed25519 secret signing key."""
    format_version: int
    product_id: str
    license_id: str
    key_id: str
    customer: CustomerInfo
    license_type: str  # "perpetual", "subscription", or "trial"
    issued_at: str     # UTC ISO-8601
    not_before: str    # UTC ISO-8601
    expires_at: Optional[str]  # UTC ISO-8601 or None for perpetual
    max_devices: int
    device_fingerprints: List[str]
    features: Dict[str, bool]
    min_app_version: Optional[str] = None
    max_app_version: Optional[str] = None
    match_policy: Optional[str] = None  # "strict", "standard", "relaxed"
    grace_period_days: Optional[int] = None
    grace_mode: Optional[str] = None    # "readonly" or "full"
    expiry_warning_days: Optional[int] = None
    max_clock_skew_hours: Optional[int] = None
    quotas: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    extra_fields: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "customer": self.customer.to_dict(),
            "device_fingerprints": list(self.device_fingerprints),
            "expires_at": self.expires_at,
            "features": dict(self.features),
            "format_version": self.format_version,
            "issued_at": self.issued_at,
            "key_id": self.key_id,
            "license_id": self.license_id,
            "license_type": self.license_type,
            "max_app_version": self.max_app_version,
            "max_devices": self.max_devices,
            "min_app_version": self.min_app_version,
            "not_before": self.not_before,
            "product_id": self.product_id,
        }
        if self.match_policy is not None:
            d["match_policy"] = self.match_policy
        if self.grace_period_days is not None:
            d["grace_period_days"] = self.grace_period_days
        if self.grace_mode is not None:
            d["grace_mode"] = self.grace_mode
        if self.expiry_warning_days is not None:
            d["expiry_warning_days"] = self.expiry_warning_days
        if self.max_clock_skew_hours is not None:
            d["max_clock_skew_hours"] = self.max_clock_skew_hours
        if self.quotas is not None:
            d["quotas"] = self.quotas
        if self.metadata is not None:
            d["metadata"] = self.metadata
        for k, v in self.extra_fields.items():
            if k not in d:
                d[k] = v
        return d


@dataclass(frozen=True)
class LicenseEnvelope:
    """Outer cryptographic envelope containing payload and Ed25519 signature."""
    envelope_version: int
    algorithm: str
    key_id: str
    payload: LicensePayload
    signature: str  # Base64 standard RFC 4648

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope_version": self.envelope_version,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "payload": self.payload.to_dict(),
            "signature": self.signature,
        }


@dataclass(frozen=True)
class ValidationResult:
    """Complete licensing evaluation report."""
    status: ValidationStatus
    is_valid: bool
    license: Optional[LicenseEnvelope] = None
    message_fa: str = ""
    detail: str = ""
    in_grace_period: bool = False
    grace_mode: str = "readonly"
    days_remaining: Optional[int] = None
    is_trial: bool = False
