# Generated automatically by tools/build_key_shards.py - DO NOT EDIT MANUALLY
"""Anti-tamper Ed25519 public key shards compiled into native C machine code."""

import hashlib
from typing import Dict, List

_BUILD_SALT = b'\xb9\x83Y\xef\x16\x04\x07\x93\x7f2Bs\x0ex\xd6\x05\x1b2wm\xe5\x8d4\xf6\xda\xd1\x17\xaa\x14K\xc9\x07'

_SHARD_REGISTRY = {
    'daqiq-prod-v1': {
        "shards": (
            b'\xd7\xa7\t\x99:!\xe4\x04\x91#f\xe5\xfa\xf9\xceX\x8a\xa7\xfb\x9c\xb0\x83\x17\xc4yc\x05\xd4\xbcL\xc5\xaa',
            b'\xba\xd2M\x07\x8c\xed\t\x902\xe9\xa9\xf4\x9f\xb81\x15\x90R\xb2\x1d\xc2p\xa1p$$\x80\x18\xea\xae\xee\xf8',
            b"\x01\x9df\xa1)\n\xe1M\x9b\x81\xe7]\xfa\xe8h\xab3\x9f\\.*\x7f\x97'\xd2S\x91\x9d\xdf\x86\xfd\xb0",
            b"\xd9t'\xf9\x7f@4\x86\xae-\x8d\tg^\x1d$\xb3b\xb1I00SV\xca@\x84\x95\xef\xf3\xf3\x92",
        ),
        "integrity": b'I\x17\x7f\xbc\x03ZV`Z\x07\x0cq$\xa5\xc0\x13\x8dL\xdb\x82\x04\xc2\x0e1\x9fEnL\xe0\x19\x17U',
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
