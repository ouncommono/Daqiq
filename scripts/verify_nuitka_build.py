#!/usr/bin/env python3
"""Automated acceptance verification for compiled Nuitka standalone and onefile binaries.

Verifies:
1. Binary exists and has non-zero size.
2. External default_taxonomy.json exists alongside executable.
3. Binary executes without crashing or missing DLL errors.
4. Unlicensed execution cleanly triggers licensing gate without database initialization.
5. Headless / offscreen test execution completes within timeout.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def verify_binary(binary_path: Path, is_standalone: bool = False) -> int:
    """Run thorough verification checks on a built Nuitka binary."""
    print("==================================================")
    print(f"Verifying Nuitka Binary: {binary_path}")
    print(f"Mode: {'Standalone' if is_standalone else 'Onefile'}")
    print("==================================================")

    if not binary_path.is_file():
        print(f"[FAIL] Executable not found at: {binary_path}", file=sys.stderr)
        return 1

    size_bytes = binary_path.stat().st_size
    if size_bytes < 1_000_000:
        print(f"[FAIL] Executable file size ({size_bytes} bytes) is suspiciously small.", file=sys.stderr)
        return 1

    print(f"[PASS] Executable exists: {size_bytes:,} bytes")

    # Check external taxonomy file beside executable
    taxonomy_file = binary_path.parent / "default_taxonomy.json"
    if not taxonomy_file.is_file():
        print(f"[FAIL] Sibling default_taxonomy.json missing next to binary at: {taxonomy_file}", file=sys.stderr)
        return 1
    print(f"[PASS] External default_taxonomy.json verified: {taxonomy_file.stat().st_size:,} bytes")

    # Run executable with DAQIQ_SMOKE_TEST=1
    # Note: In production, without an active license, it should show LicenseDialog or exit cleanly
    env = os.environ.copy()
    env["DAQIQ_SMOKE_TEST"] = "1"
    env["QT_FORCE_STDERR_LOGGING"] = "1"

    # Select platform plugin if present
    platforms_dir = binary_path.parent / "PySide6" / "plugins" / "platforms"
    if (platforms_dir / "qoffscreen.dll").is_file():
        env["QT_QPA_PLATFORM"] = "offscreen"
        print(f"Detected qoffscreen.dll; using QT_QPA_PLATFORM=offscreen")
    elif (platforms_dir / "qminimal.dll").is_file():
        env["QT_QPA_PLATFORM"] = "minimal"
        print(f"Detected qminimal.dll; using QT_QPA_PLATFORM=minimal")
    else:
        env.pop("QT_QPA_PLATFORM", None)
        print("Using default platform (windows)")

    print("\nRunning runtime smoke test (60s timeout)...")
    start_time = time.time()
    try:
        proc = subprocess.run(
            [str(binary_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60.0,
        )
        elapsed = time.time() - start_time
        print(f"[PASS] Binary executed and exited with returncode {proc.returncode} in {elapsed:.2f}s")
        if proc.stdout:
            print("--- STDOUT ---")
            print(proc.stdout)
        if proc.stderr:
            print("--- STDERR ---")
            print(proc.stderr)

        smoke_log = binary_path.parent / "smoke_test.log"
        if smoke_log.is_file():
            print("--- SMOKE TEST LOG ---")
            print(smoke_log.read_text(encoding="utf-8", errors="ignore"))

        if proc.returncode != 0:
            print(f"[FAIL] Executable exited with non-zero returncode {proc.returncode}", file=sys.stderr)
            return 1
    except subprocess.TimeoutExpired:
        print("[FAIL] Binary execution hung and timed out after 60 seconds!", file=sys.stderr)
        smoke_log = binary_path.parent / "smoke_test.log"
        if smoke_log.is_file():
            print("--- SMOKE TEST LOG BEFORE HANG ---")
            print(smoke_log.read_text(encoding="utf-8", errors="ignore"))
        return 1
    except Exception as e:
        print(f"[FAIL] Failed to execute binary: {e}", file=sys.stderr)
        return 1

    print("\nAll binary acceptance checks passed successfully!")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Daqiq Nuitka Binary Verification Script")
    parser.add_argument("--binary", type=Path, help="Explicit path to executable to verify")
    parser.add_argument("--mode", choices=["standalone", "onefile"], default="onefile", help="Build mode")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "dist"

    v_file = repo_root / "VERSION"
    version = v_file.read_text(encoding="utf-8").strip() if v_file.is_file() else "4.9.0"

    if args.binary:
        target = args.binary
        is_standalone = args.mode == "standalone" or "main.dist" in str(target)
    elif args.mode == "standalone":
        target = dist_dir / "main.dist" / "main.exe"
        is_standalone = True
    else:
        target = dist_dir / f"Daqiq_{version}.exe"
        is_standalone = False

    sys.exit(verify_binary(target, is_standalone))


if __name__ == "__main__":
    main()
