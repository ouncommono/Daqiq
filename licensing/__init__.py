# licensing/__init__.py
"""Daqiq Commercial Offline Licensing Package (v1.0 / Ed25519).

Air-gapped, database-independent cryptographic licensing engine.
"""

from .license_models import (
    CustomerInfo,
    LicensePayload,
    LicenseEnvelope,
    ValidationStatus,
    ValidationResult,
    LicensingError,
    CryptoVerificationError,
    HardwareIdentityUnavailableError,
    ClockRollbackError,
    StorageError,
)
from .keys import KeyRegistry, DEFAULT_KEY_REGISTRY
from .device_identity import (
    HardwareIdentitySource,
    WindowsHardwareProvider,
    MockHardwareProvider,
    get_system_hardware_fingerprint,
    compute_hardware_fingerprint_from_components,
)
from .license_verifier import LicenseVerifier
from .license_store import LicenseStore
from .license_policy import LicenseService
from .license_dialog import LicenseDialog

__all__ = [
    "CustomerInfo",
    "LicensePayload",
    "LicenseEnvelope",
    "ValidationStatus",
    "ValidationResult",
    "LicensingError",
    "CryptoVerificationError",
    "HardwareIdentityUnavailableError",
    "ClockRollbackError",
    "StorageError",
    "KeyRegistry",
    "DEFAULT_KEY_REGISTRY",
    "HardwareIdentitySource",
    "WindowsHardwareProvider",
    "MockHardwareProvider",
    "get_system_hardware_fingerprint",
    "compute_hardware_fingerprint_from_components",
    "LicenseVerifier",
    "LicenseStore",
    "LicenseService",
    "LicenseDialog",
]
