# Changelog

## 1.1.0

### Database and audit timestamps
- Standardized system audit timestamps on all application tables with UTC ISO-8601 timestamps and microsecond precision.
- Added insert/update triggers that maintain created_at and updated_at independently of business transaction dates.
- Preserved sale_datetime and other transaction-date fields when records are edited.
- Added an activity index set and set SQLite user_version to 110.
- Renamed the sales markup column to unit_markup_price in the fresh schema.

### Comprehensive reports
- Kept newest-first as the default using system audit activity timestamps across products, shipments, sales and services.
- Added audit-created product records to the combined activity report.
- Added sort choices for audit activity, transaction date, amount, category, and discount/markup.
- Ensured the Excel export is built from the currently sorted report table.
- Corrected service discount/markup to compare received amount with service fee.

### Service desk and selectors
- Added red/green underpriced-service feedback to the received amount and discount summary.
- Made requested report, purchase, sales, service and upgrade person/category selectors read-only.
- Kept warranty duration editable and supports manual values in days, weeks, months or years.
- Explicitly initializes product, shipment and upgrade specification fields for single-item lists.

### Settings, access and inventory exports
- Reorganized settings into Products, Services, Access Levels and Colleague Inventory Export tabs.
- Rebuilt access levels around granular permission keys with individual action/view checkboxes.
- Added dedicated permission checks for settings, backups, exports, reports and application modules.
- Expanded colleague inventory columns to include both product and shipment attributes.
- Defaults include product code then shipment code; suggested price and stock are unchecked.
- Moved the category-specific subcategory caption editor directly above the subcategory list.

### Taxonomy and RTL
- Replaced long model-specific taxonomy choices with compact editable hardware-family templates.
- Enforced Persian attribute names and English display titles for custom technical attributes.
- Made date-picker year/today and month/day controls stretchable.
- Standardized right-aligned labels and flexible form-field growth.
- Converted all extra-zero dropdown numerals to Persian digits.

### Validation
- Added regression tests for timestamp precision, immutable sale business dates, shipment-aware exports, granular role permissions, selector editability, date-picker resizing, and service discount color coding.
