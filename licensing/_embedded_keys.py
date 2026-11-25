# Generated automatically by tools/build_key_shards.py - DO NOT EDIT MANUALLY
"""Anti-tamper Ed25519 public key shards compiled into native C machine code."""

import hashlib
from typing import Dict, List

_BUILD_SALT = b'Al\xdcR@I^\x82N%\xd7\xa8\x19\xd8\xa6\x9aO\x8b\xf7\xcfPc>\xcb\xe6\xddh-\x9eo\xc1\x02'
_FP_PREFIX = 'fp_v1:'
_SUPPORT_PHONE = '09193352435'

def get_embedded_fp_prefix() -> str:
    """Return configured hardware fingerprint prefix."""
    return _FP_PREFIX

def get_embedded_support_phone() -> str:
    """Return build-time configured support phone number."""
    return _SUPPORT_PHONE

_SHARD_REGISTRY = {
    'daqiq-prod-v1': {
        "shards": (
            b"H\xfc\x19'\xdf N\xec+\xe4X\x96\x9df\x8eA\x90\x14ed2G\xd4:\x99\x19\xd8?\x8a\xe0l\xf4",
            b'l\xa0\xec\x89<X\xc8\x8a:\x8fD\xff\xd9<\x8f)k]"\x96shN\xe2O;M\xac\xfe\x8f\xf4\x97',
            b'\x80\xc7\xbc\x8b\x01\x15&PI\t\xf4\xac\x10x\xf0\xfc\xc8\x10\xab\x8f\xad\xe6\xa9vC\xad4P\xd1\x03\x9d\xc9',
            b'\x11\x07L\xe3\x02\xeb\x98i\xce\x04M\x80\xac\xd5{V\xa9QH\x9b\x84uAk\xd0\xdb1\x07\xc3\xfb \xda',
        ),
        "integrity": b'\x12\x19\xf8\xc7U\xcaT\xf7\xbe\x88~\xf8:\x9d\x96L\x13\xf9\r\x05Z\x9d<?\xf3\xd2\x85u\x16\x9a\xf8L',
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
