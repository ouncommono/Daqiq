# Daqiq Offline Licensing Protocol Specification (v1.4 — v4.9.4)

**Document Version:** 1.4.0  
**Target Product:** Daqiq Desktop (`daqiq.desktop`)  
**Release:** v4.9.4  
**Security Boundary:** Asymmetric Ed25519 Signatures, Native Win32 SMBIOS Hardware Fingerprinting (`GetSystemFirmwareTable('RSMB')`), Redundant Filesystem HMAC-SHA256 Clock-Rollback Anchors (Zero Windows Registry), Native C-Compiled XOR-Sharded Public Keys.

---

## 1. Protocol Changes & Generator Sync Notes (v4.9.3 -> v4.9.4)

### 1.1 Clean Device Request Schema (`.daqreq`)
Removed redundant `"hardware_anchors"` (the 3 unused tier hashes) and hardcoded `"device_label": "صندوق فروشگاه"`. Extracted real CPU model from **SMBIOS Type 4 (`Processor Version`)** via native Win32 `GetSystemFirmwareTable('RSMB')` (zero `winreg`), and synchronized live `store_name` from Settings / `app_config.json`.

```json
{
  "protocol_version": 1,
  "request_version": 1,
  "product_id": "daqiq.desktop",
  "device_fingerprint": "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e",
  "store_name": "فروشگاه نمونه",
  "computer_name": "CASHIER-PC",
  "os_info": "Windows 10 (64bit)",
  "cpu_model": "Intel(R) Core(TM) i5-12400F",
  "app_version": "4.9.4",
  "generated_at_utc": "2026-11-24T12:00:00Z",
  "checksum_sha256": "<64-char-hex-sha256-of-canonical-json>"
}
```

- `checksum_sha256` is computed over `json.dumps(req_without_checksum, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.
- `device_label` is omitted unless explicitly supplied by an operator/CLI caller.

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

Granular Sub-Features (14):
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

**Backward Compatibility Policy:** Omitted granular sub-feature keys in legacy/full `.daqlic` licenses automatically inherit their parent tab's authorization (`True` when the parent tab is enabled or all 10 core tabs are enabled). Explicit `false` values always take precedence and deny access.

### 1.4 Zero-Registry Clock-Rollback Guard
Windows Registry (`winreg`) is completely absent from Daqiq. High-water-mark timestamps are authenticated with HMAC-SHA256 bound to `device_fingerprint` and stored redundantly across:
- `%LOCALAPPDATA%\Daqiq\license\.clock_state.dat`
- `%LOCALAPPDATA%\Daqiq\license\clock_state.json`
- `%APPDATA%\Daqiq\.runtime_anchor.dat`
- `%PROGRAMDATA%\Daqiq\license\.runtime_anchor.dat` (when writable)
