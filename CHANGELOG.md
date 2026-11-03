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
