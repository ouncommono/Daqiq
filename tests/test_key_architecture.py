# tests/test_key_architecture.py
"""Automated tests for anti-tamper public key architecture and vendor key tool."""

import base64
import os
import subprocess
import sys
import tempfile
import json
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from licensing.keys import (
    normalize_ed25519_public_key,
    compute_key_fingerprint,
    KeyRegistry,
    get_embedded_public_keys,
    get_active_key_fingerprints,
)
from licensing.license_models import (
    KeyIntegrityError,
    PublicKeyNotConfiguredError,
    ValidationStatus,
)
from licensing.license_verifier import LicenseVerifier, canonicalize_payload, DOMAIN_PREFIX
from tools.build_key_shards import (
    create_key_shards,
    generate_embedded_module_source,
    build_shards,
)
from tools.license_key_tool import is_inside_repo


def test_key_normalization_all_formats():
    """Verify normalize_ed25519_public_key accepts Raw 32 bytes, Base64, URL-Safe Base64, Hex, and PEM."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    b64_std = base64.b64encode(raw).decode("ascii")
    b64_url = base64.urlsafe_b64encode(raw).decode("ascii").replace("=", "")
    hex_str = raw.hex()
    pem_str = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")

    # 1. Raw bytes
    r1, b1 = normalize_ed25519_public_key(raw)
    assert r1 == raw
    assert b1 == b64_std

    # 2. Standard Base64
    r2, b2 = normalize_ed25519_public_key(b64_std)
    assert r2 == raw
    assert b2 == b64_std

    # 3. URL-safe Base64 without padding
    r3, b3 = normalize_ed25519_public_key(b64_url)
    assert r3 == raw
    assert b3 == b64_std

    # 4. 64-char Hex
    r4, b4 = normalize_ed25519_public_key(hex_str)
    assert r4 == raw
    assert b4 == b64_std

    # 5. PEM format
    r5, b5 = normalize_ed25519_public_key(pem_str)
    assert r5 == raw
    assert b5 == b64_std

    # 6. Invalid input raises ValueError
    with pytest.raises(ValueError):
        normalize_ed25519_public_key("not-a-valid-key")


def test_key_fingerprint_format():
    """Verify compute_key_fingerprint produces XXXX-XXXX-XXXX format."""
    raw = b"\x00" * 32
    fp = compute_key_fingerprint(raw)
    parts = fp.split("-")
    assert len(parts) == 3
    assert all(len(p) == 4 for p in parts)
    assert fp.isupper()


def test_shards_reconstruction_roundtrip():
    """Verify that build_shards generates native shards that reconstruct to original keys."""
    priv1 = ed25519.Ed25519PrivateKey.generate()
    raw1 = priv1.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    b64_1 = base64.b64encode(raw1).decode("ascii")

    with tempfile.TemporaryDirectory() as td:
        manifest_p = os.path.join(td, "manifest.json")
        out_p = os.path.join(td, "_shards_test.py")

        with open(manifest_p, "w", encoding="utf-8") as f:
            json.dump({"test-key-1": b64_1}, f)

        fps = build_shards(output_path=out_p, manifest_path=manifest_p)
        assert len(fps) == 1
        assert fps[0]["key_id"] == "test-key-1"

        # Execute the generated file
        ns = {}
        with open(out_p, "r", encoding="utf-8") as f:
            code = f.read()
        exec(code, ns)

        reconstructed = ns["reconstruct_keys"]()
        assert "test-key-1" in reconstructed
        assert reconstructed["test-key-1"] == raw1


def test_shards_tamper_fails_closed():
    """Verify that modifying a single byte in the shard code raises an integrity error."""
    priv = ed25519.Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    b64 = base64.b64encode(raw).decode("ascii")

    with tempfile.TemporaryDirectory() as td:
        manifest_p = os.path.join(td, "manifest.json")
        out_p = os.path.join(td, "_shards_tamper.py")

        with open(manifest_p, "w", encoding="utf-8") as f:
            json.dump({"test-key": b64}, f)

        build_shards(output_path=out_p, manifest_path=manifest_p)

        with open(out_p, "r", encoding="utf-8") as f:
            code = f.read()

        # Corrupt one byte of salt or shard
        corrupted_code = code.replace("_BUILD_SALT = ", "_BUILD_SALT = b'tampered' + ")

        ns = {}
        exec(corrupted_code, ns)
        with pytest.raises(RuntimeError, match="integrity check failed"):
            ns["reconstruct_keys"]()


def test_multi_key_keyring_rotation():
    """Verify KeyRegistry and LicenseVerifier support multiple trusted keys and rotation."""
    priv1 = ed25519.Ed25519PrivateKey.generate()
    priv2 = ed25519.Ed25519PrivateKey.generate()
    priv_untrusted = ed25519.Ed25519PrivateKey.generate()

    raw1 = priv1.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    raw2 = priv2.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    keyring = KeyRegistry(initial_keys={"key-v1": raw1, "key-v2": raw2})
    verifier = LicenseVerifier(key_registry=keyring)

    def create_envelope(priv, kid):
        payload_dict = {
            "format_version": 1,
            "product_id": "daqiq.desktop",
            "license_id": "LIC-MULTI-01",
            "key_id": kid,
            "customer": {"name": "تست چند کلیدی", "organization": None, "contact": None},
            "license_type": "perpetual",
            "issued_at": "2026-11-23T00:00:00Z",
            "not_before": "2026-11-23T00:00:00Z",
            "expires_at": None,
            "max_devices": 1,
            "device_fingerprints": ["fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"],
            "features": {"dashboard": True},
            "min_app_version": None,
            "max_app_version": None,
        }
        canonical = canonicalize_payload(payload_dict)
        sig = priv.sign(DOMAIN_PREFIX + canonical)
        return {
            "envelope_version": 1,
            "algorithm": "Ed25519",
            "key_id": kid,
            "payload": payload_dict,
            "signature": base64.b64encode(sig).decode("ascii"),
        }

    # License signed by key-v1
    env1 = verifier.parse_envelope_from_bytes(json.dumps(create_envelope(priv1, "key-v1")).encode())
    verifier.verify_cryptographic_signature(env1)  # must pass

    # License signed by key-v2
    env2 = verifier.parse_envelope_from_bytes(json.dumps(create_envelope(priv2, "key-v2")).encode())
    verifier.verify_cryptographic_signature(env2)  # must pass

    # License signed by key-v2 but envelope says key-v1 (fallback keyring iteration)
    env2_alt = verifier.parse_envelope_from_bytes(json.dumps(create_envelope(priv2, "key-v1")).encode())
    verifier.verify_cryptographic_signature(env2_alt)  # must pass via fallback!

    # License signed by untrusted key must fail
    env_untrusted = verifier.parse_envelope_from_bytes(json.dumps(create_envelope(priv_untrusted, "key-v1")).encode())
    with pytest.raises(Exception):
        verifier.verify_cryptographic_signature(env_untrusted)


def test_license_key_tool_safety_guard():
    """Verify license_key_tool generate-keypair refuses to write inside the repository."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert is_inside_repo(repo_root)
    assert is_inside_repo(os.path.join(repo_root, "licensing"))
    assert not is_inside_repo(tempfile.gettempdir())

    res = subprocess.run(
        [sys.executable, "tools/license_key_tool.py", "generate-keypair", "--out-dir", repo_root],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "CRITICAL SECURITY GUARD REJECTION" in res.stderr


def test_license_key_tool_generate_and_inspect_external():
    """Verify license_key_tool generate-keypair succeeds in external directory and inspect works."""
    with tempfile.TemporaryDirectory() as td:
        res = subprocess.run(
            [sys.executable, "tools/license_key_tool.py", "generate-keypair", "--out-dir", td, "--key-id", "test-kid"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert os.path.isfile(os.path.join(td, "ed25519_private_key.raw"))
        assert os.path.isfile(os.path.join(td, "ed25519_public_key_b64.txt"))

    # Test inspect command
    res_inspect = subprocess.run(
        [sys.executable, "tools/license_key_tool.py", "inspect"],
        capture_output=True,
        text=True,
    )
    assert res_inspect.returncode == 0
    assert "DAQIQ LICENSING PUBLIC KEY INSPECTION" in res_inspect.stdout
    assert "daqiq-prod-v1" in res_inspect.stdout


def test_zero_private_keys_tracked_in_git():
    """Verify NO signing secrets exist in git repository."""
    res = subprocess.run(
        ["git", "grep", "-in", "PRIVATE" + " " + "KEY", "--", ":!tests/test_key_architecture.py"],
        capture_output=True,
        text=True,
    )
    # git grep returns 1 when pattern is not found
    assert res.returncode == 1, f"Found secret key pattern in repo: {res.stdout}"

    # Also scan git ls-files for suspicious filenames
    res_files = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
    )
    assert res_files.returncode == 0
    for f in res_files.stdout.splitlines():
        lower = f.lower()
        assert not ("private" in lower and ("key" in lower or ".pem" in lower or ".raw" in lower)), f"Suspicious file in git: {f}"
