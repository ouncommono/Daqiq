# Daqiq 4.0.0

## Release hardening

- Introduced the clean-slate v4.0.0 SQLite schema contract (schema version 400), including validated physical column order for all 16 tables and strengthened monetary constraints.
- Hardened purchase, sale, upgrade, and service calculations for signed 64-bit SQLite integer amounts; replaced the 32-bit Qt price-change signal and binary-float allocation/percentage rounding with Python-object signals and exact arithmetic.
- Standardized product catalogue defaults: blank DDR selection, localized known legacy attribute names with specific English technical titles, and a final «سایر موارد» option containing only «مشخصات» / “Specifications”.
- Corrected purchase and sales report-row restoration, including product/batch/seller cascading selection, purchase-form clear behavior, and empty optional sale customer/warranty/serial values.
- Changed the suggested database location to `Documents/Daqiq/Daqiq.db`; startup now requires an explicit `app_config.json` before auto-connecting and otherwise presents the Create / Connect dialog.
- Added regression coverage for the v4 schema, high-value purchase/sale totals, blank optional fields, catalogue localization, and startup selection. The repository CI compiles Python files and runs the complete pytest suite.

## QA status

- Latest confirmed full test run before release metadata updates: 92 passed.
- A new CI run is required on the final PR head.
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
