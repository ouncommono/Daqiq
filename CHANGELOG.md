# Changelog

## 2.1.0 — Daqiq (دقیق)

### Database and data access
- Bump the clean-slate SQLite schema contract to version 210 and record the Daqiq application name/version in database and application metadata.
- Add normalized role-to-role and role-to-user data-scope tables with foreign keys, uniqueness constraints and indexes.
- Remove the stale legacy-application-settings migration call from database switching.
- Keep product master specifications separate from shipment-level upgrade specifications.

### Accounting workflows and reports
- Center all Comprehensive Reports Excel adjustment-column cells, including signed values, with RTL worksheet reading order.
- Restore shipment stock and the exact pre-upgrade technical specifications when an upgrade is reverted.
- Clear batch/sale color selections on form reset and shipment changes.
- Keep new purchase shipment specifications sourced from the product's base specification set.

### User interface
- Apply strict RTL rendering and de-duplicated specification output to sales shipment hover tooltips.
- Add role-based and explicit-user data visibility configuration.
- Couple catalog field labels to their inputs and make the defined technical-attribute list collapsible and scrollable.
- Apply the Daqiq product name and 2.1.0 version to application metadata and visible titles.

### Validation
- Automated regression tests are updated for the 2.1.0 schema and release metadata. Desktop acceptance on Windows should be completed before production deployment.

## 1.0.2

### Reports and exports
- Added a report sort selector with newest-first as the default and oldest-first as an alternative.
- Moved report search directly above the table; report export continues to use the visible table order.
- Renamed the colleague inventory export and added per-column configuration, including suggested sale price.
- Added regression coverage for the configurable export columns.

### Inventory and UI
- Replaced purchase and sales color lists with modal selectors whose full-width checkbox rows are easy to click.
- Corrected the collapsed display direction for mixed Persian/Latin searchable selectors.
- Added direction-aware technical-specification tooltips and right-aligned section headings/field labels.
- Made the product taxonomy's subcategory, attribute, and color lists collapsible and added full-text attribute tooltips.
- Added per-category customization for the subcategory field caption.
- Reordered the dashboard low-stock table and included batch identifiers and technical specifications.
- Applied discount/markup color coding and fixed the Windows title-bar direction for mixed Persian/digit store names.
- Updated user-facing terminology and standardized dialog button text/alignment.

### Access and database
- Added configurable access-level names based on the application's existing permission profiles, with confirmation before changing or deleting assigned levels.
- Added created_at and updated_at activity fields and SQLite indexes for common activity sorts and related lookups.
- Added tests for timestamp behavior and core activity indexes.

### Validation scope
This release update preserves the existing business-table identifiers and relationships. It does not perform a wholesale redesign or rename of every legacy table/column. Manual Windows UI verification and the complete GitHub Actions test run are still required before a production release.

## 1.2.0

### Database and accounting
- Standardized creation and modification audit timestamps to local `YYYY-MM-DD HH:MM:SS.fff` precision while preserving business transaction dates.
- Replaced synthetic activity ticks with timestamp triggers and activity indexes based on `COALESCE(updated_at, created_at)`.
- Centralized settlement-aware receivable calculations: settled services classify the received/service-cost difference as discount or surcharge with zero receivable; only partial and unsettled statuses carry balances.
- Corrected service net-profit calculations to use the actual received amount less side costs.

### Reports and operational UI
- Expanded report sorting to include activity time (default), transaction date, amount, settlement, category, and responsible user.
- Reorganized report types into practical sales/services, purchasing, stock, and user-performance groups.
- Added service discount/surcharge and receivable columns; added red/green service price feedback.
- Fixed one-item product selection initialization, editable warranty duration, read-only controlled selectors, responsive date controls, and scrollable technical specifications.
- Applied compact RTL field caption alignment and English technical-specification display titles.

### Settings, catalog, exports, and permissions
- Separated product, service, colleague inventory export, and access-level settings into dedicated tabs.
- Added shipment code as the second inventory export column; it and product code are selected by default, while suggested price and stock are unchecked.
- Added per-module and per-action permission checkboxes with common role presets.
- Consolidated the subcategory caption setting into main categories and fixed the geometry of the four catalog frames.
- Compactly parameterized CPU family templates and localized every extra-price-zero option in Persian numerals.

### Release validation
- Added regression coverage for settlement accounting, service net profit, export defaults, audit column order, and schema version.
- GitHub Actions run 159 passed: 65 tests passed, 0 failed (Python 3.11 / PySide6 6.11.3).
- Manual desktop/Windows visual acceptance remains outstanding. CI currently reports 137 non-failing Qt deprecation warnings for `QSortFilterProxyModel.invalidateFilter()`.

## 2.0.0 — Clean schema and operational UI release

### Database architecture
- Introduce a fresh-database-only SQLite schema contract, recorded as `PRAGMA user_version = 200`; pre-v2 databases are rejected with an actionable error rather than silently migrated.
- Reorder employee, batch, upgrade, sales, service history and service-record columns to the v2 logical workflow order, with stable IDs and audit timestamps at the end.
- Add foreign-key and activity/reference indexes for product, batch, sales, upgrades, service records, service history and payment lookups.
- Add integrity checks for non-negative stock, quantities, costs and monetary values where appropriate.
- Store application and schema versions in database settings and JSON configuration.

### Reporting, sorting and financial presentation
- Make all shared report tables sortable by clicking column headers; first click sorts ascending and the next click reverses direction.
- Use typed comparisons for Persian/English numeric values, formatted prices, Gregorian/Jalali date strings, natural alphanumeric codes and text.
- Add the inverse “اولین ویرایش / ایجاد” activity sort in comprehensive reports.
- Apply red to negative financial values and debt, and green to positive receivables; mixed balance rows are colored by transaction type.
- Show service catalogue codes in comprehensive service rows rather than a generic placeholder.

### Sales, upgrade and operational UI
- Show shipment code, available stock and suggested price together in the sales shipment selector, with full product/shipment specifications in an RTL tooltip.
- Add an explicit upgrade checkbox to deduct or preserve part inventory; persist the actual quantity deducted, log the selected outcome and reverse exactly that amount when an upgrade is reverted or deleted.
- Rename the supplier tab to “تأمین‌کنندگان” and render the active database path LTR.
- Fix recent-database row heights, active-status badge sizing and remove-button clipping.
- Select existing backup interval and retention values automatically on focus/click.
- Keep the defined custom-specification list visible; improve grid spacing, row height and compact RTL labels in product-management settings.

### Dashboard access controls
- Add per-metric and per-table dashboard visibility grants for sales, profit, purchases, stock, low-stock, supplier debt, service profit and dashboard detail tables.
- Apply role presets and hide each metric/table unless both dashboard view and the specific permission are granted.

### Validation and acceptance
- Add regression tests for the v2 schema/version contract, rejection of old databases, stock-preserving upgrades, typed table sorting, financial colors and service-code reporting.
- GitHub Actions run [#173](https://github.com/ouncommono/Accounting-Software/actions/runs/41749974130) passed: **71 passed, 0 failed**; Python compilation also passed.
- CI emitted 141 non-failing Qt deprecation warnings for `QSortFilterProxyModel.invalidateFilter()`.
- Manual Windows/desktop visual acceptance remains a release checklist item.
