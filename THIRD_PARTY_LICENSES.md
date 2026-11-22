# Daqiq Third-Party Licenses & Compliance Audit

This document outlines the licenses and compliance notices for third-party tools, compilers, and libraries used to build and package **Daqiq Desktop v4.9.0**.

---

## 1. Packaging & Compiler Technology: Nuitka Standard Edition

Daqiq is compiled using the free, open-source **Nuitka Standard** edition (pinned stable release):
- **License:** GNU Affero General Public License v3 (AGPLv3) **with Nuitka Runtime Library Exception**.
- **Exception Clause:** Nuitka includes a formal runtime exception in its licensing terms that explicitly permits compiling proprietary and commercial software. Binaries produced by Nuitka do NOT become subject to the AGPL, and the application source code does NOT need to be disclosed.
- **Zero Paid/Commercial Addons:** Daqiq uses strictly the free Nuitka Standard release without proprietary Nuitka Commercial plugins or closed-source obfuscators.
- **Security Boundary Disclosure:** Nuitka Standard acts as an optimizing ahead-of-time (AOT) C compiler and packager. It raises the reverse-engineering difficulty compared to bytecode, but compiler packaging is **not** an impenetrable DRM boundary. The true, mathematically verifiable security boundary of Daqiq rests on asymmetric Ed25519 cryptography and `fp_v1` SMBIOS hardware identity verification.

---

## 2. Core Runtime Libraries & Components

### PySide6 (Qt for Python)
- **Version:** `>= 6.6.0`
- **License:** GNU Lesser General Public License v3 (LGPLv3)
- **Compliance:** PySide6 shared native libraries (.dll) are packaged alongside the application. Users may replace Qt libraries in standalone deployments pursuant to LGPLv3 provisions.

### Cryptography (`cryptography.hazmat`)
- **Version:** `>= 41.0.0`
- **License:** Apache License, Version 2.0 and BSD 3-Clause License
- **Copyright:** (c) Individual contributors.
- **Purpose:** Industry-standard Ed25519 asymmetric digital signature verification and SHA-256 / HMAC primitives.

### SQLCipher & sqlcipher3
- **Version:** `>= 0.6.0`
- **License:** BSD 3-Clause License
- **Copyright:** (c) Zetetic LLC.
- **Purpose:** Transparent 256-bit AES database encryption for enterprise store data.

### OpenPyXL
- **Version:** `>= 3.1.2`
- **License:** MIT / Expat License
- **Purpose:** Spreadsheet generation for inventory and financial report exports.

### Pillow (PIL Fork)
- **Version:** `>= 10.0.0`
- **License:** Historical Permission Notice and Disclaimer (HPND)
- **Purpose:** Image manipulation and icon rendering.

### JDateTime & Jalali Core
- **Version:** `>= 5.0.0`
- **License:** Python Software Foundation License (PSF) / MIT
- **Purpose:** Persian Solar Hijri (Shamsi / Jalali) calendar conversions and business date arithmetic.

### Packaging
- **Version:** `>= 23.0`
- **License:** Apache License, Version 2.0 / BSD 2-Clause License
- **Purpose:** Semantic version comparison for application compatibility validation.
