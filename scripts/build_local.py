#!/usr/bin/env python3
"""Single-command local Windows build script for Daqiq.

Validates public_key, key_id, and fp_prefix (Precedence: Env Vars > build_license_config.local.json > Repo Defaults),
prints the resolved identity, builds with Nuitka, and restores tracked git files cleanly.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_key_shards import build_shards, normalize_ed25519_public_key, compute_key_fingerprint


def resolve_and_validate_identity(local_config_path: Path) -> dict:
    """Resolve and strictly validate public_key, key_id, and fp_prefix."""
    local_cfg = {}
    if local_config_path.is_file():
        data = json.loads(local_config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{local_config_path} must be a JSON object.")
        local_cfg = data

    manifest_path = REPO_ROOT / "licensing" / "trusted_keys.json"
    manifest = {}
    if manifest_path.is_file():
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            manifest = {str(k).strip(): str(v).strip() for k, v in loaded.items() if str(v).strip()}

    fp_prefix = (
        os.environ.get("DAQIQ_LICENSE_FP_PREFIX")
        or local_cfg.get("fp_prefix")
        or "fp_v1:"
    ).strip()
    if not fp_prefix:
        raise ValueError("fp_prefix cannot be empty.")
    if not fp_prefix.endswith(":"):
        fp_prefix += ":"

    key_id = (
        os.environ.get("DAQIQ_LICENSE_KEY_ID")
        or local_cfg.get("key_id")
        or next(iter(manifest.keys()), "daqiq-prod-v1")
    ).strip()
    if not key_id or any(ch.isspace() for ch in key_id):
        raise ValueError(f"Invalid key_id: {key_id!r}")

    pub_key_input = (
        os.environ.get("DAQIQ_LICENSE_PUBLIC_KEY_B64")
        or local_cfg.get("public_key")
        or manifest.get(key_id)
        or next(iter(manifest.values()), "")
    ).strip()
    if not pub_key_input:
        raise ValueError("No public_key configured in env, local config, or trusted_keys.json.")

    raw_bytes, b64_std = normalize_ed25519_public_key(pub_key_input)
    key_fp = compute_key_fingerprint(raw_bytes)

    return {
        "public_key_b64": b64_std,
        "key_id": key_id,
        "key_fp": key_fp,
        "fp_prefix": fp_prefix,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-command validated local build for Daqiq")
    parser.add_argument("--mode", choices=["onefile", "standalone"], default="onefile")
    parser.add_argument("--local-config", type=Path, default=REPO_ROOT / "build_license_config.local.json")
    parser.add_argument("--validate-only", action="store_true", help="Validate identity and exit without compiling")
    args = parser.parse_args()

    identity = resolve_and_validate_identity(args.local_config)
    print("=" * 64)
    print("  DAQIQ BUILD IDENTITY VALIDATION")
    print("=" * 64)
    print(f"  Key ID:        {identity['key_id']}")
    print(f"  Key FP:        {identity['key_fp']}")
    print(f"  FP Prefix:     {identity['fp_prefix']}")
    print(f"  Public Key:    {identity['public_key_b64']}")
    print("=" * 64)

    if args.validate_only:
        return 0

    embedded_path = REPO_ROOT / "licensing" / "_embedded_keys.py"
    original_embedded = embedded_path.read_bytes() if embedded_path.is_file() else None
    manifest_path = REPO_ROOT / "licensing" / "trusted_keys.json"

    try:
        build_shards(
            output_path=str(embedded_path),
            manifest_path=str(manifest_path),
            override_key_b64=identity["public_key_b64"],
            override_key_id=identity["key_id"],
            override_fp_prefix=identity["fp_prefix"],
            local_config_path=str(args.local_config),
        )
        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_nuitka.py"),
            "--mode",
            args.mode,
            "--skip-shards",
        ]
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
        return proc.returncode
    finally:
        if original_embedded is not None:
            embedded_path.write_bytes(original_embedded)


if __name__ == "__main__":
    sys.exit(main())
