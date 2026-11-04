# Changelog

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
