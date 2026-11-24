"""Centralized executable and external path resolution.

Guarantees that portable external files (such as default_taxonomy.json and app_config.json)
are resolved strictly adjacent to the true outer executable binary, even under Nuitka onefile
extraction or frozen execution, avoiding extraction cache directories.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_executable_dir() -> Path:
    """Return the directory containing the true outer application executable or project root."""
    # 1. Nuitka onefile extraction: outer binary location is exported in NUITKA_ONEFILE_BINARY
    onefile_bin = os.environ.get("NUITKA_ONEFILE_BINARY")
    if onefile_bin:
        try:
            candidate = Path(onefile_bin).resolve().parent
            if candidate.is_dir():
                return candidate
        except Exception:
            pass

    # 2. Frozen/compiled execution (Nuitka standalone or PyInstaller)
    is_frozen = getattr(sys, "frozen", False) or "__compiled__" in globals()
    if is_frozen:
        # Check sys.argv[0] first to avoid temp/cache extraction folders
        if sys.argv and sys.argv[0]:
            try:
                candidate = Path(sys.argv[0]).resolve().parent
                if candidate.is_dir():
                    return candidate
            except Exception:
                pass
        try:
            return Path(sys.executable).resolve().parent
        except Exception:
            pass

    # 3. Development / source mode: return repository root (parent of utils/)
    return Path(__file__).resolve().parent.parent


def get_app_config_path() -> Path:
    """Return path to app_config.json beside executable, falling back to AppData if read-only."""
    base_dir = get_executable_dir()
    local_cfg = base_dir / "app_config.json"
    try:
        probe = base_dir / ".write_test_daqiq_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return local_cfg
    except OSError:
        app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        fallback_dir = Path(app_data) / "Daqiq"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir / "app_config.json"


def get_default_taxonomy_path() -> Path:
    """Return path to default_taxonomy.json located strictly beside the executable."""
    return get_executable_dir() / "default_taxonomy.json"
