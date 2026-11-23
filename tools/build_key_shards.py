#!/usr/bin/env python3
"""Build-time utility to generate anti-tamper Ed25519 public key shards.

Compiles trusted public keys into XOR-masked shards with internal integrity
digests for Nuitka C-level native compilation, preventing plaintext key extraction
or hex-editor patching.
"""

import argparse
import base64
import hashlib
import json
import os
import sys
from typing import Dict, Tuple, List, Any


def normalize_ed25519_public_key(input_val: Any) -> Tuple[bytes, str]:
    """Parse and normalize an Ed25519 public key from Base64, Hex, or PEM into raw 32 bytes."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization

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

    # Check if PEM
    if "BEGIN PUBLIC KEY" in s:
        key = serialization.load_pem_public_key(s.encode("utf-8"))
        if not isinstance(key, ed25519.Ed25519PublicKey):
            raise ValueError("PEM key is not an Ed25519 public key.")
        raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return raw, base64.b64encode(raw).decode("ascii")

    # Check 64-char Hex
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

    raise ValueError(f"Unable to parse valid 32-byte Ed25519 public key from provided input: {s[:30]}...")


def compute_key_fingerprint(raw_bytes: bytes) -> str:
    """Compute short human-readable SHA-256 fingerprint (XXXX-XXXX-XXXX)."""
    digest = hashlib.sha256(raw_bytes).hexdigest().upper()
    return f"{digest[0:4]}-{digest[4:8]}-{digest[8:12]}"


def create_key_shards(raw_bytes: bytes, key_id: str, salt: bytes) -> Dict[str, Any]:
    """Split a 32-byte key into 4 XOR-masked shards with SHA-256 integrity tag."""
    if len(raw_bytes) != 32:
        raise ValueError(f"Key {key_id} must be 32 bytes; got {len(raw_bytes)}")

    s1 = os.urandom(32)
    s2 = os.urandom(32)
    s3 = os.urandom(32)
    s4 = bytes(k ^ a ^ b ^ c for k, a, b, c in zip(raw_bytes, s1, s2, s3))

    integrity = hashlib.sha256(
        b"DAQIQ-KEY-SHARDS-V1\n" + salt + key_id.encode("utf-8") + raw_bytes
    ).digest()

    return {
        "shards": (s1, s2, s3, s4),
        "integrity": integrity,
        "fingerprint": compute_key_fingerprint(raw_bytes),
    }


def generate_embedded_module_source(shards_registry: Dict[str, Dict[str, Any]], salt: bytes) -> str:
    """Generate Python source code for licensing/_embedded_keys.py."""
    lines = [
        '# Generated automatically by tools/build_key_shards.py - DO NOT EDIT MANUALLY',
        '"""Anti-tamper Ed25519 public key shards compiled into native C machine code."""',
        '',
        'import hashlib',
        'from typing import Dict, List',
        '',
        f'_BUILD_SALT = {repr(salt)}',
        '',
        '_SHARD_REGISTRY = {',
    ]

    for kid, data in shards_registry.items():
        lines.append(f'    {repr(kid)}: {{')
        lines.append('        "shards": (')
        for s in data["shards"]:
            lines.append(f'            {repr(s)},')
        lines.append('        ),')
        lines.append(f'        "integrity": {repr(data["integrity"])},')
        lines.append(f'        "fingerprint": {repr(data["fingerprint"])},')
        lines.append('    },')

    lines.extend([
        '}',
        '',
        'def reconstruct_keys() -> Dict[str, bytes]:',
        '    """Reconstruct all trusted 32-byte Ed25519 public keys from native XOR shards."""',
        '    keys = {}',
        '    for kid, data in _SHARD_REGISTRY.items():',
        '        shards = data["shards"]',
        '        expected_digest = data["integrity"]',
        '        reconstructed = bytes(a ^ b ^ c ^ d for a, b, c, d in zip(*shards))',
        '        actual_digest = hashlib.sha256(',
        '            b"DAQIQ-KEY-SHARDS-V1\\n" + _BUILD_SALT + kid.encode("utf-8") + reconstructed',
        '        ).digest()',
        '        if actual_digest != expected_digest:',
        '            raise RuntimeError(f"Cryptographic key shard integrity check failed for key ID: {kid}")',
        '        keys[kid] = reconstructed',
        '    return keys',
        '',
        'def get_embedded_fingerprints() -> List[Dict[str, str]]:',
        '    """Return read-only key IDs and human-readable fingerprints."""',
        '    return [',
        '        {',
        '            "key_id": kid,',
        '            "fingerprint": data["fingerprint"],',
        '            "display": f"{kid} · {data[\'fingerprint\']}",',
        '        }',
        '        for kid, data in _SHARD_REGISTRY.items()',
        '    ]',
        '',
    ])

    return "\n".join(lines)


def build_shards(
    output_path: str,
    manifest_path: str,
    override_key_b64: str = None,
    override_key_id: str = None,
    extra_keys_json: str = None,
) -> List[Dict[str, str]]:
    """Build key shards from environment overrides or manifest file."""
    keys_to_process: Dict[str, str] = {}

    if override_key_b64 and override_key_b64.strip():
        kid = (override_key_id or "daqiq-prod-v1").strip()
        keys_to_process[kid] = override_key_b64.strip()
    elif os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
            if isinstance(manifest_data, dict):
                keys_to_process.update(manifest_data)

    if extra_keys_json and extra_keys_json.strip():
        try:
            extra = json.loads(extra_keys_json.strip())
            if isinstance(extra, dict):
                keys_to_process.update(extra)
        except Exception as e:
            print(f"Warning: Failed to parse DAQIQ_LICENSE_EXTRA_KEYS_JSON: {e}", file=sys.stderr)

    if not keys_to_process:
        raise ValueError("No public keys provided in environment or manifest.")

    salt = os.urandom(32)
    shards_registry: Dict[str, Dict[str, Any]] = {}
    fingerprints: List[Dict[str, str]] = []

    for kid, val in keys_to_process.items():
        raw_bytes, b64_std = normalize_ed25519_public_key(val)
        shards_info = create_key_shards(raw_bytes, kid, salt)
        shards_registry[kid] = shards_info
        fp = shards_info["fingerprint"]
        fingerprints.append({
            "key_id": kid,
            "fingerprint": fp,
            "display": f"{kid} · {fp}",
            "b64": b64_std,
        })

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    source_code = generate_embedded_module_source(shards_registry, salt)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(source_code)

    return fingerprints


def main():
    parser = argparse.ArgumentParser(description="Generate anti-tamper Ed25519 public key shards.")
    parser.add_argument("--output", default="licensing/_embedded_keys.py", help="Output Python file path")
    parser.add_argument("--manifest", default="licensing/trusted_keys.json", help="Path to trusted_keys.json")
    args = parser.parse_args()

    env_key = os.environ.get("DAQIQ_LICENSE_PUBLIC_KEY_B64")
    env_kid = os.environ.get("DAQIQ_LICENSE_KEY_ID")
    env_extra = os.environ.get("DAQIQ_LICENSE_EXTRA_KEYS_JSON")

    fps = build_shards(
        output_path=args.output,
        manifest_path=args.manifest,
        override_key_b64=env_key,
        override_key_id=env_kid,
        extra_keys_json=env_extra,
    )

    print(f"Successfully generated embedded key shards at: {args.output}")
    for item in fps:
        print(f"  * Key ID: {item['key_id']} -> Fingerprint: {item['fingerprint']} ({item['display']})")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        try:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write("### Embedded Ed25519 License Public Keys (Native C Shards)\n\n")
                f.write("| Key ID | SHA-256 Fingerprint | Canonical Base64 |\n")
                f.write("|---|---|---|\n")
                for item in fps:
                    f.write(f"| `{item['key_id']}` | `{item['fingerprint']}` | `{item['b64']}` |\n")
                f.write("\n")
        except Exception as e:
            print(f"Warning: Failed to write to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
