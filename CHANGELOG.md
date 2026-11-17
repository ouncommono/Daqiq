# Daqiq 4.3.0

## Release Summary & Architectural Enhancements (Final Enterprise Production Release)

- **Greenfield Database Normalization (Schema Version 430)**: Complete architectural redesign of the SQLite database schema for clean-slate production deployment. Standardized physical column ordering across all domain tables (`products`, `batches`, `upgrades`, `sales`) placing `serial_number` (`شماره سریال`) as the primary domain column immediately following `id`. Eradicated fragile positional column indexing and legacy migration shims in favor of explicit named column mapping and `sqlite3.Row` dictionary factories.
- **Product Management Serial Number Integration**: Integrated "شماره سریال" (Serial Number) as the first data column in the bottom inventory summary table (`tbl_products`) in "مدیریت کالاها". Add, edit, filter, search, and selection operations dynamically bind and refresh the serial number in real time.
- **International-Standard Bilingual Taxonomy Overhaul**:
  - **Main Categories**: 100% Persian standard naming (`لپ تاپ`, `کیس و سیستم آماده`, `قطعات`, `ذخیره ساز و حافظه`, `مانیتور و نمایشگر`, `لوازم جانبی`, `تجهیزات شبکه`, `ماشین های اداری`, `کابل و مبدل`, `سایر موارد`).
  - **Subcategories**: Strict bilingual format `"فارسی (English)"` across all categories with seamless bilingual substring filtering and search.
  - **Attribute Specifications**: Persian internal UI labels, 100% English display names and technical dropdown values.
  - **Hardware Specifics**: Dedicated single-drive capacities for standalone SSDs and Internal HDDs (dual-drive combos removed); unified `رابط و فرم` (`Interface & Form Factor`); single and multi-mode connectivity options (`Wired`, `Wireless 2.4GHz`, `Bluetooth`, `Tri-Mode Multi-Mode`); non-electronic tailored attributes for bags and backpacks (`نوع کاربری`, `سایز مناسب لپ تاپ`, `جنس و مقاومت`).
  - **Universal Specification Contract**: `مشخصات` (`Specifications`) is enforced as the final field across all subcategories; `سایر موارد (Other)` contains exclusively the `مشخصات` attribute.
- **Default Minimum Stock Configuration**: Configurable default minimum stock threshold (`default_min_stock`, default: `1`) added to "تنظیمات عمومی فروش و نمایش" (`sp_set_default_min_stock`) directly below the default profit setting. Form reset actions automatically initialize `reorder_point` to this configured default.
- **Cargo & Sales Serial Auto-fill with Re-entrancy Protection**: Dedicated `serial_numbers` column in `tbl_batches`. Product selection in "ثبت خرید و محموله‌ها" and shipment selection in "ثبت فروش" automatically cascades and populates the matching serial number. Serial barcode scanner inputs immediately resolve and select corresponding products and cargo. Protected by `_syncing_serial` re-entrancy flag preventing signal recursion.
- **Customer Phone Integration**: Added `customer_phone` (`شماره تماس مشتری`) to the sales creation form, sales table (`tbl_sales`), sales reports, search pools, and Excel spreadsheet exports.
- **Customizable Automatic Backup Directory**: Added configurable automatic backup directory with dedicated native folder browser (`QFileDialog.getExistingDirectory`). Validates directory write permissions with graceful fallback to default `Backups` and clear UI status badges.
- **Excel Report Export Settings Overhaul**:
  - Full-row click toggle for column selection list (`itemClicked` -> `_toggle_report_export_col_item`).
  - Custom report profile management: full CRUD capabilities to create (`_add_custom_report_profile`), rename (`_rename_custom_report_profile`), and delete (`_delete_custom_report_profile`) custom report configurations.
  - Expanded column selection pools across all available report types.
- **Product Management Three Visual Cards Layout**: Re-engineered "مدیریت کالاها" into 3 distinct visual cards:
  1. Card 1 (`gb_prod_identity`): Core identity and catalog parameters (`شماره سریال`, `کد کالا`, `دسته‌بندی`, `برند`, `مدل`).
  2. Card 2 (`gb_prod_specs`, `specs_scroll`): Dynamic hardware specifications contained within a smooth scroll area.
  3. Card 3 (`gb_prod_inventory`): Inventory, reorder point, profit percentage, and notes.
- **Settings Viewport Ergonomics & Memento Rollback**: Equalized "ذخیره تنظیمات" (Save) and "انصراف" (Cancel) button proportions (42px height, 50/50 horizontal expanding stretch). Cancel cleanly discards uncommitted drafts, programmatically collapses all collapsible sections via `collapse()`, resets pending security inputs, and returns the operator to the Dashboard.
- **Backup Timer Overflow Protection & Clean Lifecycle**: Hardened `_restart_backup_timer` with integer boundary guards `min(..., 2_147_483_647)` eliminating signed 32-bit millisecond overflow. Implemented `closeEvent` lifecycle cleanup guaranteeing timer termination and database flush on application exit.
- **Enterprise Database Encryption (PBKDF2-HMAC-SHA256 + AES-256-GCM)**: Full authenticated encryption for SQLite database files (`MAGIC_ENCRYPTION_HEADER = b"DAQIQ_ENC_V1\x00\x00\x00\x00"`). Decrypts on demand into an isolated temporary runtime database, flushing atomically back to persistent disk. Introduced `DatabaseUnlockDialog` for startup and database switching, complete with password modification and removal workflows in Settings.
- **DevOps CI/CD Modernization (Node 20+)**: Upgraded `.github/workflows/ci.yml` to Node 20+ native actions (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`, `actions/download-artifact@v4`, `softprops/action-gh-release@v2`), pinned version `4.3.0`, and bundled `cryptography` dependency for PyInstaller production builds.
- **QA Status**: 110 passed out of 110 tests (100% pass rate) with zero regressions across `test_database_contracts.py`, `test_release_v4.py`, `test_release_v4_1.py`, `test_release_v4_3.py`, and `test_ui_smoke.py`.

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
