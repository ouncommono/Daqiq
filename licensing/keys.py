# licensing/keys.py
"""Public key registry and Ed25519 key management for Daqiq licensing.

Enforces build-time C-compiled key sharding (anti-patch) and multi-key verification
matching the Daqiq-License-Generator specification.
"""

import base64
import hashlib
import os
from typing import Dict, Optional, List, Union, Tuple, Any
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

DEFAULT_SUPPORT_PHONE = "09193352435"

from .license_models import (
    CryptoVerificationError,
    KeyIntegrityError,
    PublicKeyNotConfiguredError,
)


def normalize_ed25519_public_key(input_val: Any) -> Tuple[bytes, str]:
    """Parse and normalize an Ed25519 public key from Base64, Hex, or PEM into raw 32 bytes."""
    if isinstance(input_val, bytes):
        try:
            s = input_val.decode("utf-8").strip()
        except UnicodeDecodeError:
            if len(input_val) == 32:
                ed25519.Ed25519PublicKey.from_public_bytes(input_val)
                b64_str = base64.b64encode(input_val).decode("ascii")
                return input_val, b64_str
            raise ValueError(f"Raw binary key must be exactly 32 bytes; got {len(input_val)}")
    else:
        s = str(input_val).strip()

    # Check if PEM SubjectPublicKeyInfo
    if "BEGIN PUBLIC KEY" in s:
        key = serialization.load_pem_public_key(s.encode("utf-8"))
        if not isinstance(key, ed25519.Ed25519PublicKey):
            raise ValueError("PEM key is not an Ed25519 public key.")
        raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return raw, base64.b64encode(raw).decode("ascii")

    # Check 64-character Hex string
    if len(s) == 64 and all(c in "0123456789abcdefABCDEF" for c in s):
        raw = bytes.fromhex(s)
        ed25519.Ed25519PublicKey.from_public_bytes(raw)
        return raw, base64.b64encode(raw).decode("ascii")

    # Check Base64 (standard or url-safe, with or without padding)
    clean_s = s.replace(" ", "").replace("\n", "").replace("\r", "")
    pad = len(clean_s) % 4
    if pad:
        clean_s += "=" * (4 - pad)

    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = decoder(clean_s)
            if len(raw) == 32:
                ed25519.Ed25519PublicKey.from_public_bytes(raw)
                return raw, base64.b64encode(raw).decode("ascii")
        except Exception:
            pass

    raise ValueError(f"Unable to parse valid 32-byte Ed25519 public key from input: {s[:30]}...")


def compute_key_fingerprint(raw_bytes: bytes) -> str:
    """Compute short human-readable SHA-256 fingerprint (XXXX-XXXX-XXXX)."""
    digest = hashlib.sha256(raw_bytes).hexdigest().upper()
    return f"{digest[0:4]}-{digest[4:8]}-{digest[8:12]}"


def validate_raw_public_key_b64(raw_b64: str) -> bool:
    """Validate that a string represents a valid 32-byte Ed25519 public key."""
    try:
        normalize_ed25519_public_key(raw_b64)
        return True
    except Exception:
        return False


def get_embedded_public_keys() -> Dict[str, bytes]:
    """Retrieve trusted public verification keys from native C-compiled shards."""
    try:
        from . import _embedded_keys
        return _embedded_keys.reconstruct_keys()
    except ImportError as e:
        raise PublicKeyNotConfiguredError(
            "Embedded public key module (_embedded_keys.py) is missing. Run tools/build_key_shards.py."
        ) from e
    except Exception as e:
        raise KeyIntegrityError(f"Embedded key integrity check failed: {e}") from e


def get_active_key_fingerprints() -> List[Dict[str, str]]:
    """Return read-only key IDs and human-readable fingerprints from embedded shards."""
    try:
        from . import _embedded_keys
        return _embedded_keys.get_embedded_fingerprints()
    except Exception:
        return []


def get_support_phone() -> str:
    """Return configured vendor support phone from embedded shards, env override, or default."""
    env_phone = (os.environ.get("DAQIQ_SUPPORT_PHONE") or "").strip()
    if env_phone:
        return env_phone
    try:
        from . import _embedded_keys
        getter = getattr(_embedded_keys, "get_embedded_support_phone", None)
        if callable(getter):
            val = str(getter() or "").strip()
            if val:
                return val
    except Exception:
        pass
    return DEFAULT_SUPPORT_PHONE


def _load_default_key_registry() -> Dict[str, str]:
    """Helper to maintain backward compatibility with code expecting DEFAULT_KEY_REGISTRY dict."""
    try:
        keys = get_embedded_public_keys()
        return {kid: base64.b64encode(raw).decode("ascii") for kid, raw in keys.items()}
    except Exception:
        return {}


DEFAULT_KEY_REGISTRY: Dict[str, str] = _load_default_key_registry()


class KeyRegistry:
    """Registry of trusted Ed25519 public verification keys indexed by key_id."""

    def __init__(
        self,
        initial_keys: Optional[Dict[str, Union[str, bytes, ed25519.Ed25519PublicKey]]] = None,
    ):
        self._keys: Dict[str, ed25519.Ed25519PublicKey] = {}
        self._raw_keys: Dict[str, bytes] = {}

        if initial_keys is not None:
            for key_id, key_val in initial_keys.items():
                if isinstance(key_val, ed25519.Ed25519PublicKey):
                    self.register_public_key(key_id, key_val)
                elif isinstance(key_val, bytes) and len(key_val) == 32:
                    self.register_key_bytes(key_id, key_val)
                elif isinstance(key_val, str):
                    self.register_key_base64(key_id, key_val)
                else:
                    raise CryptoVerificationError(f"Unsupported key value type for {key_id}: {type(key_val)}")
        else:
            embedded_raw = get_embedded_public_keys()
            if not embedded_raw:
                raise PublicKeyNotConfiguredError("No embedded public keys found in key store.")
            for key_id, raw_bytes in embedded_raw.items():
                self.register_key_bytes(key_id, raw_bytes)

    def register_key_bytes(self, key_id: str, raw_bytes: bytes) -> None:
        """Register a raw 32-byte Ed25519 public key."""
        if len(raw_bytes) != 32:
            raise CryptoVerificationError(f"Public key for {key_id} must be 32 bytes; got {len(raw_bytes)}")
        try:
            pub_key = ed25519.Ed25519PublicKey.from_public_bytes(raw_bytes)
            self._keys[key_id] = pub_key
            self._raw_keys[key_id] = raw_bytes
        except Exception as e:
            raise CryptoVerificationError(f"Failed to initialize Ed25519 public key for {key_id}: {e}") from e

    def register_key_base64(self, key_id: str, key_input: str) -> None:
        """Register a key from Base64, Hex, or PEM. Fails closed."""
        try:
            raw_bytes, _ = normalize_ed25519_public_key(key_input)
            self.register_key_bytes(key_id, raw_bytes)
        except Exception as e:
            raise CryptoVerificationError(f"Invalid public key for {key_id}: {e}") from e

    def register_public_key(self, key_id: str, public_key: ed25519.Ed25519PublicKey) -> None:
        """Register an existing Ed25519PublicKey instance."""
        if not public_key or not isinstance(public_key, ed25519.Ed25519PublicKey):
            raise CryptoVerificationError("Invalid Ed25519PublicKey instance.")
        self._keys[key_id] = public_key
        try:
            raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            self._raw_keys[key_id] = raw
        except Exception:
            pass

    def get_public_key(self, key_id: str) -> Optional[ed25519.Ed25519PublicKey]:
        """Retrieve public key for key_id, or None if not registered."""
        return self._keys.get(key_id)

    def get_all_public_keys(self) -> Dict[str, ed25519.Ed25519PublicKey]:
        """Return a copy of all registered public keys."""
        return dict(self._keys)

    def has_key(self, key_id: str) -> bool:
        """Check whether key_id exists in the registry."""
        return key_id in self._keys

    def get_active_key_fingerprints(self) -> List[Dict[str, str]]:
        """Return human-readable fingerprints for all registered keys."""
        res = []
        for kid, raw in self._raw_keys.items():
            fp = compute_key_fingerprint(raw)
            res.append({
                "key_id": kid,
                "fingerprint": fp,
                "display": f"{kid} · {fp}",
            })
        return res
