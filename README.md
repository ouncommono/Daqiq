# Daqiq (دقیق) — Desktop Retail Accounting & Inventory Management

Daqiq is a commercial-grade, high-performance offline Windows desktop application engineered for retail computer hardware shops, IT parts distributors, and repair centers. Built with **PySide6 (Qt)**, **SQLite/SQLCipher**, and compiled into native machine code with **Nuitka Standard**, Daqiq operates completely air-gapped with zero telemetry, zero cloud dependencies, and zero license servers.

---

## Key Features

- **Offline Ed25519 Cryptographic Licensing**: Robust node-locked subscription and perpetual licensing paired 100% deterministically with [Daqiq-License-Generator](https://github.com/ouncommono/Daqiq-License-Generator).
- **Anti-Crack Public Key Sharding**: Public keys are split into compile-time XOR-masked byte shards and compiled directly into native C compilation units via Nuitka.
- **Hardware Node-Locking**: Sub-2ms direct Win32 SMBIOS firmware table queries (`kernel32.GetSystemFirmwareTable`) resilient to RAM/SSD swaps, OS reinstalls, and network changes.
- **Multi-Anchor Monotonic Clock-Rollback Protection**: Redundant filesystem HMAC-SHA256 authenticated high-water mark anchors across independent OS locations (`%LOCALAPPDATA%`, `%APPDATA%`, and `%PROGRAMDATA%`) with zero Windows Registry dependency.
- **Multi-Calendar & Time Format**: Lossless real-time support for **Jalali (شمسی)**, **Hijri (قمری)**, and **Gregorian (میلادی)** calendars alongside **24-hour** and **12-hour (ق.ظ / ب.ظ)** formats with atomic database migration.
- **Tailored Retail Accounting**: Advanced batch inventory tracking, barcode scanner support, warranty management, hardware upgrade assembly with automatic stock deduction, customizable report exports, and atomic database backups.

---

## Build-Time Licensing Configuration

Daqiq features fully configurable build identity parameters:
1. **Public Key (`public_key` / `DAQIQ_LICENSE_PUBLIC_KEY_B64`)**: The vendor's Ed25519 public key (Base64, Hex, or PEM).
2. **Key ID (`key_id` / `DAQIQ_LICENSE_KEY_ID`)**: Key identifier matching the license generator (e.g., `daqiq-prod-v1`).
3. **Fingerprint Prefix (`fp_prefix` / `DAQIQ_LICENSE_FP_PREFIX`)**: Hardware fingerprint prefix (default `fp_v1:`).
4. **Support Phone (`support_phone` / `DAQIQ_SUPPORT_PHONE`)**: Vendor support phone displayed in license/grace/expiration screens (e.g., `09XXXXXXXXX`).

### Method A: Local Builds (Single-Command Validated Build)

1. Copy the tracked template:
   ```powershell
   copy build_license_config.example.json build_license_config.local.json
   ```
2. Edit `build_license_config.local.json`:
   ```json
   {
     "public_key": "YOUR_BASE64_ED25519_PUBLIC_KEY",
     "key_id": "daqiq-prod-v1",
     "fp_prefix": "fp_v1:",
     "support_phone": "09XXXXXXXXX"
   }
   ```
   *(Note: `build_license_config.local.json` is gitignored so local vendor keys are never committed).*
3. Run the single-command local build (validates all configuration values, prints `Key ID`, `Key FP`, `FP Prefix`, and `Support Phone`, compiles `Daqiq` + `Daqiq-Troubleshooter` with Nuitka, and leaves tracked git files untouched):
   ```powershell
   python scripts/build_local.py --mode onefile
   ```
   Or double-click / run `build_exe.bat`. To validate config without compiling:
   ```powershell
   python scripts/build_local.py --validate-only
   ```

Alternatively, pass parameters via environment variables (`DAQIQ_LICENSE_PUBLIC_KEY_B64`, `DAQIQ_LICENSE_KEY_ID`, `DAQIQ_LICENSE_FP_PREFIX`, `DAQIQ_SUPPORT_PHONE`) — precedence is **Env Vars > Local JSON > Repo Defaults**.

### Method B: GitHub Actions CI/CD Pipeline

In your GitHub repository under **Settings -> Secrets and variables -> Actions**:
- **Secret**: `DAQIQ_LICENSE_PUBLIC_KEY_B64` (Base64, Hex, or PEM Ed25519 public key)
- **Variable**: `DAQIQ_LICENSE_KEY_ID` (e.g., `daqiq-prod-v1`)
- **Variable**: `DAQIQ_LICENSE_FP_PREFIX` (e.g., `fp_v1:`)
- **Variable**: `DAQIQ_SUPPORT_PHONE` (e.g., `09XXXXXXXXX`)

When the workflow runs, GitHub Actions injects all three values pre-Nuitka and displays `Key ID`, `Key FP`, and `FP Prefix` in `$GITHUB_STEP_SUMMARY`.

---

## Pairing Verification with Daqiq-License-Generator

1. **Inspect Embedded Keys in Daqiq**:
   ```powershell
   python tools/license_key_tool.py inspect
   ```
2. **Generate Client Hardware Request (`.daqreq`)**:
   In Daqiq's License window, click **«دریافت فایل مشخصات سیستم»** to export `.daqreq`.
3. **Generate License in Daqiq-License-Generator**:
   Load the `.daqreq` file in `Daqiq-License-Generator`, select the matching `key_id`, choose subscription or perpetual, and issue `.daqlic`.
4. **Verify Offline**:
   ```powershell
   python tools/license_key_tool.py verify-license path/to/license.daqlic
   ```
   Or import the `.daqlic` file directly via the Daqiq activation dialog.

---

## Building from Source

### Prerequisites
- Python 3.11+
- Windows 10/11 x64
- Microsoft Visual C++ (MSVC) or MinGW64 toolchain

### Installation
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-build.txt
```

### Packaging with Free Nuitka Standard
- **Stage A (Standalone)**:
  ```powershell
  python scripts/build_nuitka.py --mode standalone
  python scripts/verify_nuitka_build.py --mode standalone
  ```
- **Stage B (Onefile Binary)**:
  ```powershell
  python scripts/build_nuitka.py --mode onefile
  python scripts/verify_nuitka_build.py --mode onefile
  ```
The optimized executables will be created at `dist/Daqiq_5.0.1.exe` and `dist/Daqiq-Troubleshooter.exe` with sibling `dist/default_taxonomy.json` and `dist/SHA256SUMS.txt`.

---

## Running Automated QA Tests
```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest tests -v
```
