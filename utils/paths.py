"""Authoritative external runtime path resolution for Daqiq.

Handles Nuitka onefile cached mode (where ``sys.executable``, ``__file__``,
and Win32 ``GetModuleFileNameW(0)`` point to the extraction cache folder and
``NUITKA_ONEFILE_PARENT`` is an integer PID rather than a path), Nuitka
standalone bundles, PyInstaller bundles, and uncompiled development runs.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_DATA_DIR_NAME = "Daqiq"


def get_user_app_data_dir() -> Path:
    """Return the per-user writable application data directory."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / APP_DATA_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DATA_DIR_NAME


def _is_compiled_runtime() -> bool:
    """Return True when running from a frozen/Nuitka-compiled binary."""
    if bool(getattr(sys, "frozen", False)):
        return True
    if "__compiled__" in globals() or hasattr(sys, "__compiled__"):
        return True
    main_mod = sys.modules.get("__main__")
    if main_mod is not None and hasattr(main_mod, "__compiled__"):
        return True
    if os.environ.get("NUITKA_ONEFILE_BINARY") or os.environ.get("NUITKA_ONEFILE_PARENT"):
        return True
    return False


def _is_nuitka_cache_dir(candidate: Path) -> bool:
    """Return True if *candidate* points inside Nuitka's onefile extraction cache."""
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate

    parts_lower = [p.lower() for p in resolved.parts]
    # Standard Nuitka temp extraction names
    if any(part.startswith("onefile_") for part in parts_lower):
        return True

    # Cached-mode directory configured by scripts/build_nuitka.py: %LOCALAPPDATA%\Daqiq\<ver>
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        try:
            cache_root = (Path(local_app_data) / APP_DATA_DIR_NAME).resolve()
            if resolved == cache_root or resolved.is_relative_to(cache_root):
                return True
        except (OSError, ValueError):
            pass
    return False


def _is_python_host_binary(exe_path: Path) -> bool:
    """Return True if *exe_path* is python/pytest rather than Daqiq.exe."""
    name = exe_path.name.lower()
    return (
        name.startswith("python")
        or name.startswith("pytest")
        or name in {"py.exe", "pyw.exe", "uv.exe"}
    )


def get_executable_dir() -> Path:
    """Return the real directory containing the outer ``Daqiq.exe`` (or repo root in dev).

    Resolution priority:
    1. ``NUITKA_ONEFILE_BINARY`` environment variable (outer binary path in Nuitka onefile).
       Note: ``NUITKA_ONEFILE_PARENT`` is an integer PID and is NEVER treated as a path.
    2. ``__compiled__.containing_dir`` (on ``__main__`` or module), when not inside Nuitka cache.
    3. Resolved ``sys.argv[0]`` (for compiled or ``.exe`` invocations across working dirs).
    4. Resolved ``sys.executable`` directory (only when compiled and outside cache dir).
    5. Source repository root fallback (uncompiled development / pytest).
    """
    # 1. Authoritative Nuitka onefile outer binary env var
    onefile_bin = os.environ.get("NUITKA_ONEFILE_BINARY", "").strip()
    if onefile_bin:
        try:
            bin_path = Path(onefile_bin).expanduser().resolve()
            return bin_path if bin_path.is_dir() else bin_path.parent
        except OSError:
            return Path(onefile_bin).parent

    # 2. Nuitka __compiled__.containing_dir (safe against cache dir)
    for mod in (sys.modules.get("__main__"), sys.modules.get(__name__)):
        compiled_meta = getattr(mod, "__compiled__", None) if mod is not None else None
        if compiled_meta is not None:
            containing_dir = getattr(compiled_meta, "containing_dir", None)
            if containing_dir:
                cand = Path(str(containing_dir)).expanduser().resolve()
                if not _is_nuitka_cache_dir(cand):
                    return cand

    is_compiled = _is_compiled_runtime()

    # 3. Resolved sys.argv[0] when launched via compiled exe (even from a separate cwd)
    argv0 = (sys.argv[0] if sys.argv else "").strip()
    if argv0 and (is_compiled or argv0.lower().endswith(".exe")):
        raw_argv0 = Path(argv0).expanduser()
        resolved_argv0: Path | None = None
        if raw_argv0.is_absolute() or os.sep in argv0 or (os.altsep and os.altsep in argv0):
            try:
                resolved_argv0 = raw_argv0.resolve()
            except OSError:
                resolved_argv0 = raw_argv0
        else:
            which_hit = shutil.which(argv0)
            if which_hit:
                try:
                    resolved_argv0 = Path(which_hit).resolve()
                except OSError:
                    resolved_argv0 = Path(which_hit)
        if resolved_argv0 is not None and not _is_python_host_binary(resolved_argv0):
            cand = resolved_argv0.parent
            if not _is_nuitka_cache_dir(cand):
                return cand

    # 4. Compiled sys.executable (standalone builds outside onefile cache)
    if is_compiled and sys.executable:
        try:
            exe_path = Path(sys.executable).expanduser().resolve()
        except OSError:
            exe_path = Path(sys.executable)
        if not _is_python_host_binary(exe_path) and not _is_nuitka_cache_dir(exe_path.parent):
            return exe_path.parent

    # 5. Uncompiled source / pytest fallback -> repo root (parent of utils/)
    return Path(__file__).resolve().parent.parent


def get_app_config_path() -> Path:
    """Return path to ``app_config.json`` beside the executable when writable, else AppData."""
    exe_dir = get_executable_dir()
    local_path = exe_dir / "app_config.json"
    probe = exe_dir / ".daqiq_config.write-test"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return local_path
    except OSError:
        data_dir = get_user_app_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / "app_config.json"


def get_default_taxonomy_path() -> Path:
    """Return path to external ``default_taxonomy.json`` beside ``Daqiq.exe``."""
    return get_executable_dir() / "default_taxonomy.json"


def format_resolved_paths_report() -> str:
    """Format diagnostic path report for ``--print-paths`` CLI smoke testing."""
    exe_dir = get_executable_dir()
    app_cfg = get_app_config_path()
    taxonomy = get_default_taxonomy_path()
    lines = [
        f"EXECUTABLE_DIR={exe_dir}",
        f"APP_CONFIG_PATH={app_cfg}",
        f"DEFAULT_TAXONOMY_PATH={taxonomy}",
        f"NUITKA_ONEFILE_BINARY={os.environ.get('NUITKA_ONEFILE_BINARY', '')}",
        f"NUITKA_ONEFILE_PARENT={os.environ.get('NUITKA_ONEFILE_PARENT', '')}",
        f"CWD={Path.cwd()}",
    ]
    return "\n".join(lines)
