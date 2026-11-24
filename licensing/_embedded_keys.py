# Generated automatically by tools/build_key_shards.py - DO NOT EDIT MANUALLY
"""Anti-tamper Ed25519 public key shards compiled into native C machine code."""

import hashlib
from typing import Dict, List

_BUILD_SALT = b";\xfe\x14'\x8c\x81HI\xa8z\x04ac\xa6m\xc0|[{\xad\x99\x90H\xdd\x9e\x03i\xa6\xfa\xc6\xdc~"
_FP_PREFIX = 'fp_v1:'

def get_embedded_fp_prefix() -> str:
    """Return configured hardware fingerprint prefix."""
    return _FP_PREFIX

_SHARD_REGISTRY = {
    'daqiq-prod-v1': {
        "shards": (
            b'\x8b\n\xc9kK\xde\x827\xc0@g\xa8)\x90^_Y\xe1\xee\x857\x00T\xc1D\xd5x\xd0L\x83\xb2_',
            b"\x85N\xa4\x12\x98;\x82w\x15O\x99^\x8e\xbb\xd7\x8a\x0b'\xab\x88wWv\xd1_\x07(\xbaV\xfb\x18A",
            b'\xdb\xb3s\xbe\xc4o\x08#B\xd3\x12\x02\xb7H_}\xb2\xb90\xe8M\xb0\xbfD\xa5\x11\x93m\xa4+g\x10',
            b'`k\x1b\x01\xf7\x0c0<\x01\xbaI\xb1\xe8\x94\\jzw\xd1\x03e[\xef\x91\xfb\x97S\xc3\xd8\xc4\xe8~',
        ),
        "integrity": b'\xbeF\xf9\r\xdf\x86\x9c\xd4\xcd\x1fh\x8e2\xe9\x04\xc8\xb6-\xed\x85\xf5\x15S_\x16(\xe7\xc4\xe8\xe2\xb3Q',
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
