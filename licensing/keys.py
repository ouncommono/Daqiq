# licensing/keys.py
"""Public key registry and Ed25519 key management for Daqiq licensing."""

import base64
import os
from typing import Dict, Optional
from cryptography.hazmat.primitives.asymmetric import ed25519
from .license_models import CryptoVerificationError

# Default trusted public keys embedded in Daqiq binary.
# Overridable via DAQIQ_PUBLIC_KEY environment variable during build or test.
DEFAULT_KEY_REGISTRY: Dict[str, str] = {
    # 32-byte raw Ed25519 public key encoded in Base64
    "daqiq-prod-v1": os.environ.get("DAQIQ_PUBLIC_KEY", "tZwFxuCGOF+WZqVF+PeKwpoIpOZovHLFRVSQxGaXJXA=").strip(),
}


def validate_raw_public_key_b64(raw_b64: str) -> bool:
    """Validate that a base64 string decodes to exactly 32 bytes for Ed25519."""
    if not raw_b64 or not isinstance(raw_b64, str):
        return False
    try:
        raw_bytes = base64.b64decode(raw_b64.strip(), validate=True)
        return len(raw_bytes) == 32
    except Exception:
        return False


class KeyRegistry:
    """Registry of trusted Ed25519 public verification keys indexed by key_id."""

    def __init__(self, initial_keys: Optional[Dict[str, str]] = None):
        self._keys: Dict[str, ed25519.Ed25519PublicKey] = {}
        source = initial_keys if initial_keys is not None else DEFAULT_KEY_REGISTRY
        for key_id, raw_b64 in source.items():
            self.register_key_base64(key_id, raw_b64)

    def register_key_base64(self, key_id: str, raw_b64: str) -> None:
        """Register a base64-encoded raw 32-byte Ed25519 public key. Fails closed."""
        clean_b64 = (raw_b64 or "").strip()
        if not clean_b64:
            raise CryptoVerificationError(f"Public key for {key_id} is empty or missing.")
        try:
            raw_bytes = base64.b64decode(clean_b64, validate=True)
        except Exception as e:
            raise CryptoVerificationError(
                f"Public key for {key_id} contains invalid Base64 encoding: {e}"
            ) from e

        if len(raw_bytes) != 32:
            raise CryptoVerificationError(
                f"Public key for {key_id} must be exactly 32 bytes; got {len(raw_bytes)}"
            )
        try:
            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(raw_bytes)
            self._keys[key_id] = pub_key
        except Exception as e:
            raise CryptoVerificationError(
                f"Failed to initialize Ed25519 public key for {key_id}: {e}"
            ) from e

    def register_public_key(self, key_id: str, public_key: ed25519.Ed25519PublicKey) -> None:
        """Register an existing Ed25519PublicKey instance."""
        if not public_key or not isinstance(public_key, ed25519.Ed25519PublicKey):
            raise CryptoVerificationError("Invalid Ed25519PublicKey instance.")
        self._keys[key_id] = public_key

    def get_public_key(self, key_id: str) -> Optional[ed25519.Ed25519PublicKey]:
        """Retrieve the public key corresponding to key_id, or None if untrusted/unknown."""
        return self._keys.get(key_id)

    def has_key(self, key_id: str) -> bool:
        """Check whether key_id exists in the trusted registry."""
        return key_id in self._keys
