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
