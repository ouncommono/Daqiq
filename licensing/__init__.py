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
    KeyIntegrityError,
    PublicKeyNotConfiguredError,
    HardwareIdentityUnavailableError,
    ClockRollbackError,
    StorageError,
)
from .keys import (
    KeyRegistry,
    DEFAULT_KEY_REGISTRY,
    validate_raw_public_key_b64,
    normalize_ed25519_public_key,
    compute_key_fingerprint,
    get_active_key_fingerprints,
)
from .device_identity import (
    HardwareIdentitySource,
    NativeWindowsHardwareProvider,
    WindowsHardwareProvider,
    MockHardwareProvider,
    get_system_hardware_fingerprint,
    get_system_hardware_fingerprint_with_tier,
    compute_hardware_fingerprint_from_components,
    create_device_request_dict,
)
from .license_verifier import LicenseVerifier
from .license_store import LicenseStore
from .license_policy import (
    LicenseService,
    TAB_MODULE_TO_FEATURE,
    CORE_TAB_FEATURES,
    SUBFEATURE_PARENT_TAB,
    ALL_LICENSE_FEATURES,
    FEATURE_LABELS_FA,
)
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
    "validate_raw_public_key_b64",
    "HardwareIdentitySource",
    "NativeWindowsHardwareProvider",
    "WindowsHardwareProvider",
    "MockHardwareProvider",
    "get_system_hardware_fingerprint",
    "get_system_hardware_fingerprint_with_tier",
    "compute_hardware_fingerprint_from_components",
    "create_device_request_dict",
    "LicenseVerifier",
    "LicenseStore",
    "LicenseService",
    "TAB_MODULE_TO_FEATURE",
    "CORE_TAB_FEATURES",
    "SUBFEATURE_PARENT_TAB",
    "ALL_LICENSE_FEATURES",
    "FEATURE_LABELS_FA",
    "LicenseDialog",
]
