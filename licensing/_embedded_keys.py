# Generated automatically by tools/build_key_shards.py - DO NOT EDIT MANUALLY
"""Anti-tamper Ed25519 public key shards compiled into native C machine code."""

import hashlib
from typing import Dict, List

_BUILD_SALT = b'\xdf,\xff4\xcd\xb9\xae\x0e\xf4\xf9e\xd8\xfc\xe1\x88\xe7CA\xad\xdd\xfe<\xd8\xea9.r\x85\x1b\x9b\xef-'
_FP_PREFIX = 'fp_v1:'

def get_embedded_fp_prefix() -> str:
    """Return configured hardware fingerprint prefix."""
    return _FP_PREFIX

_SHARD_REGISTRY = {
    'daqiq-prod-v1': {
        "shards": (
            b'WE^D\xf0\x0f\xe3Nd\xa7\xfc\xf6\xaa\xb5&\xb7P?~\xb0Y\xb2\xc3\xde\xb6\x0e.F\xe4.\xb5\x1f',
            b'\xba\x02\xbf4f\xc8s\xd2\xd5Q\xa0\xeb*#\x9c\xe1\x0b\xda\xef\xc3.\x86\xf8\xaa<Ng\x16\rf\xb9\xa2',
            b'\xfd-d\xf8\xa9\x90\xaf`\xef\xf4<\xba\xbe,cY\xa4p\x94\xe4Z\x9c\x0e\xff\xb4\x9e\xbc\x92Z\x0fma',
            b'\xa5\xf6\x80N\xdf\xd1\x07\xa3\xc8d\xc5\xe2\xc6MS\xcde\x9d\xa1qE\x14GN{\x8ae\x06\xd5\xd0D\xac',
        ),
        "integrity": b'N8\x9b\xc96\xe6\x0f\xc5\xd4\xc5\x91F\xf0\x9b\x12\x89\x05\x18\x9f\x88\xe8\xd3v\x8a\xa7J\x96\x19#\xce\x97G',
        "fingerprint": '7925-3864-0164',
    },
}

def reconstruct_keys() -> Dict[str, bytes]:
    """Reconstruct all trusted 32-byte Ed25519 public keys from native XOR shards."""
    keys = {}
    for kid, data in _SHARD_REGISTRY.items():
        shards = data["shards"]
        expected_digest = data["integrity"]
        reconstructed = bytes(a ^ b ^ c ^ d for a, b, c, d in zip(*shards))
        actual_digest = hashlib.sha256(
            b"DAQIQ-KEY-SHARDS-V1\n" + _BUILD_SALT + kid.encode("utf-8") + reconstructed
        ).digest()
        if actual_digest != expected_digest:
            raise RuntimeError(f"Cryptographic key shard integrity check failed for key ID: {kid}")
        keys[kid] = reconstructed
    return keys

def get_embedded_fingerprints() -> List[Dict[str, str]]:
    """Return read-only key IDs and human-readable fingerprints."""
    return [
        {
            "key_id": kid,
            "fingerprint": data["fingerprint"],
            "display": f"{kid} · {data['fingerprint']}",
        }
        for kid, data in _SHARD_REGISTRY.items()
    ]
