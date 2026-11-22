# licensing/keys.py
"""Public key registry and Ed25519 key management for Daqiq licensing."""

import base64
from typing import Dict, Optional
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

# Default trusted public keys embedded in Daqiq binary.
# To replace with your commercial vendor key before distribution, replace the string below.
DEFAULT_KEY_REGISTRY: Dict[str, str] = {
    # 32-byte raw Ed25519 public key encoded in Base64
    "daqiq-prod-v1": "tZwFxuCGOF+WZqVF+PeKwpoIpOZovHLFRVSQxGaXJXA=",
}


class KeyRegistry:
    """Registry of trusted Ed25519 public verification keys indexed by key_id."""

    def __init__(self, initial_keys: Optional[Dict[str, str]] = None):
        self._keys: Dict[str, ed25519.Ed25519PublicKey] = {}
        source = initial_keys if initial_keys is not None else DEFAULT_KEY_REGISTRY
        for key_id, raw_b64 in source.items():
            self.register_key_base64(key_id, raw_b64)

    def register_key_base64(self, key_id: str, raw_b64: str) -> None:
        """Register a base64-encoded raw 32-byte Ed25519 public key."""
        clean_b64 = raw_b64.strip()
        raw_bytes = base64.b64decode(clean_b64)
        if len(raw_bytes) != 32:
            raise ValueError(
                f"Public key for {key_id} must be exactly 32 bytes; got {len(raw_bytes)}"
            )
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(raw_bytes)
        self._keys[key_id] = pub_key

    def register_public_key(self, key_id: str, public_key: ed25519.Ed25519PublicKey) -> None:
        """Register an existing Ed25519PublicKey instance."""
        self._keys[key_id] = public_key

    def get_public_key(self, key_id: str) -> Optional[ed25519.Ed25519PublicKey]:
        """Retrieve the public key corresponding to key_id, or None if untrusted/unknown."""
        return self._keys.get(key_id)

    def has_key(self, key_id: str) -> bool:
        """Check whether key_id exists in the trusted registry."""
        return key_id in self._keys
