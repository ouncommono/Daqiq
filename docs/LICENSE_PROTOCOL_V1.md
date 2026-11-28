# Daqiq Offline Licensing Protocol Specification (v1.9 — v5.0.1)

**Document Version:** 1.9.0
**Target Product:** Daqiq Desktop (`daqiq.desktop`)
**Release:** v5.0.1
**Security Boundary:** Asymmetric Ed25519 Signatures, Native Win32 SMBIOS Hardware Fingerprinting (`GetSystemFirmwareTable('RSMB')`), Redundant Filesystem HMAC-SHA256 High-Water-Mark Clock Anchors (Zero Windows Registry), Native C-Compiled XOR-Sharded Public Keys.

---

## 1. Protocol Changes & Generator Sync Notes (v4.9.3 -> v4.9.7)

### 1.1 Canonical Device Request Schema (`.daqreq`)
Includes the exact `app_security_id` (`شناسه امنیتی برنامه`) displayed in the Daqiq License UI so operators/Generators can immediately verify key-pairing from a `.daqreq` file, plus real SMBIOS Type 4 `cpu_model` and live `store_name`.

```json
{
  "protocol_version": 1,
  "request_version": 1,
  "product_id": "daqiq.desktop",
  "device_fingerprint": "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e",
  "app_security_id": "daqiq-prod-v1 · 7925-3864-0164",
  "store_name": "فروشگاه نمونه",
  "computer_name": "CASHIER-PC",
  "os_info": "Windows 10 (64bit)",
  "cpu_model": "Intel(R) Core(TM) i5-12400F",
  "app_version": "4.9.8",
  "generated_at": "2026-11-25T12:00:00Z",
  "generated_at_utc": "2026-11-25T12:00:00Z",
  "checksum_sha256": "<64-char-hex-sha256-of-canonical-json>"
}
```

- `checksum_sha256` is computed over `json.dumps(req_without_checksum, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.
- Both `generated_at` and `generated_at_utc` are included so Generator `DeviceRequest` (`generated_at`) and legacy inspectors deserialize seamlessly.
- `device_label` is omitted unless explicitly supplied by an operator/CLI caller.
- **v4.9.8 Expiry & Red-Team Security Notes (Generator Sync):**
  - `grace_period_days` defaults strictly to **`0`** when omitted or `None` (zero hidden grace days). When `grace_period_days > 0`, hard lock triggers at `expires_at + grace_period_days`.
  - Non-perpetual licenses (`subscription`, `trial`, `timed`) with missing or unparseable expiry fail closed (`CORRUPTED_LICENSE`). Date-only expiry strings (`YYYY-MM-DD`) expire at end-of-day UTC (`23:59:59Z`).
  - Alias keys (`expires_at_utc`, `valid_until`, `expiry_date`, `duration_days`, and nested `validity.*`) and `license_type`/`type`/`plan` are supported safely without breaking canonical Ed25519 signature verification.
  - **Monotonic High-Water-Mark Expiration Latch:** Once monotonic clock anchors pass `expires_at`, even rolling Windows clock back within `max_clock_skew_hours` (e.g., < 24h) evaluates expiry against `max(now_utc, high_water_mark_utc)` — making expired license revival impossible. `issued_at - max_clock_skew_hours` is also enforced strictly.
  - **Fail-Closed Startup & CLI Non-Bypass:** `LicenseDialog.accept()` re-verifies `check_license(force_reload=True).is_valid` when gating startup; `--smoke-launch-db` runs strictly non-interactive, input-locked, refuses password-protected DBs, and auto-terminates via daemon watchdog.

### 1.2 Configurable Build Identity (`public_key`, `key_id`, `fp_prefix`)
Precedence order at build time:
1. Environment variables: `DAQIQ_LICENSE_PUBLIC_KEY_B64`, `DAQIQ_LICENSE_KEY_ID`, `DAQIQ_LICENSE_FP_PREFIX`
2. Local gitignored JSON: `build_license_config.local.json`
3. Repository defaults: `licensing/trusted_keys.json` (`daqiq-prod-v1`), `fp_v1:`

### 1.3 Complete Granular Entitlement Registry (`payload.features`)
Core Tab Modules (10):
- `dashboard` — داشبورد
- `products` (alias `inventory`) — مدیریت کالاها
- `batches` (alias `purchases`) — ثبت خرید و محموله‌ها
- `sales` — ثبت فروش
- `services` — میز خدمت
- `upgrades` — ارتقای کالا
- `suppliers_payments` (alias `suppliers`) — تأمین‌کنندگان و پرداخت‌ها
- `reports` — گزارش‌های جامع
- `employees` (alias `users`) — مدیریت کاربران
- `settings` — تنظیمات

Granular Sub-Features (24):
- `excel_report_export` — خروجی اکسل گزارش‌ها
- `partner_export` — خروجی موجودی همکار
- `report_builder` — ساخت و ویرایش گزارش‌های سفارشی
- `auto_backup` — پشتیبان‌گیری خودکار
- `manual_backup_restore` — پشتیبان‌گیری و بازیابی دستی
- `database_encryption` — رمزگذاری پایگاه داده
- `multi_database` — مدیریت چند پایگاه داده
- `barcode_scanner` — اسکنر بارکد
- `audit_logs` — گزارش‌های ممیزی
- `taxonomy_import_export` — ورود و خروج ساختار کالاها و خدمات
- `custom_calendar_formats` — تغییر قالب تقویم و ساعت
- `profit_analytics` — تحلیل سود و گزارش‌های سودآوری
- `price_edit` — ویرایش قیمت فروش در فاکتور
- `batch_delete` — حذف محموله خرید
- `print_invoices` — چاپ فاکتورها و گزارش‌ها (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)
- `backup_export` — پشتیبان‌گیری و خروجی اطلاعات (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)
- `customers` — مدیریت مشتریان (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)
- `installments` — فروش و پرداخت اقساطی (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)
- `charts_analytics` — گزارش‌های نموداری و تحلیل‌ها (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)
- `word_export` — خروجی قابل ویرایش Word (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)
- `proforma_invoices` — صدور و مدیریت پیش‌فاکتورها (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)
- `supplier_installments` — خرید اقساطی و تعهدات تأمین‌کنندگان (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)
- `incidental_costs` — هزینه جانبی در فاکتورها (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)
- `service_installments` — فروش اقساطی خدمات (پیش‌فرض فعال در صورت نبود کلید در لایسنس‌های قبلی)

**Backward Compatibility Policy:** Omitted granular sub-feature keys in legacy/full `.daqlic` licenses automatically inherit their parent tab's authorization (`True` when the parent tab is enabled or all 10 core tabs are enabled; `print_invoices`, `backup_export`, `customers`, `installments`, `charts_analytics`, `word_export`, `proforma_invoices`, `supplier_installments`, `incidental_costs`, and `service_installments` default to `True` when omitted so legacy `.daqlic` files issued for v4.9.x/v5.0.0/v5.0.1 retain all capabilities cleanly). Explicit `false` values always take precedence and deny access. Also during `readonly` grace period, database backups (`backup_export`), JSON/Excel exports, and viewing/printing remain active while mutating settings (`report_builder`, catalog structure, and transactions) are locked.

### 1.4 Zero-Registry Clock-Rollback Guard
Windows Registry (`winreg`) is completely absent from Daqiq. High-water-mark timestamps are authenticated with HMAC-SHA256 bound to `device_fingerprint` and stored redundantly across:
- `%LOCALAPPDATA%\Daqiq\license\.clock_state.dat`
- `%LOCALAPPDATA%\Daqiq\license\clock_state.json`
- `%APPDATA%\Daqiq\.runtime_anchor.dat`
- `%PROGRAMDATA%\Daqiq\license\.runtime_anchor.dat` (when writable)
