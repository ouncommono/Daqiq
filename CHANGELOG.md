# Daqiq 3.4.0

- Removed the arbitrary 300-item cap from the quantity selector's preset population; editable purchase quantities now accept large integer values, with stock and database constraints remaining authoritative.
- Made the DDR version selector blank by default for both desktop and laptop RAM subcategories.
- Replaced generic English `Specification` display-title fallbacks with `Additional Details`, standardized memory/interface labels, and corrected the duplicate interface attribute rename mapping.
- Bumped application metadata, SQLite schema version, UI version label, and Windows executable naming to 3.4.0. The fresh-install schema keeps its established physical column order to protect every named and positional query contract.
- Added regression coverage for 1,250/1,600-unit batch create/edit/delete and RAM DDR default selections.

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
