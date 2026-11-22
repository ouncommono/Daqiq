# Daqiq Offline Licensing Protocol Specification (v1.0)
**Document Version:** 1.0.0  
**Target Product:** Daqiq Desktop (`daqiq.desktop`)  
**Standard Release:** v4.9.0  
**Security Boundary:** Asymmetric Cryptography (Ed25519), Hardware SMBIOS Anchoring (`fp_v1`), Offline Clock-Rollback Protection

---

## 1. Architectural Overview & Ecosystem Model

The Daqiq offline licensing architecture is designed for completely air-gapped commercial desktop installations. It enforces cryptographically verifiable licensing, hardware-bound node-locking, granular feature entitlements, and time-bounded subscriptions without requiring an internet connection, activation server, cloud service, or database dependency.

### 1.1 The Three-App Ecosystem
The system operates across three distinct entities:

```
+------------------------------------+
|  Companion App A                   |
|  Device Request Utility            |
|  (Client Machine - Offline)        |
+-----------------+------------------+
                  |
                  | Exports Device Request (*.daqreq)
                  v
+-----------------+------------------+
|  Companion App B                   |
|  Offline License Generator/Issuer  |
|  (Vendor Air-gapped Host)          |
|  [Holds Ed25519 Signing Key]        |
+-----------------+------------------+
                  |
                  | Issues Signed License (*.daqlic)
                  v
+-----------------+------------------+
|  Daqiq Desktop Application         |
|  (Client Machine - Offline)        |
|  [Holds Ed25519 Public Key Only]   |
+------------------------------------+
```

1. **Companion App A (Device Request Utility):** Standalone lightweight tool running on the client machine. Collects the client machine's SMBIOS hardware identity, hashes it via `fp_v1`, and exports a `.daqreq` JSON request file.
2. **Companion App B (Offline License Generator):** Air-gapped administrative software operated strictly by the vendor. Imports `.daqreq`, configures customer details, entitlements, validity period, and device quotas, and signs the payload with the vendor's private Ed25519 key, outputting a `.daqlic` license file.
3. **Daqiq Desktop (`daqiq.desktop`):** The commercial enterprise desktop ERP application. Embeds trusted Ed25519 public keys, verifies the cryptographic signature of `.daqlic`, matches the local `fp_v1` hardware fingerprint, enforces feature entitlements, and detects clock rollback. **The private signing key never exists in Daqiq.**

---

## 2. Cryptographic Envelope & File Format

### 2.1 File Specification
- **File Extension:** `.daqlic`
- **Encoding:** UTF-8 without Byte Order Mark (BOM).
- **Max File Size:** `65536` bytes (64 KiB). Any file exceeding this limit is rejected immediately without parsing.
- **Parsing Restrictions:** Strict JSON parser. Duplicate keys inside dictionaries MUST be rejected (`object_pairs_hook`). Floats, `NaN`, and `Infinity` are strictly forbidden inside the signed payload.

### 2.2 Envelope JSON Schema
```json
{
  "envelope_version": 1,
  "algorithm": "Ed25519",
  "key_id": "daqiq-prod-v1",
  "payload": {
    "format_version": 1,
    "product_id": "daqiq.desktop",
    "license_id": "LIC-2026-000001",
    "key_id": "daqiq-prod-v1",
    "customer": {
      "name": "نام مشتری یا فروشگاه",
      "organization": "نام مجموعه (اختیاری)",
      "contact": "شناسه پشتیبانی یا شماره تماس (اختیاری)"
    },
    "license_type": "perpetual",
    "issued_at": "2026-11-22T00:00:00Z",
    "not_before": "2026-11-22T00:00:00Z",
    "expires_at": null,
    "max_devices": 1,
    "device_fingerprints": [
      "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"
    ],
    "features": {
      "dashboard": true,
      "products": true,
      "batches": true,
      "sales": true,
      "services": true,
      "upgrades": true,
      "suppliers_payments": true,
      "reports": true,
      "employees": true,
      "settings": true
    },
    "min_app_version": "4.9.0",
    "max_app_version": null
  },
  "signature": "<base64-standard-encoded-64-byte-ed25519-signature>"
}
```

### 2.3 Field Specification & Validation Rules

| Field | Type | Required | Invariants & Validation |
|---|---|---|---|
| `envelope_version` | Integer | Yes | Must equal `1`. |
| `algorithm` | String | Yes | Must strictly equal `"Ed25519"`. |
| `key_id` | String | Yes | Non-empty ASCII identifier. Must match `payload.key_id` and exist in `KeyRegistry`. |
| `signature` | String | Yes | Base64 standard RFC 4648 encoded string decoding to exactly 64 raw bytes. |
| `payload.format_version` | Integer | Yes | Must equal `1`. |
| `payload.product_id` | String | Yes | Must strictly equal `"daqiq.desktop"`. |
| `payload.license_id` | String | Yes | Non-empty unique string (e.g., `"LIC-2026-000001"`). |
| `payload.customer.name` | String | Yes | Customer name in Persian or Latin (Unicode NFC normalized). |
| `payload.customer.organization` | String / Null | Optional | Organization name (Unicode NFC normalized). |
| `payload.customer.contact` | String / Null | Optional | Support phone, email, or telegram ID. |
| `payload.license_type` | String | Yes | Either `"perpetual"` or `"subscription"`. |
| `payload.issued_at` | String | Yes | ISO-8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`). |
| `payload.not_before` | String | Yes | ISO-8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`). |
| `payload.expires_at` | String / Null | Conditional | If `license_type == "perpetual"`, MUST be `null`. If `license_type == "subscription"`, MUST be valid ISO-8601 UTC timestamp strictly greater than `not_before`. |
| `payload.max_devices` | Integer | Yes | Integer `>= 1`. |
| `payload.device_fingerprints` | List[String] | Yes | Non-empty list of valid `fp_v1:<64-hex>` strings with zero duplicates. Length must satisfy `1 <= len(device_fingerprints) <= max_devices`. |
| `payload.features` | Dict[str, bool] | Yes | Dict mapping feature keys to strict booleans. Unknown or non-boolean values rejected. Omitted keys default to `false`. |
| `payload.min_app_version` | String / Null | Optional | SemVer/Packaging version string (e.g. `"4.9.0"`). Current app version must be `>= min_app_version`. |
| `payload.max_app_version` | String / Null | Optional | SemVer/Packaging version string. Current app version must be `<= max_app_version`. |

---

## 3. Canonical Serialization & Cryptographic Verification

### 3.1 Canonical Serialization Algorithm
To ensure identical byte representation across different operating systems and JSON libraries:

1. **Type Strictness:** Validate that `payload` contains only `dict`, `list`, `str`, `int`, `bool`, and `None`. Reject any `float`.
2. **Unicode Normalization:** Recursively normalize every string (both dictionary keys and string values) to **Unicode Normalization Form C (NFC)** (`unicodedata.normalize("NFC", s)`).
3. **JSON Serialization:** Serialize `payload` using:
   ```python
   canonical_bytes = json.dumps(
       normalized_payload,
       sort_keys=True,
       separators=(",", ":"),
       ensure_ascii=False
   ).encode("utf-8")
   ```
4. **Domain Separation:** Prepend the domain separation prefix:
   ```
   message_to_sign = b"DAQIQ-LICENSE-V1\n" + canonical_bytes
   ```
5. **Ed25519 Verification:** Verify `signature` against `message_to_sign` using the trusted Ed25519 public key identified by `key_id`.

### 3.2 Canonical Serialization Test Vector

**Test Public Key (32 bytes raw, Base64):**
```
tZwFxuCGOF+WZqVF+PeKwpoIpOZovHLFRVSQxGaXJXA=
```

**Normalized Canonical JSON String (691 bytes UTF-8):**
```json
{"customer":{"contact":"+989120000000","name":"فروشگاه تستی نمونه","organization":"مجموعه آزمایشی"},"device_fingerprints":["fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"],"expires_at":null,"features":{"batches":true,"dashboard":true,"employees":true,"products":true,"reports":true,"sales":true,"services":true,"settings":true,"suppliers_payments":true,"upgrades":true},"format_version":1,"issued_at":"2026-11-22T00:00:00Z","key_id":"daqiq-test-v1","license_id":"LIC-2026-TEST01","license_type":"perpetual","max_app_version":null,"max_devices":1,"min_app_version":"4.9.0","not_before":"2026-11-22T00:00:00Z","product_id":"daqiq.desktop"}
```

**Domain Separated Message SHA-256 Digest:**
```
52bdf69ad45d565685bae87f75c03d4a5baa43a3acafe785499b16ee5618366a
```

**Ed25519 Signature (Base64):**
```
kgrF5f89h9JBIHiQ55H5J+jZul3ZwC6NdeEDXtrlxMDWWlBr892vliqLsTxPD0q+RlEJaXsIQZUSjaevKSGjCA==
```

---

## 4. Hardware Fingerprint Specification (`fp_v1`)

The hardware fingerprint binds a license strictly to physical hardware while remaining resilient to Windows operating system reinstalls, user accounts, disk swaps, and RAM upgrades.

### 4.1 SMBIOS Hardware Sources
1. **System UUID:** `Win32_ComputerSystemProduct.UUID`
2. **Motherboard Serial:** `Win32_BaseBoard.SerialNumber`
3. **Motherboard Product & Manufacturer:** `Win32_BaseBoard.Product`, `Win32_BaseBoard.Manufacturer`

### 4.2 Non-Blocking Safe Acquisition
Hardware identity is acquired using PowerShell CIM queries with hard timeouts and hidden window creation flags:
```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_ComputerSystemProduct | Select-Object -ExpandProperty UUID; Get-CimInstance Win32_BaseBoard | Select-Object SerialNumber, Manufacturer, Product | Format-List"
```
Execution constraints:
- Timeout: `<= 5.0` seconds.
- Process Creation Flags: `subprocess.CREATE_NO_WINDOW` (exit code `0x08000000`) to prevent console flickering.

### 4.3 OEM Placeholder & Invalid Value Rejection
Values are cleaned by trimming, removing internal punctuation, and converting to lowercase for comparison. If a value matches any entry below, it is rejected as a non-unique OEM placeholder:

- **Invalid UUIDs:**
  - Empty string or whitespace.
  - `00000000-0000-0000-0000-000000000000` (all zeros)
  - `ffffffff-ffff-ffff-ffff-ffffffffffff` (all Fs)
  - `03000200-0400-0500-0006-000700080009` (AMI placeholder)
  - Any string not matching canonical UUID format (`8-4-4-4-12` hex characters).
- **Invalid Motherboard Serials:**
  - Empty string or whitespace.
  - `none`, `n/a`, `na`, `not applicable`, `not specified`, `default string`, `to be filled by o.e.m.`, `system serial number`, `chassis serial number`, `base board serial number`, `oem`, `invalid`, `unknown`, `0`, `00000000`, `123456789`.
  - Any single character repeated (e.g. `xxxxxxx`, `.......`, `-------`).

### 4.4 Multi-Tier Anchoring Strategy
- **Tier 1 (Preferred - Both Valid):**
  Canonical representation: `v1|uuid=<NORM_UUID>|board=<NORM_BOARD>`
- **Tier 2 (Valid UUID, OEM Board Serial):**
  Canonical representation: `v1|uuid=<NORM_UUID>|board_model=<NORM_MFG>:<NORM_PROD>`
- **Tier 3 (OEM UUID, Valid Board Serial):**
  Canonical representation: `v1|board=<NORM_BOARD>|board_model=<NORM_MFG>:<NORM_PROD>`
- **Hard Failure:**
  If neither Tier 1, Tier 2, nor Tier 3 can be satisfied, the provider raises `HardwareIdentityUnavailableError`. **The system NEVER falls back to volatile identifiers (RAM serials, MAC address, IP address, Windows MachineGuid, disk/volume serial, Windows username, or random UUIDs).**

### 4.5 Fingerprint Hash Calculation
1. Normalize canonical string: Unicode NFC, trim edges, collapse repeated whitespace, uppercase ASCII.
2. Prepend domain prefix: `DAQIQ-HWFP-V1|` + normalized string.
3. Compute SHA-256 hash.
4. Format output as: `fp_v1:<64-lowercase-hex>`.

### 4.6 Reproducible Test Vectors

| Vector | Raw Hardware Inputs | Canonical Normalized String | Output `fp_v1` Fingerprint |
|---|---|---|---|
| **1 (Tier 1)** | UUID: `4c4c4544-004a-4810-804e-c6c04f4b3232`<br>Board: `CN1296385A0123` | `V1\|UUID=4C4C4544-004A-4810-804E-C6C04F4B3232\|BOARD=CN1296385A0123` | `fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e` |
| **2 (Tier 1)** | UUID: `6fa0b6c2-38b1-4604-95d9-052c895c9e1a`<br>Board: `210889218200192` | `V1\|UUID=6FA0B6C2-38B1-4604-95D9-052C895C9E1A\|BOARD=210889218200192` | `fp_v1:cc12b7ba73d61e6240c106bb3239c09690102a0ca9f448497532733e8a5382cf` |
| **3 (Tier 2)** | UUID: `a1b2c3d4-e5f6-7890-abcd-ef1234567890`<br>Board: `Default string`<br>Mfg: `ASUSTeK COMPUTER INC.`<br>Product: `ROG STRIX B550-F GAMING` | `V1\|UUID=A1B2C3D4-E5F6-7890-ABCD-EF1234567890\|BOARD_MODEL=ASUSTEK COMPUTER INC.:ROG STRIX B550-F GAMING` | `fp_v1:112240a4e47ec9659a35161c17b93af2d36347155a138cac4ccafd8a9b6e5f0d` |
| **4 (Tier 3)** | UUID: `00000000-0000-0000-0000-000000000000`<br>Board: `MB-987654321-XYZ`<br>Mfg: `Micro-Star International Co., Ltd.`<br>Product: `MS-7C91` | `V1\|BOARD=MB-987654321-XYZ\|BOARD_MODEL=MICRO-STAR INTERNATIONAL CO., LTD.:MS-7C91` | `fp_v1:31e219b0b74a8399e199ebc12ef49c557d86fac0db3f445249ceed8fa72a1ecb` |
| **5 (Unicode & Whitespace)** | UUID: `b8f9a102-1234-5678-9abc-def012345678`<br>Board: `  SN-Tehran-۰۱۲۳-XY  ` | `V1\|UUID=B8F9A102-1234-5678-9ABC-DEF012345678\|BOARD=SN-TEHRAN-۰۱۲۳-XY` | `fp_v1:a4cb3359206a481ec7115db8c9116422deca91eebb7c6bdfc60f18307ebe8671` |

---

## 5. Feature Entitlement & Tab Mapping

Daqiq enforces entitlements directly on its 10 main application tabs. Feature keys in `payload.features` correspond exactly to tab modules:

| Tab Index | Tab Title (Persian RTL) | License Feature Key | Default Policy |
|---|---|---|---|
| `0` | 📊 داشبورد | `dashboard` | `false` if omitted |
| `1` | 📦 مدیریت کالاها | `products` | `false` if omitted |
| `2` | 🚚 ثبت خرید و محموله‌ها | `batches` | `false` if omitted |
| `3` | 🛒 ثبت فروش | `sales` | `false` if omitted |
| `4` | 🛠️ میز خدمت | `services` | `false` if omitted |
| `5` | 🔧 ارتقای کالا | `upgrades` | `false` if omitted |
| `6` | 💳 تأمین‌کنندگان | `suppliers_payments` | `false` if omitted |
| `7` | 📈 گزارش‌های جامع | `reports` | `false` if omitted |
| `8` | 👤 مدیریت کاربران | `employees` | `false` if omitted |
| `9` | ⚙️ تنظیمات | `settings` | `false` if omitted |

**Enforcement Policy:**
- When a feature key evaluates to `false`, the corresponding tab is disabled and cannot be activated via sidebar, tab clicks, quick-action shortcuts, or navigation events.
- Attempting to switch to an unlicensed tab displays a polite Persian information prompt:
  > «این بخش در لایسنس فعال شما مجاز نیست. جهت ارتقا یا فعال‌سازی این ماژول با پشتیبانی تماس بگیرید.»
- Full commercial licenses specify all 10 features as `true`.
- Commercial feature entitlements operate independently from database employee role permissions (`employees` table).

---

## 6. Device Request File Contract (`.daqreq`)

When a customer commissions a new PC or adds a terminal to a multi-device store license, Companion App A (Device Request Utility) generates a `.daqreq` file:

```json
{
  "request_version": 1,
  "product_id": "daqiq.desktop",
  "generated_at": "2026-11-22T00:00:00Z",
  "device_fingerprint": "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e",
  "device_label": "صندوق اصلی فروشگاه (Main Terminal)",
  "app_version": "4.9.0",
  "hardware_tier": "tier1"
}
```

Companion App B (Offline License Generator) accepts one or more `.daqreq` files to bundle into `payload.device_fingerprints` (up to `max_devices`).

---

## 7. Storage, Atomicity & Clock-Rollback Protection

### 7.1 Deterministic Storage Paths
Licenses and clock states are stored strictly outside the business database:
1. **Machine-Wide Path:** `%PROGRAMDATA%\Daqiq\Licensing\` (`C:\ProgramData\Daqiq\Licensing\`)
2. **Per-User Path:** `%LOCALAPPDATA%\Daqiq\Licensing\` (`C:\Users\<User>\AppData\Local\Daqiq\Licensing\`)

**Resolution Precedence:**
- **Read:** Check Machine-Wide `license.daqlic` first. If missing, check Per-User `license.daqlic`.
- **Write:** Attempt to write to Machine-Wide directory. If permission denied (`PermissionError`), write to Per-User directory seamlessly without failing.
- **Forbidden Locations:** NEVER store inside SQLite/SQLCipher databases, `%TEMP%`, current working directory, or Nuitka onefile temporary extraction directories.

### 7.2 Atomic Import & Reinstall Recovery
- Candidate `.daqlic` files are validated completely in memory before writing to disk.
- Writing uses a temporary sibling file (`license.daqlic.<uuid>.tmp`), flushed with `os.fsync()`, and swapped atomically using `os.replace()`.
- The portable signed `.daqlic` is stored unmodified on disk. Re-importing the file after a clean Windows reinstallation on authorized hardware restores full licensing immediately.

### 7.3 Clock-Rollback Protection (`clock_state.json`)
For time-limited subscription licenses, Daqiq tracks a monotonic high-water mark:
```json
{
  "version": 1,
  "last_seen_utc": "2026-11-22T00:18:00Z",
  "hmac_tag": "<hmac-sha256-hex>"
}
```
- **Tolerance:** `900` seconds (15 minutes) to accommodate natural NTP synchronization or standard BIOS clock jitter.
- **Evaluation:** If `now_utc + 900s < last_seen_utc`, a `CLOCK_ROLLBACK` status is raised with guidance to synchronize the PC system clock.
- **Perpetual License Immunity:** Perpetual licenses (`license_type == "perpetual"`) never expire and are immune to clock-state rollback errors.

---

## 8. Public Key Management & Replacement Instructions

Daqiq ships with a default trusted public key registry in `licensing/keys.py`:
```python
DEFAULT_KEY_REGISTRY = {
    "daqiq-prod-v1": "tZwFxuCGOF+WZqVF+PeKwpoIpOZovHLFRVSQxGaXJXA=",
}
```

### Steps to Replace with Vendor Production Public Key:
1. Generate an Ed25519 keypair offline in the secure vendor signing environment:
   ```python
   from cryptography.hazmat.primitives.asymmetric import ed25519
   from cryptography.hazmat.primitives import serialization
   import base64

   private_key = ed25519.Ed25519PrivateKey.generate()
   public_key = private_key.public_key()
   pub_b64 = base64.b64encode(public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode('ascii')
   print("Vendor Public Key:", pub_b64)
   ```
2. Store `private_key` securely in an air-gapped vault for Companion App B. **Never commit secret signing keys to source control or package them with Daqiq.**
3. Update `DEFAULT_KEY_REGISTRY` in `licensing/keys.py` with `"daqiq-prod-v1": "<YOUR_VENDOR_PUBLIC_KEY>"`.
4. Compile Daqiq via `python scripts/build_nuitka.py --mode onefile`.
