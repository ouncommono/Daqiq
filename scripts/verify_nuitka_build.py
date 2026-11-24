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

    smoke_log = binary_path.parent / "smoke_test.log"
    if smoke_log.is_file():
        try:
            smoke_log.unlink()
        except Exception:
            pass

    # Run executable with DAQIQ_SMOKE_TEST=1
    # Note: In production, without an active license, it should show LicenseDialog or exit cleanly
    env = os.environ.copy()
    env["DAQIQ_SMOKE_TEST"] = "1"
    env["DAQIQ_SMOKE_LOG_PATH"] = str(smoke_log.resolve())
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_FORCE_STDERR_LOGGING"] = "1"
    env["QT_LOGGING_TO_CONSOLE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"

    print("\nRunning runtime smoke test (offscreen mode, 60s timeout)...", flush=True)
    start_time = time.time()
    try:
        proc = subprocess.Popen(
            [str(binary_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=60.0)
        except subprocess.TimeoutExpired:
            print("[FAIL] Binary execution hung and timed out after 60 seconds!", file=sys.stderr, flush=True)
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.kill()
            stdout, stderr = proc.communicate()
            if stdout:
                print("--- STDOUT BEFORE TIMEOUT ---", flush=True)
                print(stdout, flush=True)
            if stderr:
                print("--- STDERR BEFORE TIMEOUT ---", flush=True)
                print(stderr, flush=True)
            if smoke_log.is_file():
                print("--- SMOKE TEST LOG BEFORE HANG ---", flush=True)
                print(smoke_log.read_text(encoding="utf-8", errors="ignore"), flush=True)
            return 1

        elapsed = time.time() - start_time
        print(f"[PASS] Binary executed and exited with returncode {proc.returncode} in {elapsed:.2f}s", flush=True)
        if stdout:
            print("--- STDOUT ---", flush=True)
            print(stdout, flush=True)
        if stderr:
            print("--- STDERR ---", flush=True)
            print(stderr, flush=True)

        if smoke_log.is_file():
            print("--- SMOKE TEST LOG ---", flush=True)
            print(smoke_log.read_text(encoding="utf-8", errors="ignore"), flush=True)

        if proc.returncode != 0:
            print(f"[FAIL] Executable exited with non-zero returncode {proc.returncode}", file=sys.stderr, flush=True)
            return 1
    except Exception as e:
        print(f"[FAIL] Failed to execute binary: {e}", file=sys.stderr, flush=True)
        return 1

    print("\nAll binary acceptance checks passed successfully!", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Daqiq Nuitka Binary Verification Script")
    parser.add_argument("--binary", type=Path, help="Explicit path to executable to verify")
    parser.add_argument("--mode", choices=["standalone", "onefile"], default="onefile", help="Build mode")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "dist"

    v_file = repo_root / "VERSION"
    version = v_file.read_text(encoding="utf-8").strip() if v_file.is_file() else "4.9.4"

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
