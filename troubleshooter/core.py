"""Core decoupled safety engine for Daqiq-Troubleshooter (stdlib only)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

BACKUP_NAME_PATTERNS = (
    re.compile(r"^daqiqbackup_.*\.db$", re.IGNORECASE),
    re.compile(r".*_backup_\d{8}_\d{6}(?:_\d+)?\.db$", re.IGNORECASE),
    re.compile(r".*backup.*\.db$", re.IGNORECASE),
    re.compile(r".*\.bak$", re.IGNORECASE),
    re.compile(r".*\.pre_cal_migration_.*\.bak$", re.IGNORECASE),
)

LEGACY_LICENSE_DIRS = ("license", "licensing", ".roaming_anchor")
LICENSE_AND_ANCHOR_FILES = (
    "license.daqlic",
    ".clock_state.dat",
    ".runtime_anchor.dat",
    "clock_state.json",
    "secure_vault.dat",
)


@dataclass
class TroubleshootingPlan:
    executable_dir: Path
    local_app_daqiq: Path
    roaming_app_daqiq: Path
    config_files: List[Path] = field(default_factory=list)
    cache_paths: List[Path] = field(default_factory=list)
    runtime_paths: List[Path] = field(default_factory=list)
    license_paths: List[Path] = field(default_factory=list)
    protected_backup_dirs: List[Path] = field(default_factory=list)
    protected_backup_files: List[Path] = field(default_factory=list)
    database_files: List[Path] = field(default_factory=list)
    running_pids: List[int] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class TroubleshootingResult:
    removed_configs: List[Path] = field(default_factory=list)
    removed_caches: List[Path] = field(default_factory=list)
    removed_runtime: List[Path] = field(default_factory=list)
    removed_licenses: List[Path] = field(default_factory=list)
    removed_databases: List[Path] = field(default_factory=list)
    preserved_backups: List[Path] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    aborted_reason: str = ""


def resolve_executable_dir(explicit_exe_dir: Optional[Path] = None) -> Path:
    if explicit_exe_dir is not None:
        return Path(explicit_exe_dir).resolve()
    if getattr(sys, "frozen", False) or "__compiled__" in globals() or hasattr(sys, "__compiled__"):
        argv0 = Path(sys.argv[0]) if sys.argv else Path(sys.executable)
        return argv0.resolve().parent
    return Path.cwd().resolve()


def _find_pids_win32_snapshot(my_pid: int) -> List[int]:
    """Enumerate running Daqiq main processes using Win32 CreateToolhelp32Snapshot (never matches Troubleshooter)."""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return []
    found: List[int] = []
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            img = str(pe.szExeFile or "").lower().strip()
            pid = int(pe.th32ProcessID)
            if (
                "troubleshooter" not in img
                and (img == "daqiq.exe" or (img.startswith("daqiq_") and img.endswith(".exe")))
                and pid != my_pid
                and pid not in found
            ):
                found.append(pid)
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return found


def find_running_daqiq_pids(process_lister=None) -> List[int]:
    """Detect running Daqiq main executable processes (excluding Troubleshooter itself)."""
    if process_lister is not None:
        return list(process_lister())
    if sys.platform != "win32":
        return []
    pids: List[int] = []
    my_pid = os.getpid()
    try:
        proc = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip().strip('"') for p in line.split('","')]
                if len(parts) < 2:
                    continue
                image_name = parts[0].lower()
                if "troubleshooter" in image_name:
                    continue
                if image_name == "daqiq.exe" or (image_name.startswith("daqiq_") and image_name.endswith(".exe")):
                    try:
                        pid = int(parts[1])
                    except ValueError:
                        continue
                    if pid != my_pid and pid not in pids:
                        pids.append(pid)
    except Exception:
        pass
    try:
        for pid in _find_pids_win32_snapshot(my_pid):
            if pid not in pids:
                pids.append(pid)
    except Exception:
        pass
    return pids


def terminate_running_daqiq(pids: Optional[Sequence[int]] = None, terminator=None) -> List[int]:
    """Attempt to terminate running Daqiq.exe processes; returns remaining PIDs if any."""
    target_pids = list(pids) if pids is not None else find_running_daqiq_pids()
    if not target_pids:
        return []
    if terminator is not None:
        terminator(target_pids)
        return []
    my_pid = os.getpid()
    for pid in target_pids:
        if pid == my_pid:
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(int(pid))],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
    time.sleep(0.4)
    return find_running_daqiq_pids()


def is_backup_filename(name: str) -> bool:
    return any(pat.match(name) for pat in BACKUP_NAME_PATTERNS)


def _norm_key(p: Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _is_within(child: Path, parent: Path) -> bool:
    try:
        c_abs = Path(os.path.abspath(str(child)))
        p_abs = Path(os.path.abspath(str(parent)))
        return _norm_key(c_abs) == _norm_key(p_abs) or p_abs in c_abs.parents
    except Exception:
        return False


def _read_config_safely(path: Path) -> Dict:
    """Read app_config.json without failing on partial/corrupted JSON."""
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    # Fallback regex recovery so custom auto_backup_dir is STILL protected even on corrupted JSON!
    recovered: Dict = {}
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        for key in ("db_path", "auto_backup_dir", "backup_dir"):
            m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', raw)
            if m:
                recovered[key] = m.group(1).replace("\\\\", "\\")
        dirs = re.findall(r'"auto_backup_dir"\s*:\s*"([^"]+)"', raw)
        if dirs:
            recovered["databases"] = {
                f"recovered_{idx}": {"auto_backup_dir": d.replace("\\\\", "\\")}
                for idx, d in enumerate(dirs)
            }
    except Exception:
        pass
    return recovered


def _collect_protected_and_db_paths(
    config_files: Sequence[Path],
    exe_dir: Path,
    roaming_daqiq: Path,
    extra_db_search_dirs: Sequence[Path] = (),
) -> tuple[List[Path], List[Path], List[Path]]:
    """Pre-scan app_config.json before deletion to whitelist ALL backups and find active DBs."""
    protected_dirs_map: Dict[str, Path] = {}
    protected_files_map: Dict[str, Path] = {}
    db_files_map: Dict[str, Path] = {}
    candidate_db_parents: Set[Path] = set()

    def _add_protected_dir(p: Optional[str | Path]):
        if not p:
            return
        path_obj = Path(os.path.abspath(str(p)))
        protected_dirs_map.setdefault(_norm_key(path_obj), path_obj)

    def _add_candidate_db(p: Optional[str | Path]):
        if not p:
            return
        path_obj = Path(os.path.abspath(str(p)))
        candidate_db_parents.add(path_obj.parent)
        if is_backup_filename(path_obj.name):
            if path_obj.is_file():
                protected_files_map.setdefault(_norm_key(path_obj), path_obj)
            return
        if path_obj.is_file():
            db_files_map.setdefault(_norm_key(path_obj), path_obj)

    # Default Windows Documents\Daqiq folder if present
    docs_daqiq = Path.home() / "Documents" / "Daqiq"
    for default_root in (exe_dir, roaming_daqiq, docs_daqiq, *extra_db_search_dirs):
        if default_root.exists():
            candidate_db_parents.add(default_root)
            _add_protected_dir(default_root / "Backups")

    for cfg_path in config_files:
        cfg = _read_config_safely(cfg_path)
        if not cfg:
            continue
        _add_candidate_db(cfg.get("db_path"))
        for rec in cfg.get("recent_databases") or []:
            _add_candidate_db(rec)

        auto_dir = cfg.get("auto_backup_dir")
        if auto_dir:
            _add_protected_dir(auto_dir)

        dbs_map = cfg.get("databases")
        if isinstance(dbs_map, dict):
            for db_key, entry in dbs_map.items():
                if isinstance(db_key, str) and (os.sep in db_key or "/" in db_key):
                    _add_candidate_db(db_key)
                if isinstance(entry, dict) and entry.get("auto_backup_dir"):
                    _add_protected_dir(entry["auto_backup_dir"])

        bk_dir = cfg.get("backup_dir")
        if bk_dir:
            bk_path = Path(os.path.abspath(str(bk_dir)))
            candidate_db_parents.add(bk_path)
            if bk_path.name.lower() == "backups":
                _add_protected_dir(bk_path)

    # Also protect any <parent>/Backups and scan backup files inside candidate parents
    for parent in list(candidate_db_parents):
        if not parent.is_dir():
            continue
        _add_protected_dir(parent / "Backups")
        try:
            for item in parent.iterdir():
                if item.is_file() and is_backup_filename(item.name):
                    protected_files_map.setdefault(_norm_key(item), item)
        except OSError:
            pass

    for pdir in list(protected_dirs_map.values()):
        if pdir.is_dir():
            try:
                for item in pdir.rglob("*"):
                    if item.is_file():
                        protected_files_map.setdefault(_norm_key(item), item)
            except OSError:
                pass

    # Strict exclusion: any file inside a protected dir can NEVER be in database_files
    for k in list(db_files_map.keys()):
        p = db_files_map[k]
        if any(_is_within(p, pdir) for pdir in protected_dirs_map.values()):
            protected_files_map.setdefault(k, p)
            db_files_map.pop(k, None)

    return (
        sorted(protected_dirs_map.values(), key=lambda x: str(x).lower()),
        sorted(protected_files_map.values(), key=lambda x: str(x).lower()),
        sorted(db_files_map.values(), key=lambda x: str(x).lower()),
    )


def discover_troubleshooting_targets(
    *,
    executable_dir: Optional[Path] = None,
    local_app_data: Optional[Path] = None,
    roaming_app_data: Optional[Path] = None,
    program_data: Optional[Path] = None,
    temp_dir: Optional[Path] = None,
    process_lister=None,
) -> TroubleshootingPlan:
    """Scan all caches, configs, licenses/anchors, backups, and DB paths without modifying anything."""
    exe_dir = resolve_executable_dir(executable_dir)
    local_root = Path(local_app_data) if local_app_data else Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    roaming_root = Path(roaming_app_data) if roaming_app_data else Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    if program_data is not None:
        prog_root = Path(program_data)
    elif sys.platform == "win32":
        prog_root = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    else:
        prog_root = Path("/tmp")
    tmp_root = Path(temp_dir) if temp_dir else Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")

    local_daqiq = local_root / "Daqiq"
    roaming_daqiq = roaming_root / "Daqiq"
    program_daqiq = prog_root / "Daqiq"
    nuitka_root = local_root / "Nuitka"

    cfg_candidates = [
        exe_dir / "app_config.json",
        exe_dir / "app_config.json.tmp",
        roaming_daqiq / "app_config.json",
        roaming_daqiq / "app_config.json.tmp",
    ]
    config_files: List[Path] = []
    seen_cfg: Set[str] = set()
    for cf in cfg_candidates:
        nk = _norm_key(cf)
        if cf.is_file() and nk not in seen_cfg:
            seen_cfg.add(nk)
            config_files.append(cf)

    protected_dirs, protected_files, db_files = _collect_protected_and_db_paths(
        config_files, exe_dir, roaming_daqiq
    )

    cache_paths: List[Path] = []
    runtime_paths: List[Path] = []
    license_paths: List[Path] = []
    seen_targets: Set[str] = set()

    def _append_unique(target_list: List[Path], path_obj: Path):
        nk = _norm_key(path_obj)
        if nk not in seen_targets:
            seen_targets.add(nk)
            target_list.append(path_obj)

    if local_daqiq.is_dir():
        try:
            for child in sorted(local_daqiq.iterdir()):
                low = child.name.lower()
                if low in LEGACY_LICENSE_DIRS or low in LICENSE_AND_ANCHOR_FILES:
                    _append_unique(license_paths, child)
                elif low in ("logs", "cache", "qtwebengine", "qmlcache", "tmp", "qt"):
                    _append_unique(runtime_paths, child)
                else:
                    _append_unique(cache_paths, child)
        except OSError:
            pass

    if roaming_daqiq.is_dir():
        for sub_name in LEGACY_LICENSE_DIRS:
            cand = roaming_daqiq / sub_name
            if cand.exists():
                _append_unique(license_paths, cand)
        for fname in LICENSE_AND_ANCHOR_FILES:
            cand = roaming_daqiq / fname
            if cand.exists():
                _append_unique(license_paths, cand)
        for sub_name in ("logs", "cache", "tmp", "Qt"):
            cand = roaming_daqiq / sub_name
            if cand.exists():
                _append_unique(runtime_paths, cand)

    if program_daqiq.is_dir():
        _append_unique(license_paths, program_daqiq)

    if nuitka_root.is_dir():
        try:
            for child in sorted(nuitka_root.iterdir()):
                if child.name.lower().startswith("daqiq"):
                    _append_unique(cache_paths, child)
        except OSError:
            pass

    if tmp_root.is_dir():
        my_pid_tag = f"daqiqtroubleshooter_{os.getpid()}"
        try:
            for child in tmp_root.iterdir():
                low = child.name.lower()
                if low == my_pid_tag:
                    continue
                if low.startswith("daqiq_") or low == "daqiq":
                    _append_unique(cache_paths, child)
        except OSError:
            pass

    pids = find_running_daqiq_pids(process_lister=process_lister)
    return TroubleshootingPlan(
        executable_dir=exe_dir,
        local_app_daqiq=local_daqiq,
        roaming_app_daqiq=roaming_daqiq,
        config_files=config_files,
        cache_paths=cache_paths,
        runtime_paths=runtime_paths,
        license_paths=license_paths,
        protected_backup_dirs=protected_dirs,
        protected_backup_files=protected_files,
        database_files=db_files,
        running_pids=pids,
    )


def _is_path_protected(target: Path, plan: TroubleshootingPlan) -> bool:
    for pdir in plan.protected_backup_dirs:
        if _is_within(target, pdir):
            return True
    t_key = _norm_key(target)
    for pf in plan.protected_backup_files:
        if _norm_key(pf) == t_key:
            return True
    if target.is_file() and is_backup_filename(target.name):
        return True
    return False


def _safe_remove_path(target: Path, plan: TroubleshootingPlan) -> bool:
    if _is_path_protected(target, plan):
        return False
    if target.is_dir():
        for root, dirs, files in os.walk(str(target), topdown=False):
            for fname in files:
                fpath = Path(root) / fname
                if not _is_path_protected(fpath, plan):
                    fpath.unlink()
            for dname in dirs:
                dpath = Path(root) / dname
                if not _is_path_protected(dpath, plan):
                    try:
                        dpath.rmdir()
                    except OSError:
                        pass
        if not any(target.iterdir()):
            target.rmdir()
        return True
    if target.is_file():
        target.unlink()
        return True
    return False


def execute_troubleshooting_reset(
    plan: TroubleshootingPlan,
    *,
    delete_databases: bool = False,
    dry_run: bool = False,
    process_lister=None,
) -> TroubleshootingResult:
    """Execute cache/config reset and optional DB deletion while preserving every backup."""
    res = TroubleshootingResult(preserved_backups=list(plan.protected_backup_files))

    active_pids = find_running_daqiq_pids(process_lister=process_lister)
    if active_pids and not dry_run:
        res.aborted_reason = (
            "برنامه دقیق هم‌اکنون در حال اجرا است. ابتدا برنامه را ببندید و سپس دوباره تلاش کنید."
        )
        return res

    for cf in plan.config_files:
        if _is_path_protected(cf, plan):
            continue
        if dry_run:
            res.removed_configs.append(cf)
            continue
        try:
            if cf.is_file():
                cf.unlink()
                res.removed_configs.append(cf)
        except OSError as exc:
            res.warnings.append(f"حذف فایل پیکربندی ممکن نشد ({cf}): {exc}")

    for cp in plan.cache_paths:
        if _is_path_protected(cp, plan):
            continue
        if dry_run:
            res.removed_caches.append(cp)
            continue
        try:
            if cp.exists() and _safe_remove_path(cp, plan):
                res.removed_caches.append(cp)
        except OSError as exc:
            res.warnings.append(f"پاک‌سازی کش ممکن نشد ({cp}): {exc}")

    for rp in plan.runtime_paths:
        if _is_path_protected(rp, plan):
            continue
        if dry_run:
            res.removed_runtime.append(rp)
            continue
        try:
            if rp.exists() and _safe_remove_path(rp, plan):
                res.removed_runtime.append(rp)
        except OSError as exc:
            res.warnings.append(f"پاک‌سازی مسیر موقت ممکن نشد ({rp}): {exc}")

    for lp in plan.license_paths:
        if _is_path_protected(lp, plan):
            continue
        if dry_run:
            res.removed_licenses.append(lp)
            continue
        try:
            if lp.exists() and _safe_remove_path(lp, plan):
                res.removed_licenses.append(lp)
        except OSError as exc:
            res.warnings.append(f"پاک‌سازی فایل یا پوشه لایسنس ممکن نشد ({lp}): {exc}")

    if delete_databases:
        for dbp in plan.database_files:
            if _is_path_protected(dbp, plan):
                continue
            sidecars = [Path(str(dbp) + ext) for ext in ("", "-wal", "-shm", "-journal")]
            for sp in sidecars:
                if _is_path_protected(sp, plan) or not sp.is_file():
                    continue
                if dry_run:
                    if sp == dbp:
                        res.removed_databases.append(sp)
                    continue
                try:
                    sp.unlink()
                    if sp == dbp:
                        res.removed_databases.append(sp)
                except OSError as exc:
                    res.warnings.append(f"حذف فایل پایگاه داده ممکن نشد ({sp}): {exc}")

    return res
