# Daqiq Hardware Taxonomy Standards & Authoritative Sources Matrix

This document provides the authoritative source matrix for the hardware taxonomy seed packaged with Daqiq v4.6.0 (`default_taxonomy.json`). In accordance with retail computer store requirements, specifications distinguish verified technical standards from common commercial retail labels and extensible examples. Combinations of independent dropdown choices are not guaranteed to be mutually compatible.

---

## 1. Memory (RAM)

| Family / Scope | Dimension / Feature | Standard Values & Units | Classification | Authoritative Source URL |
| :--- | :--- | :--- | :--- | :--- |
| **Desktop RAM** | Generation | DDR2, DDR3, DDR3L, DDR4, DDR5 | Verified Standard | [JEDEC Standards Directory](https://www.jedec.org/standards-documents) |
| **Desktop RAM** | Form Factor | 240-pin DIMM (DDR2/3), 288-pin DIMM (DDR4/5) | Verified Standard | [JEDEC Standard No. 21-C](https://www.jedec.org/standards-documents/docs/jesd21-c) |
| **Desktop RAM** | Capacity | 1 GB, 2 GB, 4 GB, 8 GB, 16 GB, 32 GB, 64 GB, 128 GB | Retail Standard | [JEDEC Memory Standards](https://www.jedec.org/category/technology-focus-area/main-memory-ddr3-ddr4-ddr5) |
| **Desktop RAM** | Data Rate | 667 MT/s, 800 MT/s, 1066 MT/s, 1333 MT/s, 1600 MT/s, 2133 MT/s, 2400 MT/s, 2666 MT/s, 3200 MT/s, 4800 MT/s, 5600 MT/s, 6000 MT/s, 6400 MT/s | Verified Standard | [JEDEC JESD79 Series](https://www.jedec.org/standards-documents/docs/jesd-79-5b) |
| **Laptop RAM** | Form Factor | 200-pin SO-DIMM (DDR2), 204-pin SO-DIMM (DDR3), 260-pin SO-DIMM (DDR4), 262-pin SO-DIMM (DDR5), CAMM2 | Verified Standard | [JEDEC SO-DIMM & CAMM2](https://www.jedec.org/standards-documents/docs/jesd318) |
| **Laptop / Mobile** | Soldered LPDDR | LPDDR3, LPDDR4, LPDDR4X, LPDDR5, LPDDR5X (Soldered / On-board) | Verified Standard | [JEDEC Low Power Memory](https://www.jedec.org/category/technology-focus-area/low-power-memory) |

*Note: Data transfer rate is measured in Megatransfers per second (MT/s) rather than internal clock frequency (MHz), consistent with JEDEC specifications.*

---

## 2. Processors (CPUs) & Platform Architecture

| Family / Scope | Dimension / Feature | Standard Values & Units | Classification | Authoritative Source URL |
| :--- | :--- | :--- | :--- | :--- |
| **Intel Processors** | Product Line | Intel Celeron, Intel Pentium, Intel Core i3 / i5 / i7 / i9, Intel Core 3 / 5 / 7, Intel Core Ultra 5 / 7 / 9, Intel Xeon | Commercial Standard | [Intel ARK Product Specifications](https://ark.intel.com/content/www/us/en/ark.html) |
| **Intel Sockets** | Physical Socket | LGA775, LGA1156, LGA1155, LGA1150, LGA1151, LGA1200, LGA1700, LGA1851, BGA (Mobile) | Verified Standard | [Intel Desktop Processor Sockets](https://www.intel.com/content/www/us/en/support/articles/000005592/processors.html) |
| **AMD Processors** | Product Line | AMD Athlon, AMD Ryzen 3 / 5 / 7 / 9, AMD Ryzen Threadripper, AMD EPYC | Commercial Standard | [AMD Official Processor Specifications](https://www.amd.com/en/products/specifications/processors.html) |
| **AMD Sockets** | Physical Socket | Socket AM2, Socket AM3, Socket AM3+, Socket AM4, Socket AM5, Socket sTR5 | Verified Standard | [AMD Socket Specifications](https://www.amd.com/en/products/processors/desktops/ryzen.html) |

---

## 3. Displays & Monitors

| Family / Scope | Dimension / Feature | Standard Values & Units | Classification | Authoritative Source URL |
| :--- | :--- | :--- | :--- | :--- |
| **Displays** | Screen Size | 19", 20", 21.5", 22", 23.8", 24", 27", 29" (Ultrawide), 31.5", 32", 34" (Ultrawide), 38", 49" | Retail Standard | [Dell Professional Monitor Specifications](https://www.dell.com/en-us/shop/monitors/ar/4009) |
| **Displays** | Resolution | 1366x768 (HD), 1600x900 (HD+), 1920x1080 (FHD), 1920x1200 (WUXGA), 2560x1440 (QHD/2K), 3440x1440 (UWQHD), 3840x2160 (4K UHD), 5120x1440 (Dual QHD) | Verified Standard | [VESA Display Standards](https://vesa.org/featured-articles/vesa-standards-summary/) |
| **Displays** | Panel Technology | IPS, Fast IPS, VA, Curved VA, TN, OLED, QD-OLED, Mini-LED | Industry Standard | [VESA DisplayHDR Specifications](https://displayhdr.org/) |
| **Displays** | Refresh Rate | 60Hz, 75Hz, 100Hz, 120Hz, 144Hz, 165Hz, 180Hz, 240Hz, 360Hz | Verified Standard | [VESA Adaptive-Sync Standards](https://www.vesa.org/adaptive-sync/) |
| **Displays** | Video Ports | HDMI 1.4/2.0/2.1, DisplayPort 1.2/1.4/2.1, USB Type-C (DP Alt Mode / 65W+ PD), VGA (D-Sub), DVI-D | Verified Standard | [HDMI Licensing Administrator](https://www.hdmi.org) & [DisplayPort.org](https://www.displayport.org) |

*Note: Screen Size and Resolution are independent attributes. Selecting 27" does not force 2560x1440 or 3840x2160, preserving flexibility across commercial panels.*

---

## 4. Storage, Motherboards, GPUs & Power

| Family / Scope | Dimension / Feature | Standard Values & Units | Classification | Authoritative Source URL |
| :--- | :--- | :--- | :--- | :--- |
| **Solid State Drives** | Form Factor & Interface | M.2 2280 NVMe (PCIe Gen3 / Gen4 / Gen5), M.2 2230/2242 NVMe, M.2 SATA, 2.5" SATA III, mSATA, U.2 (SFF-8639), E1.S / E3.S EDSFF | Verified Standard | [SNIA Solid State Storage Technical Working Group](https://www.snia.org/tech_work/workgroups/sssi) |
| **Solid State Drives** | Capacity | 120GB, 128GB, 240GB, 256GB, 480GB, 500GB, 512GB, 1TB, 2TB, 4TB, 8TB | Retail Standard | [SATA-IO Standards](https://sata-io.org) & [NVM Express Standards](https://nvmexpress.org) |
| **Hard Disk Drives** | Form Factor & Speed | 3.5" SATA III (5400/5900/7200 RPM), 2.5" SATA III (5400/7200 RPM), 3.5" SAS (10K/15K RPM) | Verified Standard | [IDEMA Standards](https://idema.org) |
| **Motherboards** | Form Factor & Chipset | ATX, Micro-ATX, Mini-ITX, E-ATX; Intel H/B/Z series; AMD A/B/X series | Verified Standard | [Intel Motherboard Chipsets](https://www.intel.com/content/www/us/en/products/details/chipsets.html) |
| **Graphics (GPUs)** | GPU Family & Memory | NVIDIA GeForce RTX 30/40/50, NVIDIA Quadro/RTX Ada; AMD Radeon RX 6000/7000; GDDR6, GDDR6X, GDDR7 | Commercial Standard | [NVIDIA Official Specifications](https://www.nvidia.com/en-us/geforce/graphics-cards/) & [AMD Radeon](https://www.amd.com/en/products/graphics/desktops.html) |
| **Power Supplies** | Form Factor & Rating | ATX, SFX, TFX; 80 PLUS White/Bronze/Gold/Platinum/Titanium; ATX 3.0 / PCIe 5.0 (12VHPWR / 12V-2x6) | Verified Standard | [Intel ATX 3.0 / ATX12V Design Guide](https://www.intel.com/content/www/us/en/gaming/resources/power-supply-types.html) |

---

## 5. Networks, Accessories & Office Devices

| Family / Scope | Dimension / Feature | Standard Values & Units | Classification | Authoritative Source URL |
| :--- | :--- | :--- | :--- | :--- |
| **Wi-Fi Connectivity** | Wireless Protocol | Wi-Fi 4 (802.11n), Wi-Fi 5 (802.11ac), Wi-Fi 6 (802.11ax), Wi-Fi 6E (6GHz), Wi-Fi 7 (802.11be) | Verified Standard | [Wi-Fi Alliance Certification](https://www.wi-fi.org/certification) |
| **Ethernet** | Speed & Port Count | 100 Mbps (Fast Ethernet), 1 Gbps (Gigabit), 2.5 Gbps (2.5GbE), 10 Gbps (10GbE); RJ45, SFP+; 5, 8, 16, 24, 48 Ports | Verified Standard | [IEEE 802.3 Ethernet Working Group](https://www.ieee802.org/3/) |
| **Peripherals** | Connectivity Modes | Wired USB, 2.4GHz RF Wireless, Bluetooth 5.x, Dual-Mode (Wired/Wireless), Tri-Mode (Wired/2.4G/BT) | Industry Standard | [Bluetooth SIG](https://www.bluetooth.com) & [USB-IF](https://www.usb.org) |
| **Printers & Scanners** | Print Technology | Laser (Monochrome / Color), Inkjet / Tank, Thermal (Receipt / Label), Dot Matrix; A4, A3 | Retail Standard | [ISO/IEC 24734 Print Standards](https://www.iso.org/standard/54347.html) |

---

## 6. Seed Extensibility Policy

1. **User Customization**: Users may create, rename, or delete any category, subcategory, or attribute in `تنظیمات مدیریت کالاها`. Seed entries provide an initial baseline and do not enforce permanent restrictions.
2. **Clean-Slate Guarantee**: If `default_taxonomy.json` is missing before initializing a fresh database, Daqiq creates an empty database with strictly zero categories, zero subcategories, and zero custom technical fields.
3. **Persian / English Naming Contract**:
   - Main Categories: 100% Persian retail terms.
   - Subcategories: `فارسی (English)` bilingual format.
   - Attributes: Persian `نام ویژگی`, English `نام نمایشی`, Latin-script suggested values.
   - Universal Terminal Field: Every hardware subcategory concludes strictly with `مشخصات` (Specifications).
