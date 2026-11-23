#!/usr/bin/env python3
"""Developer utility for Ed25519 licensing keys and cross-repo validation.

STRICTLY FOR DEVELOPER / CI USE.
MUST NOT BE BUNDLED INTO DAQIQ BINARY (excluded via --nofollow-import-to=tools).
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Ensure project root is in sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from licensing.keys import (
    normalize_ed25519_public_key,
    compute_key_fingerprint,
    KeyRegistry,
    get_embedded_public_keys,
)
from tools.build_key_shards import build_shards


def is_inside_repo(target_path: str, repo_root: str = _PROJECT_ROOT) -> bool:
    """Return True if target_path is inside the git repository working tree."""
    abs_target = os.path.realpath(os.path.abspath(target_path))
    abs_repo = os.path.realpath(os.path.abspath(repo_root))
    try:
        common = os.path.commonpath([abs_target, abs_repo])
        return common == abs_repo
    except ValueError:
        return False


def cmd_inspect(args):
    """Inspect currently configured public keys and embedded shard module."""
    manifest_path = os.path.join(_PROJECT_ROOT, "licensing", "trusted_keys.json")
    embedded_path = os.path.join(_PROJECT_ROOT, "licensing", "_embedded_keys.py")

    print("=" * 70)
    print("  DAQIQ LICENSING PUBLIC KEY INSPECTION")
    print("=" * 70)

    # 1. Manifest
    manifest_keys: Dict[str, str] = {}
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_keys = json.load(f)
        print(f"Manifest File: {manifest_path} ({len(manifest_keys)} keys found)")
    else:
        print(f"Manifest File: NOT FOUND ({manifest_path})")

    # 2. Embedded Shards
    embedded_keys: Dict[str, bytes] = {}
    embedded_valid = False
    if os.path.isfile(embedded_path):
        try:
            embedded_keys = get_embedded_public_keys()
            embedded_valid = True
            print(f"Embedded Module: {embedded_path} (Integrity check PASSED)")
        except Exception as e:
            print(f"Embedded Module: {embedded_path} (Integrity check FAILED: {e})")
    else:
        print(f"Embedded Module: NOT FOUND ({embedded_path})")

    print("-" * 70)
    print(f"{'Key ID':<18} {'Fingerprint':<16} {'In Sync?':<10} {'Canonical Base64'}")
    print("-" * 70)

    all_kids = sorted(set(list(manifest_keys.keys()) + list(embedded_keys.keys())))
    if not all_kids:
        print("  No public keys currently configured.")
    for kid in all_kids:
        m_val = manifest_keys.get(kid)
        e_val = embedded_keys.get(kid)

        raw_m = None
        b64_m = "-"
        fp_m = "-"
        if m_val:
            try:
                raw_m, b64_m = normalize_ed25519_public_key(m_val)
                fp_m = compute_key_fingerprint(raw_m)
            except Exception:
                fp_m = "INVALID"

        in_sync = "YES" if (raw_m and e_val and raw_m == e_val) else "NO"
        if not embedded_valid:
            in_sync = "DESYNC"

        fp_display = fp_m if fp_m != "-" else (compute_key_fingerprint(e_val) if e_val else "-")
        b64_display = b64_m if b64_m != "-" else (base64.b64encode(e_val).decode("ascii") if e_val else "-")

        print(f"{kid:<18} {fp_display:<16} {in_sync:<10} {b64_display}")

    print("=" * 70)


def cmd_set_public_key(args):
    """Normalize and configure a public key, regenerating embedded shards."""
    key_input = args.key
    if os.path.isfile(key_input):
        with open(key_input, "r", encoding="utf-8") as f:
            key_input = f.read().strip()

    try:
        raw_bytes, b64_std = normalize_ed25519_public_key(key_input)
    except Exception as e:
        print(f"Error: Invalid public key input: {e}", file=sys.stderr)
        sys.exit(1)

    key_id = (args.key_id or "daqiq-prod-v1").strip()
    fp = compute_key_fingerprint(raw_bytes)
    hex_str = raw_bytes.hex()

    manifest_path = os.path.join(_PROJECT_ROOT, "licensing", "trusted_keys.json")
    embedded_path = os.path.join(_PROJECT_ROOT, "licensing", "_embedded_keys.py")

    manifest: Dict[str, str] = {}
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    manifest[key_id] = b64_std
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Regenerate shards
    build_shards(output_path=embedded_path, manifest_path=manifest_path)

    print("=" * 70)
    print("  PUBLIC KEY REGISTERED & SHARDS COMPILED SUCCESSFULLY")
    print("=" * 70)
    print(f"  Key ID:              {key_id}")
    print(f"  SHA-256 Fingerprint: {fp} ({key_id} · {fp})")
    print(f"  Canonical Base64:    {b64_std}")
    print(f"  Raw 64-char Hex:     {hex_str}")
    print("-" * 70)
    print("  Paste into GitHub Actions Secret / Variable (DAQIQ_LICENSE_PUBLIC_KEY_B64):")
    print(f"  {b64_std}")
    print("=" * 70)


def cmd_generate_keypair(args):
    """Generate an Ed25519 keypair, enforcing the repo-safety guard against secret leaks."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization

    out_dir = os.path.abspath(args.out_dir)

    # REPO SAFETY GUARD: Refuse to write inside git repository working tree
    if is_inside_repo(out_dir):
        print(
            "\n" + "!" * 75 + "\n"
            "CRITICAL SECURITY GUARD REJECTION:\n"
            f"The target directory '{out_dir}' is located INSIDE the Daqiq git repository!\n"
            "To prevent accidental leaks of the vendor secret signing key into git history,\n"
            "this tool strictly REFUSES to write secret keys inside the working tree.\n"
            "Please specify an external secure vault directory outside the repository (e.g. ~/DaqiqVault).\n"
            + "!" * 75 + "\n",
            file=sys.stderr,
        )
        sys.exit(1)

    os.makedirs(out_dir, exist_ok=True)

    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()

    priv_raw = priv_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    priv_b64 = base64.b64encode(priv_raw).decode("ascii")
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    pub_hex = pub_raw.hex()
    fp = compute_key_fingerprint(pub_raw)
    key_id = (args.key_id or "daqiq-prod-v1").strip()

    # Write files in external directory
    with open(os.path.join(out_dir, "ed25519_private_key.raw"), "wb") as f:
        f.write(priv_raw)

    with open(os.path.join(out_dir, "ed25519_private_key_b64.txt"), "w", encoding="utf-8") as f:
        f.write(priv_b64 + "\n")

    with open(os.path.join(out_dir, "ed25519_public_key_b64.txt"), "w", encoding="utf-8") as f:
        f.write(pub_b64 + "\n")

    with open(os.path.join(out_dir, "ed25519_public_key.hex"), "w", encoding="utf-8") as f:
        f.write(pub_hex + "\n")

    info = {
        "key_id": key_id,
        "public_key_b64": pub_b64,
        "fingerprint": fp,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "notes": "Generated by Daqiq license_key_tool for Daqiq-License-Generator",
    }
    with open(os.path.join(out_dir, "key_info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)

    print("=" * 70)
    print("  ED25519 KEYPAIR GENERATED SAFELY (OUTSIDE REPOSITORY)")
    print("=" * 70)
    print(f"  Target Vault Directory: {out_dir}")
    print(f"  Key ID:                 {key_id}")
    print(f"  Public Key Fingerprint: {fp} ({key_id} · {fp})")
    print(f"  Public Key (Base64):    {pub_b64}")
    print(f"  Public Key (Hex):       {pub_hex}")
    print("-" * 70)
    print("  Files written in vault:")
    print("    - ed25519_private_key.raw        (raw 32 bytes for Daqiq-License-Generator)")
    print("    - ed25519_private_key_b64.txt    (Base64 encoded secret signing key)")
    print("    - ed25519_public_key_b64.txt     (Base64 encoded public key)")
    print("    - ed25519_public_key.hex         (64-char hex public key)")
    print("    - key_info.json                  (metadata)")
    print("=" * 70)


def cmd_verify_license(args):
    """Run Daqiq's exact verifier against a license file and output full diagnostics."""
    from licensing.license_verifier import LicenseVerifier
    from licensing.device_identity import WindowsHardwareProvider

    lic_path = os.path.abspath(args.license_path)
    if not os.path.isfile(lic_path):
        print(f"Error: License file not found: {lic_path}", file=sys.stderr)
        sys.exit(1)

    with open(lic_path, "rb") as f:
        raw_content = f.read()

    verifier = LicenseVerifier()
    print("=" * 70)
    print("  DAQIQ LICENSE VERIFICATION DIAGNOSTICS")
    print("=" * 70)
    print(f"  File: {lic_path} ({len(raw_content)} bytes)")

    try:
        envelope = verifier.parse_envelope_from_bytes(raw_content)
        print("  [✓] JSON & Envelope Structure: Valid")
        print(f"      - Envelope Version: {envelope.envelope_version}")
        print(f"      - Algorithm:        {envelope.algorithm}")
        print(f"      - Key ID:           {envelope.key_id}")
        print(f"      - License ID:       {envelope.payload.license_id}")
        print(f"      - Customer Name:    {envelope.payload.customer.name}")
        print(f"      - License Type:     {envelope.payload.license_type}")
        print(f"      - Issued At:        {envelope.payload.issued_at}")
        print(f"      - Expires At:       {envelope.payload.expires_at or 'Perpetual'}")
        print(f"      - Devices Bound:    {len(envelope.payload.device_fingerprints)} / {envelope.payload.max_devices}")
    except Exception as e:
        print(f"  [X] Envelope Parsing FAILED: {e}")
        sys.exit(1)

    # Signature check
    try:
        verifier.verify_cryptographic_signature(envelope)
        print("  [✓] Cryptographic Signature: VALID")
    except Exception as e:
        print(f"  [X] Cryptographic Signature FAILED: {e}")

    # Hardware check
    target_fp = None
    if args.request and os.path.isfile(args.request):
        with open(args.request, "r", encoding="utf-8") as rf:
            req_data = json.load(rf)
            target_fp = req_data.get("device_fingerprint")
            print(f"  Target Hardware from Request File: {target_fp}")
    else:
        try:
            hw_prov = WindowsHardwareProvider()
            target_fp = hw_prov.get_fingerprint()
            print(f"  Local Host Hardware Fingerprint:   {target_fp}")
        except Exception as e:
            print(f"  Warning: Could not acquire local hardware fingerprint: {e}")

    if target_fp:
        res = verifier.validate_license(
            envelope=envelope,
            current_hardware_fingerprint=target_fp,
            current_app_version="4.9.2",
        )
        print("-" * 70)
        print(f"  Evaluation Status:  {res.status.value}")
        print(f"  Evaluation Message: {res.message_fa}")
        if res.detail:
            print(f"  Evaluation Detail:  {res.detail}")
        print(f"  Overall Valid:      {res.is_valid}")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Daqiq License Key Management & Diagnostics Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # inspect
    subparsers.add_parser("inspect", help="Inspect configured public keys and embedded shards")

    # set-public-key
    p_set = subparsers.add_parser("set-public-key", help="Register a public key and recompile shards")
    p_set.add_argument("--key", required=True, help="Base64, Hex, PEM string, or path to key file")
    p_set.add_argument("--key-id", default="daqiq-prod-v1", help="Key ID (default: daqiq-prod-v1)")

    # generate-keypair
    p_gen = subparsers.add_parser("generate-keypair", help="Generate Ed25519 keypair outside the git repo")
    p_gen.add_argument("--out-dir", required=True, help="Target directory outside the repository")
    p_gen.add_argument("--key-id", default="daqiq-prod-v1", help="Key ID (default: daqiq-prod-v1)")

    # verify-license
    p_ver = subparsers.add_parser("verify-license", help="Run full diagnostic verification on a .daqlic file")
    p_ver.add_argument("license_path", help="Path to .daqlic license file")
    p_ver.add_argument("--request", help="Optional path to .daqreq request file")

    args = parser.parse_args()

    if args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "set-public-key":
        cmd_set_public_key(args)
    elif args.command == "generate-keypair":
        cmd_generate_keypair(args)
    elif args.command == "verify-license":
        cmd_verify_license(args)


if __name__ == "__main__":
    main()
