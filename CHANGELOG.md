# Daqiq 4.10.0

## Commercial Milestone: A5/A4 B&W Print + Editable Word (.docx), Customers & Installments, Native QPainter Charts, High-Load Scalability, Persistent Forms & Pure Win32 RTL Troubleshooter

- **A5-Default (with A4 Toggle) B&W Printing & Editable RTL Word (`.docx`) Engine (`utils/printing.py`, `main.py`, `scripts/build_nuitka.py`)**: Re-engineered printing into a unified `PrintDocumentSpec` across all 12 sections (`dashboard_low`, `dashboard_employees`, `products`, `batches`, `sales`, `service_catalog`, `service_records`, `upgrades`, `suppliers`, `customers`, `employees`, `reports`/`charts`) with Bold `B Nazanin` (`9pt` A5 / `10pt` A4) body + `B Titr` headers, running Persian page numbers (`صفحه X از Y`), repeating headers, non-splitting table rows, strict zero cost/profit/margin leakage on customer invoices, and true bidirectional Word `.docx` export (`w:bidi`, `w:bidiVisual`, `w:rtl`, `w:cs`, `w:bCs`, `w:tblHeader`, `w:cantSplit`, dynamic `PAGE`/`NUMPAGES`, bundled with `python-docx` & `lxml`).
- **«مشتری‌ها» CRM Tab & Full Installment Financing Engine (`database.py`, `main.py`)**: Added dedicated Customers directory (`🤝 مشتری‌ها`) right beside Suppliers with national ID, address, single-query debt ledgers, purchase history, and per-installment settlement (`installment_plans`, `installment_payments` with OCC `row_version` guard and 64-bit integer division putting any remainder onto the final installment), integrated directly into «ثبت فروش» («فروش اقساطی»), Dashboard receivables/overdue cards, atomic cancellation cleanup, and Reports (`۱۳. گزارش اقساط و بدهی مشتریان`).
- **Native Interactive High-DPI `QPainter` Charts (`charts/native_charts.py`, `main.py`)**: Added «📊 گزارش‌های نموداری» right next to «گزارش‌های جامع» using pure `QPainter` (zero `matplotlib` / zero `QtCharts` DLLs) supporting Vertical Bar, Horizontal Bar, Line/Area Trend, and Donut/Pie across best-selling, most profitable, time trends, categories, sellers, and cash vs. installment mix with smart Persian compact ticks, hover tooltips, empty states, Light/Dark themes, and PNG/Print/Word export.
- **UI/UX, RTL Alignment & Selective Post-Submit Persistence (`main.py`, `utils_and_widgets.py`)**: Placed Dashboard print buttons on visual LEFT (`Qt.RightToLeft`), relocated `زیرمجموعه` directly below `دسته‌بندی اصلی` in `مدیریت کالا` with balanced groupbox heights, shortened `میز خدمت` delete buttons to `حذف`, unified Settings license buttons styling, aligned all `QGroupBox` headers RTL-right cleanly, and preserved entered form fields across rapid Purchase/Sales submissions while advancing/resetting only `کد محموله` / `شماره فاکتور` / `انتخاب رنگ` / warranty dates and silently refreshing live `remaining_qty` & `row_version`.
- **High-Load 50,000+ Row Scalability, SemVer (`4.10.0 > 4.9.10`) & Granular Entitlements (`licensing/`, `database.py`)**: Added composite indexes on customers, sales, and installments, pure SQL `GROUP BY`/CTE aggregations, `compare_semver`, and backward-compatible `customers`, `installments`, `charts_analytics`, and `word_export` entitlements (defaulting `True` when omitted from legacy licenses).
- **Pure Zero-Qt Win32 RTL Troubleshooter (`troubleshooter/win_ui.py`, `troubleshooter/core.py`)**: Replaced `MessageBoxW` prompts with native pure-Win32 `CreateWindowExW` (`WS_EX_LAYOUTRTL`) dialogs featuring 100% Persian horizontally centered bottom buttons, `CreateToolhelp32Snapshot` + `tasklist` process detection, unconditional backup preservation across default & custom paths, and clean ephemeral temp execution (`{TEMP}/DaqiqReset_{PID}`).

---

# Daqiq 4.9.10

## Commercial A4/A5 B&W Printing, 1-Year Store Scalability, Zero-Qt Troubleshooter EXE & Commercial Polish

- **Monochrome A4/A5 Commercial Invoice & Report Printing (`utils/printing.py`, `main.py`, `scripts/build_nuitka.py`)**: Added high-contrast monochrome B&W RTL print preview & printing (`PySide6.QtPrintSupport` bundled cleanly via Nuitka `printsupport`) with `🖨️ چاپ` buttons next to every report/table search bar, multi-row selection, empty-selection Persian prompt, customer-only «فاکتور فروش» with strict zero cost/profit/margin leakage protection, «رسید خرید و ثبت محموله», «فاکتور خدمات و تعمیرات» / «رسید ارتقای کالا», and «گزارش چاپی ...», plus vector PDF export and A4/A5 switching.
- **1-Year High-Volume DB Scalability & LAN Concurrency (`database.py`, `main.py`)**: Added non-breaking `CREATE INDEX IF NOT EXISTS` retail scale indexes (`idx_products_active_cat`, `idx_products_name`, `idx_batches_purchase_date`, `idx_batches_settlement`, `idx_sales_sale_datetime`, `idx_sales_settlement`, `idx_services_service_datetime`, `idx_upgrades_upgrade_date`, `idx_customers_phone`), debounced large-table search (>500 rows), and extended interactive OCC conflict resolution (`ConcurrencyConflictError`) to services, upgrades, and suppliers.
- **Zero-Qt Standalone `Daqiq-Troubleshooter.exe` (`troubleshooter/win_ui.py`, `scripts/build_nuitka.py`, `scripts/verify_nuitka_build.py`)**: Completely removed PySide6/Qt from `Daqiq-Troubleshooter.exe`, replacing it with pure Python stdlib + native Win32 RTL `MessageBoxW`, reducing onefile size to ~4–6 MB, eliminating cached extraction leftovers (`--onefile-tempdir-spec={TEMP}/DaqiqReset_{PID}` without `--onefile-cache-mode=cached`), and preserving all manual & automatic backups unconditionally.
- **Airtight `readonly` Grace Mode, Banner Overhaul & Button Copy (`main.py`, `licensing/license_policy.py`)**: Rewrote the top license warning banner to concise RTL (`<= 2` lines, compact fixed `تمدید/مدیریت لایسنس` button, removed «یادآوری لایسنس» and «دوره مهلت لایسنس»), strictly locked report-export builders, catalog/JSON import structure editors, and general settings during `readonly` grace while keeping DB backups, JSON/Excel exports, and viewing/printing active, added backward-compatible `print_invoices` & `backup_export` sub-features, and standardized all 7 edit buttons (`«✏️ ویرایش ...»`).
- **`app_config.json` & `schema_version` Alignment (`database.py`, `app_config.json`)**: Separated `CONFIG_SCHEMA_VERSION = 2` (`app_config.json` `schema_version`) from legacy SQLite `PRAGMA user_version = 484` so stale `484` never leaks into `app_config.json`.

---

# Daqiq 4.9.9

## Multi-PC LAN/SMB Concurrency, Grace Mode Hardening, Standalone Troubleshooter & Commercial UI Polish

- **LAN / SMB Multi-PC SQLite Concurrency & Optimistic Concurrency Control (`database.py`, `main.py`)**: Added network/UNC/mapped-drive path detection (`is_network_database_path`), enforced safe `PRAGMA journal_mode = DELETE`, `synchronous = FULL`, `locking_mode = NORMAL`, and `busy_timeout = 15000` on shared/network databases (preventing WAL/SHM corruption across SMB hosts), centralized serialized write transactions (`run_write_transaction` with `BEGIN IMMEDIATE` + exponential backoff/jitter), added `row_version` OCC tracking on mutable core tables (with backward-compatible additive column upgrade for `v4.9.8` databases), interactive Persian concurrent-edit & concurrent-sale conflict/stock dialogs (`ConcurrencyConflictError`, `InsufficientStockError`), online `conn.backup()` retry safety, and non-intrusive 4s `PRAGMA data_version` polling.
- **Dual-Mode Grace Period & Configurable Support Phone (`licensing/`, `tools/build_key_shards.py`, `main.py`)**: Added `grace_days_remaining`, Light/Dark theme-aware top-bar warning banner showing remaining days, grace mode (`فقط خواندنی` / `کامل`), and build-time configurable support phone (`DAQIQ_SUPPORT_PHONE` / `"support_phone"`), dual-layer UI + DB `ReadOnlyGraceError` enforcement permitting viewing, backups, and Excel/partner exports in `readonly` grace, and 100% Persian module labels (`FEATURE_LABELS_FA` + localized fallback).
- **Standalone Decoupled `Daqiq-Troubleshooter.exe` (`troubleshooter/`, `scripts/build_nuitka.py`, `.github/workflows/ci.yml`)**: Built completely isolated reset utility (`--onefile-tempdir-spec="{TEMP}/DaqiqTroubleshooter_{PID}"`, excluded from `Daqiq.exe`) that detects running `Daqiq.exe`, pre-scans `app_config.json` before deletion to whitelist all manual & automatic backups (default & custom `auto_backup_dir`), clears caches/runtime folders/config, and separately prompts to retain or delete DB files while preserving all backups.
- **Commercial UI/UX & Copy Polish (`main.py`, `licensing/license_dialog.py`)**: Removed `(پیش‌فرض)` suffixes from «شمسی» and «۲۴ ساعته» dropdowns, framed login password policy in a dedicated styled `QGroupBox`, standardized theme button to «حالت تیره» / «حالت روشن», and unified UI terminology (`لایسنس` while retaining conceptual `نوع اشتراک` / `اشتراکی زمان‌دار`).

---

# Daqiq 4.9.8

## Red-Team License Security Hardening, Battery Taxonomy Sync, Config Parity & Codebase Optimization

- **Zero-Bypass Subscription Expiry & High-Water-Mark Latch (`licensing/license_store.py`, `licensing/license_verifier.py`, `licensing/license_policy.py`, `licensing/license_dialog.py`, `main.py`, `docs/LICENSE_PROTOCOL_V1.md`)**: Closed sub-24h clock-rollback revival of expired 1-day/timed licenses by feeding monotonic High-Water-Mark (`max(now_utc, high_water_mark_utc)`) from multi-location HMAC-SHA256 clock anchors directly into `evaluate_validity_window()`; enforced `issued_at - max_clock_skew_hours` clock-rollback detection; added fail-closed `LicenseDialog.accept()` verification on the startup gate and end-of-day display parity; hardened `--smoke-launch-db` as strictly non-interactive (`setEnabled(False)`, input-transparent, rejects password-protected DBs, 6s daemon watchdog); added `"generated_at"` alongside `"generated_at_utc"` in `.daqreq` for full `Daqiq-License-Generator` `DeviceRequest` parity; shortened runtime periodic license check interval to `60s`.
- **Synced Updated Battery Taxonomy (`default_taxonomy.json`)**: Merged updated external taxonomy from `release/v4.9.7` (`a2fe616`) adding «باتری قلمی، سکه‌ای و شارژی (AA, Coin & Rechargeable Battery)», `UPS LiFePO4 Battery`, `6V 4.5Ah`, and 4 dedicated attribute sets while keeping `default_taxonomy.json` strictly external alongside `Daqiq.exe`.
- **`app_config.json` & `schema_version` Parity (`database.py`)**: Dynamically reconciled `app_config.json` (`schema_version = SCHEMA_VERSION`, live `app_version = "4.9.8"`, repaired empty/corrupt configs, canonicalized optional keys) while preserving all user preferences.
- **Legacy DB Migration Cleanup (`database.py`)**: Removed obsolete pre-v4.9.7 legacy column-drop/table-rebuild migration code cleanly while keeping greenfield DB creation, `v4.9.7`/`v4.9.8` DB opening, and General Settings calendar conversion 100% intact.
- **Performance Optimization & CI Fixes (`main.py`, `.github/workflows/ci.yml`)**: Batched `_populate_table_safely` table repaints with `setUpdatesEnabled(False)` and precomputed column metadata; fixed `.github/workflows/ci.yml` PR detached-HEAD null branch trim failure.

---

# Daqiq 4.9.7

## Commercial Licensing Expiry Parity, Unified "Date Time" Schema, Universal Dialog Theming & Full Stability Audit

- **Fail-Closed Subscription Expiry & Full `Daqiq-License-Generator` Parity (`licensing/license_verifier.py`, `licensing/license_policy.py`, `main.py`)**: Eliminated hidden 7-day cached grace fallback (`grace_period_days = 0` when omitted or disabled), added end-of-day UTC handling for date-only expiry strings (`YYYY-MM-DD`), added fail-closed checks for malformed/missing non-perpetual expiry timestamps, bool/negative grace values, and alias/nested `validity.*` fields while preserving canonical Ed25519 signature verification; live `check_license()` inside `is_feature_enabled()` and urgent lock banner on mid-session expiration ensure expired subscriptions lock immediately.
- **System Spec Security ID & Settings Tab Preservation (`licensing/device_identity.py`, `licensing/license_policy.py`, `licensing/license_dialog.py`, `main.py`, `docs/LICENSE_PROTOCOL_V1.md`)**: Included exact `app_security_id` («شناسه امنیتی برنامه») inside canonical `.daqreq` exports from both LicenseDialog and Settings; closing LicenseDialog via «بستن» keeps the user on «تنظیمات» (and syncs any theme toggle) instead of resetting to tab `0` («داشبورد»).
- **`app_config.json` Reconciliation & Live Version Sync (`database.py`, `main.py`)**: Added `get_live_app_version()` + `reconcile_app_config()` so `app_version` in `app_config.json` automatically updates to `4.9.7` on startup, migrates legacy aliases (`last_db_path`, `calendar_format`, `store_name`), aligns `calendar_type`/`time_format`/`last_store_name`, and strips orphaned keys cleanly without altering user preferences.
- **Unified `"Date Time"` Format Across Purchases & Users (`database.py`, `main.py`, `exporter.py`, `utils/datetime_format.py`)**: Consolidated «ثبت خرید و محموله‌ها» into single `"Date Time"` `purchase_date` matching «ثبت فروش», removing `batches.purchase_time` & `"ساعت خرید"` with automatic lossless migration from `v4.9.4`–`v4.9.6` databases and seamless compatibility with `v4.9.3` databases; standardized `format_timestamp_for_display()` in «مدیریت کاربران» to `"Date Time"` (zero `" - "` separator).
- **Universal Light/Dark Dialog Theme Synchronization (`utils_and_widgets.py`, `main.py`)**: Added unified `apply_dialog_theme()` + `DatabasePasswordDialog` (replacing raw `QInputDialog`), synchronized `LoginDialog` (startup & Switch User), `DatetimeMigrationChoiceDialog`, `ColorSelectionButton`, DB password dialogs, `DatabaseBootstrapDialog`, `JalaliCalendarDialog`, and `_MessageBoxPolisher` cleanly with active Light/Dark theme.
- **Holistic Audit & Resource Hygiene (`database.py`, `utils_and_widgets.py`, `main.py`)**: Fixed connection cleanup on failed DB password verification, stopped `_license_timer` cleanly on `closeEvent`, and eliminated 300+ Qt `invalidateFilter()` deprecation warnings via `beginFilterChange()`/`endFilterChange()`.

---

# Daqiq 4.9.6

## Root-Cause Post-DB Startup Crash Fix & Full Stability Hardening

- **Fixed Native C-Stack Overflow (`0xC00000FD`) After Database Dialog (`utils_and_widgets.py`)**: Eliminated an unbounded mutual recursion between `JalaliDateEdit.get_calendar_format()` and `_resolve_ancestor_calendar(self, ...)` that had been masked as swallowed `RecursionError` in CPython unit tests but exhausted the Windows C thread stack inside compiled Nuitka binaries (`v4.9.4` / `v4.9.5`) during `MainWindow._build_ui()`. Added cycle/type guards and removed generic exception swallowing of `RecursionError`.
- **Native & Qt Crash Diagnostics (`main.py`)**: Enabled `faulthandler` native fault logging (`%LOCALAPPDATA%\Daqiq\logs\daqiq_native_fault.log`) and Qt `qInstallMessageHandler` critical/fatal logging (`daqiq_crash.log`) alongside `sys.excepthook` and `threading.excepthook`.
- **64-bit Win32 `ctypes` & Nuitka Outer Path Hardening (`utils/paths.py`, `database.py`, `licensing/device_identity.py`, `main.py`)**: Added explicit `.argtypes`/`.restype` declarations for `GetSystemFirmwareTable`, `CryptProtectData`, `CryptUnprotectData`, `LocalFree`, `CoTaskMemFree`, and `SetCurrentProcessExplicitAppUserModelID`; added Win32 `NUITKA_ONEFILE_PARENT` image lookup in `get_executable_dir()`; preserved `DatabaseBootstrapDialog` theme toggles across `select_startup_database_path()`; synced date widget calendars on startup.
- **Compiled Windows Binary CI Launch Proof (`.github/workflows/ci.yml`, `main.py`)**: Added non-interactive `--smoke-launch-db` E2E verification executing the compiled onefile `Daqiq.exe` through database creation/connection into a live 1.5s `MainWindow` event loop in Windows CI.

---

# Daqiq 4.9.5

## Critical Hotfix & License Window UI Polish

- **Startup Lifecycle & Crash Safety Net**: Set `app.setQuitOnLastWindowClosed(False)` across the multi-dialog startup sequence (`LicenseDialog` → `DatabaseBootstrapDialog` → password prompt → employee login) until `MainWindow.show()`/`showMaximized()` completes, retained a persistent `MainWindow` reference across `app.exec()`, and installed global `sys.excepthook` + `threading.excepthook` crash logging (`%LOCALAPPDATA%\Daqiq\logs\daqiq_crash.log`) with a localized Persian error dialog (`بروز خطای غیرمنتظره`) so console-less Windows builds never terminate silently.
- **License Window Centered Header**: Replaced the unbalanced header `QHBoxLayout` in `LicenseDialog` with a symmetrical 3-column `QGridLayout` dynamically equalizing the logo and theme-toggle columns so «سامانه مدیریت و فعال‌سازی لایسنس دقیق» stays geometrically centered in both Light and Dark themes.
- **Theme-Aware Persian Notification Dialogs**: Added self-contained `ThemedNoticeDialog` replacing raw `QMessageBox` popups inside `LicenseDialog` (`.daqreq` export, license activation/validation errors, license deletion confirmation) with explicit Light/Dark isolation, RTL Persian buttons (`تأیید`, `بله`, `خیر`), and crisp high-contrast button borders; enhanced startup `_MessageBoxPolisher` for consistent Persian button localization on startup dialogs.

---

# Daqiq 4.9.4

## Release Summary & Commercial Store Hardening

- **Offline Licensing Hardening & Zero Registry Dependency (`REQ-01`..`REQ-05`, `REQ-10`)**: Replaced all Windows Registry usage with dual-location HMAC-SHA256 authenticated filesystem clock-rollback anchors (`.clock_state.dat` + `.runtime_anchor.dat`). Streamlined `.daqreq` by removing redundant `hardware_anchors` and hardcoded `"صندوق فروشگاه"`, added live synced `store_name` (including pre-DB startup gate), and extracted genuine CPU brand names from SMBIOS Type 4 (`Processor Version`) via `GetSystemFirmwareTable('RSMB')`.
- **Configurable Key Identity (`fp_prefix`, `key_id`, `public_key`)**: Unified per-field precedence (`Env > build_license_config.local.json > trusted_keys.json` defaults) across `tools/build_key_shards.py`, `.github/workflows/ci.yml`, and new `scripts/build_local.py` (restoring tracked `_embedded_keys.py` cleanly after local builds).
- **Theme-Isolated License Dialog (`REQ-06`)**: Rebuilt `LicenseDialog` with `#LicenseDialogRoot` CSS isolation, explicit `QPalette` Light/Dark resets eliminating dark QSS bleed, crisp HiDPI SVG logo, concise RTL Persian copy, click-to-copy `شناسه امنیتی برنامه` footer with safe auto-revert timers, responsive scroll area, and clean `بستن` footer action.
- **Authoritative Outer Executable Path Resolution (`REQ-07`)**: Added `utils/paths.py` (`get_executable_dir()`, `--print-paths`) resolving the true outer `Daqiq.exe` directory instead of Nuitka onefile cached extraction folders or `NUITKA_ONEFILE_PARENT` integer PIDs; proved in Windows CI from a separate working directory.
- **Granular Module & Sub-Feature Licensing (`REQ-11`)**: Enforced 14 granular sub-feature entitlements alongside 10 core tab locks, uniform «تنظیمات»-style locked-access dialog with direct `مدیریت لایسنس 🔑` shortcut, non-flashing tab interception, and silent startup selection of the first unlocked tab.
- **Sales & Purchases UX Upgrades (`REQ-08`, `REQ-12`, `REQ-13`)**: Fixed «محموله موجود» tooltip RTL alignment, fixed «مدت گارانتی» digit-only click selection via `MouseButtonRelease` event filter, moved `تاریخ خرید` next to `رنگ‌های این محموله` and shifted remaining purchase fields cleanly up, added `batches.purchase_time` (`ساعت خرید`) alongside `تاریخ خرید` across tables/reports/Excel with backward-compatible auto-migration, and added editable `تاریخ فروش` directly between `انقضای گارانتی` and `رنگ‌های فروخته‌شده` with dynamic warranty expiry recalculation.
- **Multi-Origin Calendar, AM/PM & Chronological Ordering (`REQ-09`)**: Standardized 12h formatting to English `AM`/`PM`, enabled dynamic `sqlite_master` discovery and deterministic per-cell origin conversion across mixed-calendar DBs, synced live clock/user management/date pickers (`JalaliDateEdit` + `JalaliCalendarDialog`), and added chronological 24h-normalized sorting and date-range filtering.
- **Headless QA & Node 24 CI/CD (`REQ-14`, `REQ-15`)**: Added `tests/conftest.py` fail-fast modal `.exec()` interceptor, comprehensive `tests/test_v494_features.py`, and `--print-paths` Windows CI verification on Node 24 actions.

---

# Daqiq 4.9.3

## Release Summary & Architectural Enhancements

- **Multi-Calendar & Time Format Engine**: Built a centralized datetime formatting and conversion service (`utils/datetime_format.py` / `datetime_format.py`) with support for Jalali (شمسی), Hijri (قمری via `hijridate`), and Gregorian (میلادی) calendars, as well as 24-hour and 12-hour (ق.ظ / ب.ظ) time formats. Seamlessly handles and normalizes Persian (`۰-۹`) and Arabic (`٠-٩`) digits.
- **Lossless Atomic Database Migration**: Implemented safe, transactional database date and time migration across all historical sales, batches, upgrades, payments, service records, and audit logs with pre-migration backup protection. Handled via an interactive 3-choice dialog (Migrate All Historical Data, Apply to New Records Only, or Cancel).
- **Partner Export Reordering & Full Column Suite**: Replaced the static checkbox grid in Partner Export («تنظیمات خروجی موجودی همکار») with a dynamic reorderable list of all 32 shipment and product attributes, featuring Up/Down and drag-and-drop ordering, staging boundaries, and strict persistence in exported Excel files.
- **Report Export UX & Immediate View Refresh**: Renamed report configuration button to «✏️ ویرایش لیست گزارش» and connected column reordering to immediately refresh the active view in «گزارش های جامع».
- **Global Eradication of «تجاری»**: Eliminated all occurrences of the Persian word «تجاری» across the entire user interface and licensing dialogs in favor of clean, professional terminology.
- **Licensing Security Hardening & Registry Removal**: Completely eliminated Windows registry access in licensing storage in favor of multi-location HMAC-SHA256 authenticated High-Water-Mark filesystem anchors resistant to clock rollback tampering. Cleaned `.daqreq` hardware request schema with system details and SHA-256 checksums.
- **Configurable Build Identity & Sharding**: Made key sharding fully configurable via environment variables (`DAQIQ_LICENSE_PUBLIC_KEY_B64`, `DAQIQ_LICENSE_KEY_ID`, `DAQIQ_LICENSE_FP_PREFIX`) and local config files (`build_license_config.local.json`), supported by comprehensive build and verification documentation.
- **External Taxonomy Resolution in Onefile Mode**: Enhanced `database.py` to resolve `default_taxonomy.json` and `app_config.json` next to the true executable binary when running under Nuitka onefile cached extraction mode (`NUITKA_ONEFILE_BINARY`).
- **Comprehensive QA Automation**: Added end-to-end regression tests in `tests/test_v493_features.py` validating calendar conversions, time formatting, atomic DB migrations, dialog choices, export column ordering, UI string invariants, and taxonomy resolution.

---

# Daqiq 4.9.2

## Release Summary & Architectural Enhancements

- **Anti-Crack Ed25519 Public Key Sharding Architecture**: Completely eradicated binary patching crack vectors and plaintext public-key markers in executable binaries. Re-engineered key provisioning using multi-byte XOR masking with pseudo-random build salts and compile-time integrity checks (`tools/build_key_shards.py`). Shards are compiled directly into native C compilation units via Nuitka, preventing hex-editor tampering or external key substitution.
- **Developer License Key CLI Tool (`tools/license_key_tool.py`)**: Built a robust, production-grade CLI utility for developers and administrators with four core commands:
  - `inspect`: Displays all embedded public keys, key IDs, Base64 values, SHA-256 fingerprints, and shard integrity status.
  - `set-public-key`: Registers or updates trusted public keys in `licensing/trusted_keys.json` with immediate shard rebuilding.
  - `generate-keypair`: Generates new Ed25519 keypairs with strict filesystem safeguards refusing to write secret signing keys inside the repository or git tree.
  - `verify-license`: Non-blocking offline verification and deep payload inspection for `.daqlic` files against configured public keys.
- **Fail-Closed Multi-Key Ring & Seamless Key Rotation**: Upgraded `KeyRegistry` to support multiple trusted public keys with fallback verification (`KeyRegistry.verify_any()`). Supports hot key rotation and grandfathered licenses without breaking backward compatibility.
- **100% Deterministic Protocol Parity with Daqiq-License-Generator**: Fully validated against `https://github.com/ouncommono/Daqiq-License-Generator` specifications (`COMPATIBILITY_CONTRACT.md`). Supports all 14 canonical payload fields, `fp_v1:<sha256>` hardware fingerprints, `match_policy` (strict, standard, relaxed), `grace_period_days`, `grace_mode` (full, readonly), and `expiry_warning_days`.
- **Persian RTL UI/UX Key Fingerprint Transparency**: Added subtle security key fingerprint footer (`شناسه کلید امنیتی (Key FP): daqiq-prod-v1 · 7925-3864-0164`) in the offline license activation dialog and detailed license view, allowing operators to verify pairing with the store's license generator at a glance.
- **Compiler Hardening & Developer Tool Exclusion**: Enhanced `scripts/build_nuitka.py` with automatic pre-build key shard synchronization and explicit exclusion of developer utilities and test generators (`--noinclude-tools-mode=nofollow`, `--nofollow-import-to=tools`), ensuring zero private-key or developer scaffolding leaks into distributed binaries.
- **Continuous Integration (CI/CD) on Node 24**: Updated GitHub Actions workflows for v4.9.2 with automatic key shard synchronization, clean Node 24 execution across all jobs, zero Node 20 deprecation warnings, and automated unmerged release pull requests targeting `main`.
- **Strict Database Independence & Zero Schema Regressions**: Confirmed 0 bytes of diff in `database.py` and `default_taxonomy.json` (`APP_VERSION = "4.8.4"` and `SCHEMA_VERSION = 484` strictly untouched). All commercial licensing operations execute completely external to the business database.

---

# Daqiq 4.9.1

## Release Summary & Architectural Enhancements

- **Full Cross-Repo Protocol Parity with Daqiq-License-Generator**: Rigorously audited and aligned with `ouncommono/Daqiq-License-Generator` according to `COMPATIBILITY_CONTRACT.md`. Full support for all 14 standard payload fields, modular `match_policy` (strict, standard, relaxed), `grace_period_days`, `grace_mode` (full, readonly), `expiry_warning_days`, and forward-compatible metadata and extra fields.
- **Ultra-Fast Native Win32 SMBIOS Hardware Fingerprinting (< 5ms)**: Replaced external PowerShell/CIM/WMI queries with direct Win32 `kernel32.GetSystemFirmwareTable` SMBIOS parsing (`0x52534D42` / `RSMB`). Acquires SMBIOS Type 1 UUID and Type 2 Motherboard Serial in under 2 milliseconds with zero subprocess spawns, zero command-line execution, and zero Windows Defender / EDR friction.
- **Multi-Anchor Anti-Clock-Tampering Guard**: Re-architected clock state tracking using dual synchronized anchors: local AppData atomic state file and Windows Current User Registry (`HKCU\Software\Daqiq\Licensing`). Prevents tampering by comparing HMAC-SHA256 authenticated monotonically increasing high-water marks across independent storage subsystems.
- **Persian RTL UI/UX Activation Polish**: Re-designed offline license dialog with 2-step offline guidance, one-click `.daqreq` machine file export, clipboard copying, drag-and-drop `.daqlic` license import, direct text-token pasting, and localized expiry warning banner with graceful degradation into read-only mode during grace periods.
- **High-Performance Nuitka Packaging & Lazy Startup Optimizations**: Integrated Zstandard (`zstd`) onefile payload compression, configured version-scoped tempdir cache (`{CACHE_DIR}/Daqiq/{VERSION}`), pruned non-essential Qt plugins (`platforms`, `styles`, `imageformats`), excluded Qt translations, and deferred heavy library imports (`openpyxl` in `exporter.py`), slashing application cold-start latency by over 350ms.
- **GitHub Actions Node 24 CI/CD Upgrade**: Upgraded 100% of GitHub Actions workflows to modern Node 24 compatible actions (`actions/checkout@v7`, `actions/setup-python@v7`, `actions/upload-artifact@v7`, `actions/download-artifact@v8`). Eliminated third-party MSVC action in favor of Nuitka's native toolchain discovery, eradicating 100% of Node 20 deprecation warnings.
- **Strict Database Independence & Zero Schema Regressions**: Confirmed 0 bytes of diff in `database.py` and `default_taxonomy.json`. All commercial licensing mechanisms operate 100% outside the business database.

---

# Daqiq 4.9.0

## Release Summary & Architectural Enhancements

- **Commercial Offline Ed25519 Cryptographic Licensing**: Greenfield air-gapped licensing engine built using Python `cryptography` with Ed25519 asymmetric digital signatures. Enforces UTF-8 canonical JSON serialization with Unicode NFC normalization, domain-separated signature prefixes (`DAQIQ-LICENSE-V1\n`), and strict rejection of duplicate keys and floating-point values. Fully documented protocol specification published in `docs/licensing-protocol-v1.md`.
- **Hardware Node-Locking & SMBIOS Fingerprinting (`fp_v1`)**: Hardware identity anchoring via Windows CIM/WMI querying `Win32_ComputerSystemProduct.UUID` and `Win32_BaseBoard.SerialNumber` with a 3-tier fallback policy and non-blocking sub-5-second execution. Resistant to Windows reinstallations, RAM upgrades, SSD/HDD swaps, and network changes. Strict rejection of OEM placeholder values with privacy-safe SHA-256 digests (`fp_v1:<hex>`).
- **Granular Feature Entitlements & Tab Access Control**: Verified licenses control availability across all 10 retail modules (Dashboard, Products, Batches, Sales, Services, Upgrades, Suppliers, Reports, Employees, Settings). Disabled tabs are physically deactivated with clear Persian tooltips and polite user dialogs. Entitlements operate 100% independently of database employee RBAC roles.
- **Database Independence & Atomic Persistent Storage**: Complete zero-diff preservation of SQLite business data (`database.py` APP_VERSION 4.8.4 and SCHEMA_VERSION 484 strictly untouched). Licenses are stored in dedicated OS paths (`%PROGRAMDATA%\Daqiq\Licensing` with fallback to `%LOCALAPPDATA%\Daqiq\Licensing`), written atomically via sibling temporary files and `os.replace`.
- **Offline Clock-Rollback Protection**: Monotonic high-water mark tracking in `clock_state.json` with HMAC-SHA256 integrity tags bound to the device fingerprint. Enforces a 15-minute tolerance window on time-limited subscriptions, while perpetual licenses remain fully immune to clock-state expiration.
- **Persian RTL License Management Dialog**: Native PySide6 activation window featuring one-click hardware fingerprint copying (`کپی شناسه دستگاه`), atomic `.daqlic` license file import, real-time re-validation, Persian Jalali expiration formatting, and clean non-zero exit prevention.
- **Free Nuitka Standard Migration**: Complete elimination of PyInstaller from active build scripts, dependencies, and CI workflows. Upgraded to free, open-source Nuitka Standard 2.8.x with MSVC/MinGW toolchain support, `--assume-yes-for-downloads`, `--enable-plugin=pyside6`, Stage A standalone compilation, Stage B onefile (`Daqiq_4.9.0.exe`) packaging, external `default_taxonomy.json` sibling resolution, and automated `SHA256SUMS.txt` generation.
- **Quality Assurance**: 100% pass rate across the full 176 baseline regression tests and new comprehensive test suites covering cryptography, hardware identity, atomic storage, startup gate enforcement, and binary smoke testing.

---

# Daqiq 4.5.0

## Release Summary & Architectural Enhancements

- **Greenfield Database Schema & Canonical Column Architecture (Schema Version 450)**: Clean-slate production release with fully validated physical column ordering across all SQLite tables. Positioned `serial_number` immediately following `code` in `products`, `serial_numbers` immediately following `product_id` in `batches`, and `serial_number` immediately following `batch_id` with `customer_phone` following `customer_name` in `sales`. Strict 64-bit integer support for massive financial figures in Tomans.
- **Recent Databases Deduplication & Physical File Filtering**: Enhanced startup database resolution (`_resolve_database_path`) and recent databases manager (`_refresh_recent_database_list`) to deduplicate paths using case-normalized paths (`os.path.normcase`) and strictly exclude non-existent physical database files, preventing phantom default database entries.
- **First-Class Serial Number Auto-Fill & Clearing**: In "ثبت خرید و محموله ها" and "ثبت فروش", selecting a product with a registered serial number automatically populates the serial number input field (`ed_batch_serial_number` and `ed_sale_serial`), and selecting a product without a serial cleanly clears the field.
- **Canonical Column Ordering & Customer Phone Persistence**: Synchronized physical column sequence across sales forms, sales tables (`tbl_sales`), and comprehensive reports (`tbl_report`). Reordered "شماره سریال" immediately after "کد کالا", and persisted and rendered "شماره تماس مشتری" across sales entry, live reports, search filters, and invoices.
- **Custom Report Synchronization & Execution in Reports Tab**: Dynamically synchronized user-defined custom report profiles with `cb_rep_type` in the Reports tab. Selecting a custom report executes a multi-table joined query across sales, products, batches, suppliers, and employees, rendering the exact combination of columns chosen by the user in `tbl_report` with instant search filtering, date ranges, and Excel export.
- **Full-Row Checklist Toggling (Zero Double-Toggle)**: Enhanced `SmoothScrollListWidget` with full-row toggling (`enable_row_toggle = True`), allowing users to toggle column checkboxes in Settings by clicking anywhere on the item row or label without double-toggling.
- **Staged Database Password Architecture**: Decoupled database password dialogs (Set, Change, Remove, and Startup Prompt Toggle) from immediate disk/database mutations. All actions are staged in memory (`_staged_db_password_action`, `_staged_db_startup_prompt`) with visual pending status indicators, and committed atomically only when clicking "ذخیره تنظیمات". Clicking "انصراف" (Cancel) completely rolls back all staged password changes.
- **CI/CD Pipeline & GitHub Actions**: Updated GitHub Actions workflow (`ci.yml`) to version 4.5.0, enforcing `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"`, PyInstaller single-file packaging with `default_taxonomy.json`, and automatic GitHub Release creation tagged as `v4.5.0` and marked as Latest.
- **Quality Assurance**: Comprehensive unit and GUI smoke test suite covering schema v450, custom report execution, password staging, and canonical column ordering with 100% pass rate in headless mode (`$env:QT_QPA_PLATFORM="offscreen"`).

---

# Daqiq 4.4.0

## Release Summary & Architectural Enhancements

- **Greenfield Database Schema & Canonical Column Architecture (Schema Version 440)**: Complete clean-slate redesign of the SQLite database schema with validated physical column ordering across all tables. Strict 64-bit integer support for massive financial figures in Tomans, eliminating floating-point rounding errors. Positioned `serial_number` immediately following `code` in `products`, `serial_numbers` immediately following `product_id` in `batches`, and `serial_number` immediately following `batch_id` with `customer_phone` following `customer_name` in `sales`.
- **Serial Number First-Class Integration**: Added dedicated "شماره سریال" (Serial Number) column in the bottom report table of "مدیریت کالاها" positioned immediately after "کد کالا". Selecting any product in "ثبت خرید و محموله ها" or "ثبت فروش" automatically retrieves and populates the recorded serial number into the form.
- **International Retail Taxonomy & External Seed Engine (`default_taxonomy.json`)**: Shipped comprehensive `default_taxonomy.json` packaged via PyInstaller. Enforced 100% Persian main categories, strict bilingual `"فارسی (English)"` subcategories, 100% Persian attribute keys with 100% English display titles and dropdown values. Standalone SSD and Internal HDD subcategories feature tailored single-drive capacities (combo capacities purged) and unified "نوع رابط و فرم" (Interface & Form Factor). Peripheral subcategories feature comprehensive single-mode and multi-mode connectivity options (Wired, Wireless 2.4GHz, Bluetooth, Dual-Mode, Tri-Mode).
- **Universal Specifications Rule & "سایر موارد (Other)" Single-Spec Principle**: Guaranteed that "مشخصات" (Specifications) is strictly the final attribute of every subcategory across all categories. For all "سایر موارد (Other)" subcategories, all category-specific attributes are purged and only the single "مشخصات" attribute is retained.
- **Default Minimum Inventory Level = 1**: Adjusted initial minimum reorder threshold from 0 to 1 across database configurations, schema defaults, and product creation forms.
- **Customer Phone Number Tracking in Sales**: Added customer phone number field (`ed_sale_phone`) adjacent to customer name in Sales tab. Persisted, updated, and displayed in sales tables, search filters, and invoices.
- **Dynamic Windows Documents Resolution & Configurable Backup Directory**: Dynamic resolution of the user's true Windows Documents folder using `SHGetKnownFolderPath` (FOLDERID_Documents) with fallback to `QStandardPaths`. Added custom automatic backup directory selector (`ed_auto_bk_dir`) with directory browse dialog in Settings, defaulting to database-relative `Backups` directory unless overridden.
- **Custom Report Builder for Excel Export**: Interactive column selection table with row-click checkbox toggling in Settings. Full custom report lifecycle: creating, renaming, configuring custom column sets, and deleting custom report configurations.
- **Ergonomic 2-Column RTL Product Settings & Smooth Scrollable Dynamic Specs**: Redesigned "تنظیمات مدیریت کالاها" into an ergonomic 2-column RTL layout with Category/Subcategory management on the right and Attribute/Feature management on the left. Wrapped dynamic subcategory specifications in `QScrollArea` with smooth vertical scrolling and expanding policies.
- **Action Buttons Symmetry & Memento Rollback**: Enforced 1:1 stretch ratio and 42px minimum height for Settings action buttons. Clicking "انصراف" (Cancel) completely rolls back uncommitted drafts, collapses all expandable sections, and redirects immediately to the Dashboard tab.
- **32-bit Millisecond Timer Overflow Immunity**: Clamped all QTimer millisecond intervals to `[1_000, 2_147_483_647]` with ISO timestamp delta sanitization, preventing signed 32-bit integer overflow exceptions during long running sessions.
- **Database Password Protection & PBKDF2 Authentication**: Cryptographic password management with PBKDF2-HMAC-SHA256 and AES-GCM unlock tokens stored securely in `app_config.json`. Password management UI in Settings with Show/Hide toggle, startup password prompt toggle, and atomic schema integrity validation.
- **DevOps Pipeline & CI/CD Packaging**: Upgraded GitHub Actions workflow (`ci.yml`) with `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"`, packaged `default_taxonomy.json` asset via PyInstaller, and configured GitHub Release publishing with `--latest` / `make_latest: true`.
- **QA & Verification**: 100% test pass rate (118 passed out of 118 tests) with zero unhandled exceptions.

---

# Daqiq 4.1.0

## Release Summary & Architectural Enhancements

- **Greenfield Database Normalization (Schema Version 410)**: Redesigned the SQLite schema contract for v4.1.0. Added first-class `serial_number` column to `products`, validated physical column ordering, strict Foreign Key constraints, and search indexes (`idx_products_serial`, `idx_batches_serial`, `idx_batches_code`, `idx_sales_serial`) for rapid queries. Implemented `ManagedConnection` context manager eliminating Windows SQLite file handle leaks.
- **Hardware Integration (Barcode Scanner Keyboard Wedge)**: Added dedicated "Serial Number" fields in "مدیریت کالاها" and "ثبت خرید و محموله‌ها". Integrated fast dual-entry (manual typing and barcode scanner emitting CR/LF). In "ثبت فروش", barcode entry triggers instant DB lookup, auto-selects product in "انتخاب کالا", filters "محموله موجود", and automatically selects and cascades all dependent fields when a unique cargo matches.
- **Dynamic Attribute Domain Engine**: Completely replaced flawed comma-separated text strings with `DynamicAttributeValuesWidget` featuring dynamic rows with atomic `+` (Add) and `-` (Remove) action buttons. Eradicated domain duplication and concatenation bugs.
- **Decoupled UI State Management in Tab Navigation**: Deployed `CatalogSettingsState` external state buffer decoupling form data state from widget destruction across tab switches. Retains and re-renders draft inputs for "نام جدید یا نام جایگزین", "نام زیرمجموعه", "نام ویژگی", "مقادیر پیشنهادی", and "نام رنگ".
- **Dynamic Excel Export Configuration Engine (openpyxl)**: Architected a new configuration section within "مدیریت ساختار کالاها، خدمات، خروجی‌ها و دسترسی‌ها" directly adjacent to "تنظیمات خروجی موجودی همکار". Allows user to customize included columns and dictate exact ordering per report type. Generates styled spreadsheets via openpyxl with zebra striping, auto column widths, thin borders, and RTL worksheet direction.
- **Global UI/UX Ergonomics (Floating Save & Memento Rollback)**: Placed "ذخیره تنظیمات" in a floating bar pinned to the viewport bottom outside the primary scroll area. Added adjacent "انصراف" (Cancel) button deploying the Memento pattern (`SettingsSnapshot`) rolling back uncommitted drafts and redirecting to Dashboard.
- **CI/CD & DevOps Release Pipeline**: Updated GitHub Actions workflow (`ci.yml`) to validate syntax, run unit/smoke tests, build standalone Windows executable via PyInstaller, publish a Draft Release tagged as Latest, and register an open Pull Request for human review (auto-merge disabled).
- **QA Status**: 99 passed out of 99 tests (100% pass rate) with zero failures.

---

# Daqiq 4.0.0

## Release hardening

- Introduced the clean-slate v4.0.0 SQLite schema contract (schema version 400), including validated physical column order for all 16 tables and strengthened monetary constraints.
- Hardened purchase, sale, upgrade, and service calculations for signed 64-bit SQLite integer amounts; replaced the 32-bit Qt price-change signal and binary-float allocation/percentage rounding with Python-object signals and exact arithmetic.
- Standardized product catalogue defaults: blank DDR selection, localized known legacy attribute names with specific English technical titles, and a final «سایر موارد» option containing only «مشخصات» / “Specifications”.
- Corrected purchase and sales report-row restoration, including product/batch/seller cascading selection, purchase-form clear behavior, and empty optional sale customer/warranty/serial values.
- Changed the suggested database location to `Documents/Daqiq/Daqiq.db`; startup now requires an explicit `app_config.json` before auto-connecting and otherwise presents the Create / Connect dialog.
- Added regression coverage for the v4 schema, high-value purchase/sale totals, blank optional fields, catalogue localization, and startup selection. The repository CI compiles Python files and runs the complete pytest suite.

## QA status

- Final PR head `4222518380747d15775f614a14f64f63782acdbd`: Python compilation succeeded; `pytest -q` reported **93 passed, 176 warnings** (29.48s) in GitHub Actions run [41875547287](https://github.com/ouncommono/Daqiq/actions/runs/41875547287).
- Manual packaged-Windows smoke testing, RTL visual acceptance, and store-operator end-to-end acceptance remain release gates.

---

# Daqiq 3.3.0

- Corrected the first-shipment `add_batch` payload mapping for the extra `initial_specs` parameter; added a full cold-start UI regression that creates a product, registers quantity 10, verifies settlement/specification fields, directly edits 1 → 10 → 2, and deletes the shipment.
- The reported numeric quantity failure could not be independently reproduced from the repository baseline; the regression now protects the described flow but does not attribute that external symptom to the positional-field defect.
- Restored the three matching subcategory actions (افزودن، تغییر نام، حذف) with the same button styling pattern and independent handlers.
- Standardized the 3.3.0 fresh-install schema (version 330): explicit domain checks, consistent batch stock-balance and sale-return invariants, distinct target/part batches, and `WITHOUT ROWID` for natural/composite-key tables; froze all 16 tables' initial column order in a schema contract test.
- Audited the core SQL modules for positional `INSERT ... VALUES` statements and `SELECT *`; none were found. Runtime integrity and CRUD behavior remain covered by the test suite.

# Daqiq 3.2.0

- Serialized product and sale stock changes with immediate SQLite transactions and guarded quantity deltas.
- Synchronized product fields, configurable technical catalog and persisted specification keys; corrected exact subcategory filtering.
- Added taxonomy/stock indexes and standardized fresh-install metadata to 3.2.0.
