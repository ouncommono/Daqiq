# Daqiq 4.2.0

## Release Summary & Enterprise Architectural Refactoring

- **Clean Slate Normalized Database Architecture (Schema Version 420)**:
  - Greenfield SQLite schema v420 discarding legacy migrations for a fully normalized, high-performance architecture.
  - Prioritized table column sequencing upon creation: `serial_number` is placed immediately after `id` in `products`, followed by logical identifier fields.
  - Added indexed customer contact phone (`customer_phone`) in `sales` table (`idx_sales_customer_phone`) and dedicated search indexing.
  - Advanced Cryptographic Database Security: Optional AES-256-GCM authenticated encryption with PBKDF2 key derivation (HMAC-SHA256, 256,000 iterations, 16-byte DAQIQ_ENC_V1 envelope) and SQLCipher compatibility without data loss.

- **Explicit Serial Number Observer Pattern & Visibility**:
  - Rendered "شماره سریال" (Serial Number) explicitly as a standalone distinct column in `tbl_products`, `tbl_batches`, and `tbl_sales`.
  - Implemented automatic trace/observer watcher on product comboboxes in both "ثبت خرید و محموله‌ها" and "ثبت فروش": selecting a product dynamically queries the database and auto-populates the Serial Number field.
  - Reordered form field inputs across "مدیریت کالاها", "ثبت خرید و محموله‌ها", and "ثبت فروش" so Serial Number is logically the VERY FIRST input field in row 0.

- **Dynamic Feature Sets, Taxonomy Standardization & Bilingual Search Support**:
  - Standardized main categories purely in Persian.
  - Standardized subcategories strictly adhering to the bilingual `فارسی (انگلیسی)` format for international search indexing (e.g., `رم کامپیوتر (RAM PC)`, `حافظه اس‌اس‌دی (SSD)`).
  - Feature Data Schema: Persian keys ("نام ویژگی"), English display labels ("Display Names"), and English dropdown values.
  - Tailored dynamic specification logic:
    - "لپ‌تاپ": "مشخصات" (Specifications) exists across all subcategories; "سایر موارد (Other)" strictly retains ONLY "مشخصات".
    - "حافظه اس‌اس‌دی (SSD)" vs "هارد دیسک اینترنال (Internal HDD)": Independent tailored capacity lists (SSD: 120GB to 8TB; HDD: 160GB to 16TB); merged duplicate interface fields into a single dynamic "نوع رابط" field.
    - "قطعات": Removed duplicate "مشخصه" in favor of unified "مشخصات" across all subcategories.
    - "لوازم جانبی": Expanded "نوع اتصال / پورت" to modern multi-mode connections (Wired + Wireless, Wired + Bluetooth, etc.); mouse connectivity formatted consistently.
    - Global Taxonomy Invariant: Across all categories, "مشخصات" is present on all subcategories, and only "مشخصات" exists on "سایر موارد".

- **Customer Contact Data Integration**:
  - Added mandatory "شماره تماس مشتری" (Customer Contact Number) field in "ثبت فروش".
  - Enforced strict validation preventing sale completion without customer contact details.
  - Propagated customer contact number system-wide: persisted in database `sales` table, displayed in bottom sales grids, and exported in reporting views.

- **Configurable Default Inventory & Margins**:
  - Hardcoded default for "حداقل موجودی" (Minimum Stock) set to 1.
  - Added UI configuration control in application settings directly beneath "درصد سود پیش‌فرض فروشگاه (%)" to dynamically configure and persist `cfg["default_min_stock"]`.

- **Dynamic Backup Directory & System Sleep Overflow Fix**:
  - Implemented dynamic backup save path configuration with folder picker in settings, persisted to `cfg["backup_dir"]`.
  - Fixed Qt 32-bit signed timer `OverflowError` after PC sleep/wake: abolished long-duration timer and implemented a robust 60,000ms polling heartbeat timer comparing `time.time() >= self._target_backup_time`.

- **Excel Export UX & Custom Reporting**:
  - Enhanced column selector list in "تنظیمات خروجی اکسل گزارش‌ها": clicking row label text toggles item checkbox state.
  - Added "نام گزارش" input field to save and rename custom report layouts.
  - Expanded available export fields to include Serial Number and Customer Contact Number across comprehensive reports.

- **Card Frame Modern UI/UX Paradigm & Collapsible Sections**:
  - Redesigned "مدیریت کالاها" using card frame containers with consistent grid padding, 12px margins, and clear visual hierarchy.
  - Balanced, proportionate, and responsive "انصراف" and "💾 ذخیره تنظیمات" action buttons.
  - Clicking "انصراف" safely collapses (`.collapse()`, `.pack_forget()`, `.grid_forget()`) all expanded accordion menus in settings.
  - Handled CustomTkinter asset bundling for PyInstaller builds (`sys._MEIPASS` and `--collect-all customtkinter`).

- **CI/CD Pipeline & GitHub Release**:
  - Added `.github/workflows/release.yml` with PyInstaller executable build, `softprops/action-gh-release@v2` targeting `Latest` tag, and `permissions: contents: write`.
  - Prepared release branch `release/v4.2.0` with pull request targeting `main` (auto-merge disabled).

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
