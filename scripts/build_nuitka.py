#!/usr/bin/env python3
"""Unified Nuitka Standard Build Driver for Daqiq Desktop.

Single source of truth for local Windows compilation and GitHub Actions CI.
Supports Stage A (--mode standalone) and Stage B (--mode onefile).
Optimized for lean executable size and fast cached startup.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_version(repo_root: Path) -> str:
    """Read version string from central VERSION file."""
    v_path = repo_root / "VERSION"
    if v_path.is_file():
        return v_path.read_text(encoding="utf-8").strip()
    return "4.9.7"


def compute_sha256(file_path: Path) -> str:
    """Compute lowercase hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def build(mode: str, repo_root: Path, skip_shards: bool = False) -> int:
    """Run optimized Nuitka compilation."""
    version = get_version(repo_root)
    dist_dir = repo_root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    print(f"==================================================")
    print(f"Daqiq Nuitka Standard Build Engine v{version}")
    print(f"Compilation Mode: {mode}")
    print(f"Repository Root: {repo_root}")
    print(f"Output Directory: {dist_dir}")
    print(f"==================================================")

    # Ensure anti-tamper key shards are in sync prior to compilation
    build_shards_script = repo_root / "tools" / "build_key_shards.py"
    if not skip_shards and build_shards_script.is_file():
        print("Synchronizing anti-tamper Ed25519 public key shards...")
        shard_proc = subprocess.run([sys.executable, str(build_shards_script)], cwd=str(repo_root))
        if shard_proc.returncode != 0:
            print("[ERROR] Failed to compile key shards prior to build", file=sys.stderr)
            return shard_proc.returncode

    import PySide6
    pyside6_dir = Path(PySide6.__file__).resolve().parent
    platforms_src = pyside6_dir / "plugins" / "platforms"

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        f"--mode={mode}",
        "--assume-yes-for-downloads",
        "--enable-plugin=pyside6",
        # Prune unused heavy Qt plugins and translations
        "--include-qt-plugins=sensible,platforms,styles,imageformats",
        "--noinclude-qt-translations",
        # Prune test and dev packages from payload
        "--noinclude-pytest-mode=nofollow",
        "--noinclude-unittest-mode=nofollow",
        "--noinclude-pydoc-mode=nofollow",
        "--noinclude-IPython-mode=nofollow",
        "--nofollow-import-to=pytest,unittest,doctest,pydoc,tkinter,turtle,distutils,lib2to3,setuptools,pip,wheel,tools",
        "--windows-console-mode=attach",
        f"--windows-icon-from-ico={repo_root / 'assets' / 'daqiq_logo.ico'}",
        f"--company-name=ouncommono",
        f"--product-name=Daqiq",
        f"--file-version={version}.0",
        f"--product-version={version}.0",
        f"--include-data-files={repo_root / 'assets' / 'daqiq_logo.ico'}=assets/daqiq_logo.ico",
        f"--include-data-files={repo_root / 'assets' / 'daqiq_logo.png'}=assets/daqiq_logo.png",
        f"--include-data-files={repo_root / 'assets' / 'daqiq_logo.svg'}=assets/daqiq_logo.svg",
        f"--include-data-files={repo_root / 'VERSION'}=VERSION",
    ]

    if platforms_src.is_dir():
        cmd.append(f"--include-data-dir={platforms_src}=PySide6/qt-plugins/platforms")
        cmd.append(f"--include-data-dir={platforms_src}=platforms")

    cmd.append(f"--output-dir={dist_dir}")

    # Detect MSVC vs GCC
    cl_path = shutil.which("cl")
    if cl_path:
        print(f"Detected MSVC compiler at: {cl_path}")
        cmd.append("--msvc=latest")
    else:
        print("MSVC not found on PATH; falling back to Nuitka automatic MinGW/GCC toolchain.")

    if mode == "onefile":
        onefile_name = f"Daqiq_{version}.exe"
        cmd.append(f"--output-filename={onefile_name}")
        # Enable onefile cache mode to avoid repeated decompression overhead
        cmd.append("--onefile-cache-mode=cached")
        cmd.append(f"--onefile-tempdir-spec={{CACHE_DIR}}/Daqiq/{version}")
        cmd.append(str(repo_root / "main.py"))
    else:
        cmd.append(str(repo_root / "main.py"))

    print("\nExecuting Nuitka command:")
    print(" ".join(cmd))
    print("\n--- Compilation in progress ---")

    proc = subprocess.run(cmd, cwd=str(repo_root))
    if proc.returncode != 0:
        print(f"\n[ERROR] Nuitka compilation failed with exit code {proc.returncode}", file=sys.stderr)
        return proc.returncode

    print("\n--- Compilation finished successfully ---")

    # Copy external default_taxonomy.json alongside output
    source_tax = repo_root / "default_taxonomy.json"
    if not source_tax.is_file():
        print(f"[ERROR] default_taxonomy.json not found at {source_tax}", file=sys.stderr)
        return 1

    if mode == "onefile":
        target_exe = dist_dir / f"Daqiq_{version}.exe"
        target_tax = dist_dir / "default_taxonomy.json"
        shutil.copy2(source_tax, target_tax)
        print(f"Copied external {source_tax.name} to {target_tax}")

        if not target_exe.is_file():
            print(f"[ERROR] Expected binary not found: {target_exe}", file=sys.stderr)
            return 1

        exe_size = target_exe.stat().st_size
        print(f"Output Executable: {target_exe} ({exe_size:,} bytes)")

        # Generate SHA256SUMS.txt
        sums_file = dist_dir / "SHA256SUMS.txt"
        exe_sha = compute_sha256(target_exe)
        tax_sha = compute_sha256(target_tax)

        sums_content = f"{exe_sha}  {target_exe.name}\n{tax_sha}  {target_tax.name}\n"
        sums_file.write_text(sums_content, encoding="utf-8")
        print(f"\nGenerated {sums_file}:")
        print(sums_content.strip())

    elif mode == "standalone":
        standalone_dir = dist_dir / "main.dist"
        if not standalone_dir.is_dir():
            print(f"[ERROR] Expected standalone dir not found: {standalone_dir}", file=sys.stderr)
            return 1
        target_tax = standalone_dir / "default_taxonomy.json"
        shutil.copy2(source_tax, target_tax)
        print(f"Copied external {source_tax.name} to {target_tax}")

        # Ensure all Qt platform plugins exist for headless verification
        if platforms_src.is_dir():
            for dest_sub in ["PySide6/qt-plugins/platforms", "platforms"]:
                p_dest = standalone_dir / dest_sub
                p_dest.mkdir(parents=True, exist_ok=True)
                for dll in platforms_src.glob("*.dll"):
                    shutil.copy2(dll, p_dest / dll.name)
            print("Verified complete Qt platform plugins in standalone directory.")

        print(f"Standalone distribution ready at: {standalone_dir}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Daqiq Nuitka Standard Build Driver")
    parser.add_argument(
        "--mode",
        choices=["standalone", "onefile"],
        default="onefile",
        help="Compilation mode: 'standalone' (Stage A) or 'onefile' (Stage B)",
    )
    parser.add_argument(
        "--skip-shards",
        action="store_true",
        help="Use already-generated licensing/_embedded_keys.py without regenerating",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    sys.exit(build(args.mode, repo_root, skip_shards=args.skip_shards))


if __name__ == "__main__":
    main()
