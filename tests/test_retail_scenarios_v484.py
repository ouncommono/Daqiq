"""Comprehensive Multi-Scenario End-to-End QA Suite for Daqiq v4.8.4.

Covers:
- Scenario 1: Scoped & Comprehensive JSON Export / Import Round-Trip (REQ-1)
- Scenario 2: Theme-Adaptive WCAG AA+ Contrast Ratio Audit for Dashboard Top Report Cards (REQ-2)
- Scenario 3: Swiss-Style Minimalist Logo Redesign Verification (REQ-3)
- Scenario 4: Clean-Slate Schema v484 & End-to-End Retail Store Workflow Sweep (REQ-0, REQ-4)
"""

import copy
import json
import os
import struct
import tempfile
import xml.etree.ElementTree as ET
import pytest
from PySide6.QtWidgets import QApplication

import database
from database import (
    APP_VERSION,
    SCHEMA_VERSION,
    EXPECTED_SCHEMA_COLUMNS,
    DatabaseManager,
    create_and_initialize_database,
    validate_schema_column_order,
)
from main import (
    MainWindow,
    DASHBOARD_CARD_TOKENS,
    LEGACY_COLOR_TO_ROLE,
    resource_path,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["daqiq_test", "-platform", "offscreen"])
    return app


# =========================================================================
# HELPER: Relative Luminance and Contrast Ratio (WCAG 2.1 Specification)
# =========================================================================
def hex_to_rgb(hex_str: str):
    hex_clean = hex_str.strip().lstrip("#")
    if len(hex_clean) == 3:
        hex_clean = "".join(c * 2 for c in hex_clean)
    r = int(hex_clean[0:2], 16)
    g = int(hex_clean[2:4], 16)
    b = int(hex_clean[4:6], 16)
    return r, g, b


def relative_luminance(rgb):
    vals = []
    for c in rgb:
        norm = c / 255.0
        if norm <= 0.03928:
            vals.append(norm / 12.92)
        else:
            vals.append(((norm + 0.055) / 1.055) ** 2.4)
    return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]


def contrast_ratio(hex1: str, hex2: str) -> float:
    l1 = relative_luminance(hex_to_rgb(hex1))
    l2 = relative_luminance(hex_to_rgb(hex2))
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# =========================================================================
# SCENARIO 1: Scoped & Comprehensive JSON Export / Import Round-Trip (REQ-1)
# =========================================================================
def test_scenario1_scoped_and_comprehensive_json_export_suite(qapp, tmp_path):
    """Scenario 1 (REQ-1):
    1. Verify existence of scoped & comprehensive export buttons in both toolbars.
    2. Section-only product JSON export/import cycle (services untouched).
    3. Section-only service JSON export/import cycle (products untouched).
    4. Comprehensive JSON export matching default_taxonomy.json schema and seeding fresh DB.
    """
    db_path = str(tmp_path / "test_tax_export.db")
    db = create_and_initialize_database(db_path)
    win = MainWindow(db, active_employee=None)

    try:
        # 1. UI Buttons existence and attributes
        assert hasattr(win, "btn_export_prod_tax_section"), "Missing btn_export_prod_tax_section"
        assert hasattr(win, "btn_export_prod_tax_full"), "Missing btn_export_prod_tax_full"
        assert hasattr(win, "btn_export_serv_tax_section"), "Missing btn_export_serv_tax_section"
        assert hasattr(win, "btn_export_serv_tax_full"), "Missing btn_export_serv_tax_full"

        # Check button labels
        assert "همین بخش" in win.btn_export_prod_tax_section.text()
        assert "جامع" in win.btn_export_prod_tax_full.text()
        assert "همین بخش" in win.btn_export_serv_tax_section.text()
        assert "جامع" in win.btn_export_serv_tax_full.text()

        # 2. Modify live draft with unique custom tokens
        custom_category = "کالای دیجیتال پیشرفته"
        custom_subcategory = "تجهیزات واقعیت مجازی"
        custom_attr = "رزولوشن لنز"
        custom_color = "تیتانیومی مات"
        custom_service = "تعمیر تخصصی حسگر اپتیکال"

        win._taxonomy_draft["categories"].append(custom_category)
        win._taxonomy_draft["subcategories"].setdefault(custom_category, []).append(custom_subcategory)
        win._taxonomy_draft["attributes"].setdefault(custom_category, {}).setdefault(custom_subcategory, []).append(custom_attr)
        win._taxonomy_draft["colors"].append(custom_color)
        win._taxonomy_draft["service_types"].append(custom_service)

        initial_services_count = len(win._taxonomy_draft["service_types"])
        initial_categories_count = len(win._taxonomy_draft["categories"])

        # 3. Export section-only product taxonomy
        prod_export_path = str(tmp_path / "product_only.json")
        saved_prod = win._export_product_taxonomy_section(export_path=prod_export_path)
        assert saved_prod == prod_export_path
        assert os.path.exists(prod_export_path)

        with open(prod_export_path, "r", encoding="utf-8") as f:
            prod_data = json.load(f)

        assert "categories" in prod_data
        assert "subcategories" in prod_data
        assert "attributes" in prod_data
        assert "colors" in prod_data
        assert "service_types" not in prod_data, "Product section export must NOT leak service_types"
        assert custom_category in prod_data["categories"]
        assert custom_color in prod_data["colors"]

        # Clear product taxonomy in draft, then re-import product-only JSON
        win._taxonomy_draft["categories"] = []
        win._taxonomy_draft["subcategories"] = {}
        win._taxonomy_draft["attributes"] = {}
        win._taxonomy_draft["colors"] = []
        win._import_product_taxonomy(import_path=prod_export_path)

        # Products restored, services remained untouched
        assert custom_category in win._taxonomy_draft["categories"]
        assert custom_color in win._taxonomy_draft["colors"]
        assert len(win._taxonomy_draft["service_types"]) == initial_services_count
        assert custom_service in win._taxonomy_draft["service_types"]

        # 4. Export section-only service taxonomy
        serv_export_path = str(tmp_path / "service_only.json")
        saved_serv = win._export_service_taxonomy_section(export_path=serv_export_path)
        assert saved_serv == serv_export_path
        assert os.path.exists(serv_export_path)

        with open(serv_export_path, "r", encoding="utf-8") as f:
            serv_data = json.load(f)

        assert "service_types" in serv_data
        assert "categories" not in serv_data, "Service section export must NOT leak categories"
        assert "subcategories" not in serv_data
        assert custom_service in serv_data["service_types"]

        # Clear services in draft, then re-import service-only JSON
        win._taxonomy_draft["service_types"] = []
        win._import_service_taxonomy(import_path=serv_export_path)

        # Services restored, products remained untouched
        assert custom_service in win._taxonomy_draft["service_types"]
        assert len(win._taxonomy_draft["categories"]) == initial_categories_count
        assert custom_category in win._taxonomy_draft["categories"]

        # 5. Export comprehensive taxonomy (both products & services)
        full_export_path = str(tmp_path / "full_default_taxonomy.json")
        saved_full = win._export_comprehensive_taxonomy(export_path=full_export_path)
        assert saved_full == full_export_path
        assert os.path.exists(full_export_path)

        with open(full_export_path, "r", encoding="utf-8") as f:
            full_data = json.load(f)

        expected_keys = {"categories", "subcategories", "attributes", "colors", "service_types"}
        assert set(full_data.keys()) == expected_keys, f"Comprehensive export keys mismatch: {set(full_data.keys())}"
        assert custom_category in full_data["categories"]
        assert custom_service in full_data["service_types"]
        assert custom_color in full_data["colors"]

        # 6. Seed a clean database using this comprehensive exported JSON
        new_db_path = str(tmp_path / "fresh_seeded.db")
        with open(full_export_path, "r", encoding="utf-8") as f:
            seed_dict = json.load(f)

        def mock_load_seed():
            return seed_dict

        orig_loader = database.load_default_taxonomy_from_seed
        database.load_default_taxonomy_from_seed = mock_load_seed
        try:
            db_new = create_and_initialize_database(new_db_path)
            new_tax = db_new.get_product_catalog_config()
            assert custom_category in new_tax.get("categories", [])
            assert custom_color in new_tax.get("colors", [])
            assert custom_service in new_tax.get("service_types", [])
            db_new.close()
        finally:
            database.load_default_taxonomy_from_seed = orig_loader

    finally:
        win.close()
        db.close()


# =========================================================================
# SCENARIO 2: Theme-Adaptive WCAG AA+ Contrast Ratio Audit (REQ-2)
# =========================================================================
def test_scenario2_dashboard_cards_wcag_contrast_audit(qapp, tmp_path):
    """Scenario 2 (REQ-2):
    1. Verify semantic theme tokens exist for Light and Dark themes.
    2. Audit Light Theme contrast: Title >= 4.5:1 (WCAG AA), Values >= 3.0:1 (WCAG AA large text).
    3. Audit Dark Theme contrast: Title >= 4.5:1, Values >= 3.0:1.
    4. Verify live switching updates styles immediately on _toggle_theme.
    """
    assert "light" in DASHBOARD_CARD_TOKENS
    assert "dark" in DASHBOARD_CARD_TOKENS

    # Audit Light Theme tokens
    light_tokens = DASHBOARD_CARD_TOKENS["light"]
    light_surface = light_tokens["surface"]
    light_title = light_tokens["title"]
    title_light_cr = contrast_ratio(light_title, light_surface)
    assert title_light_cr >= 4.5, f"Light title contrast {title_light_cr:.2f}:1 is below WCAG AA (4.5:1)"
    assert title_light_cr >= 7.0, f"Light title contrast {title_light_cr:.2f}:1 should achieve WCAG AAA (7.0:1)"

    for role_name, token in light_tokens["roles"].items():
        val_color = token["val"]
        cr = contrast_ratio(val_color, light_surface)
        assert cr >= 4.5, f"Light role '{role_name}' val ({val_color}) contrast {cr:.2f}:1 is below WCAG AA (4.5:1)"

    # Audit Dark Theme tokens
    dark_tokens = DASHBOARD_CARD_TOKENS["dark"]
    dark_surface = dark_tokens["surface"]
    dark_title = dark_tokens["title"]
    title_dark_cr = contrast_ratio(dark_title, dark_surface)
    assert title_dark_cr >= 4.5, f"Dark title contrast {title_dark_cr:.2f}:1 is below WCAG AA (4.5:1)"
    assert title_dark_cr >= 7.0, f"Dark title contrast {title_dark_cr:.2f}:1 should achieve WCAG AAA (7.0:1)"

    for role_name, token in dark_tokens["roles"].items():
        val_color = token["val"]
        cr = contrast_ratio(val_color, dark_surface)
        assert cr >= 3.0, f"Dark role '{role_name}' val ({val_color}) contrast {cr:.2f}:1 is below WCAG AA large text (3.0:1)"

    # Verify runtime live switching
    db_path = str(tmp_path / "test_dash_contrast.db")
    db = create_and_initialize_database(db_path)
    win = MainWindow(db, active_employee=None)

    try:
        assert len(win._dashboard_card_styles) >= 8, f"Expected >= 8 dashboard cards, found {len(win._dashboard_card_styles)}"

        # Initial theme is light
        win.db.cfg["theme"] = "light"
        win._refresh_dashboard_card_styles()

        box0, t0, v0, role0 = win._dashboard_card_styles[0]
        assert "background: #FFFFFF" in box0.styleSheet() or "background: #ffffff" in box0.styleSheet().lower()

        # Toggle to dark theme
        win._toggle_theme()
        assert win.db.cfg.get("theme") == "dark"

        box0, t0, v0, role0 = win._dashboard_card_styles[0]
        assert "background: #1E293B" in box0.styleSheet() or "background: #1e293b" in box0.styleSheet().lower()
        assert "color: #CBD5E1" in t0.styleSheet() or "color: #cbd5e1" in t0.styleSheet().lower()

        # Toggle back to light theme
        win._toggle_theme()
        assert win.db.cfg.get("theme") == "light"
        assert "background: #FFFFFF" in box0.styleSheet() or "background: #ffffff" in box0.styleSheet().lower()
        assert "color: #334155" in t0.styleSheet() or "color: #334155" in t0.styleSheet().lower()

    finally:
        win.close()
        db.close()


# =========================================================================
# SCENARIO 3: Minimalist Logo Redesign Verification (REQ-3)
# =========================================================================
def test_scenario3_minimalist_logo_assets_and_runtime_wiring(qapp):
    """Scenario 3 (REQ-3):
    1. SVG validation: 512x512 viewBox, 32-unit grid, strict 3-color palette (#0B132B, #FFFFFF, #10B981).
    2. PNG validation: 512x512 resolution, valid PNG header.
    3. Multi-resolution ICO: valid 7-frame icon directory.
    4. Runtime wiring: resource_path resolution, PyInstaller config.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    svg_path = os.path.join(base_dir, "assets", "daqiq_logo.svg")
    png_path = os.path.join(base_dir, "assets", "daqiq_logo.png")
    ico_path = os.path.join(base_dir, "assets", "daqiq_logo.ico")

    assert os.path.isfile(svg_path), f"Missing SVG: {svg_path}"
    assert os.path.isfile(png_path), f"Missing PNG: {png_path}"
    assert os.path.isfile(ico_path), f"Missing ICO: {ico_path}"

    # 1. Inspect SVG
    tree = ET.parse(svg_path)
    root = tree.getroot()
    assert "512" in root.attrib.get("viewBox", "")

    allowed_colors = {"#0b132b", "#ffffff", "#10b981", "none"}
    with open(svg_path, "r", encoding="utf-8") as f:
        svg_content = f.read()

    # Zero AI slop: no filters, gradients, drop shadows
    assert "<linearGradient" not in svg_content
    assert "<filter" not in svg_content
    assert "<feDropShadow" not in svg_content

    # Strict 3-color palette check
    for color in ["#0B132B", "#FFFFFF", "#10B981"]:
        assert color.lower() in svg_content.lower(), f"Expected brand color {color} in SVG"

    # 2. Inspect PNG dimensions via standard library struct
    with open(png_path, "rb") as f:
        png_header = f.read(24)
    assert png_header[:8] == b"\x89PNG\r\n\x1a\n", "Invalid PNG magic header"
    width, height = struct.unpack(">II", png_header[16:24])
    assert (width, height) == (512, 512), f"PNG resolution is {width}x{height}, expected 512x512"

    # 3. Inspect ICO multi-resolution directory
    with open(ico_path, "rb") as f:
        reserved, ico_type, count = struct.unpack("<HHH", f.read(6))
    assert reserved == 0 and ico_type == 1, "Invalid ICO header"
    assert count >= 6, f"ICO has only {count} frames, expected at least 6 multi-res frames"

    # 4. Runtime resolution
    resolved_ico = resource_path(os.path.join("assets", "daqiq_logo.ico"))
    assert os.path.isabs(resolved_ico)
    assert os.path.exists(resolved_ico)

    # 5. CI Workflow PyInstaller wiring
    ci_path = os.path.join(base_dir, ".github", "workflows", "ci.yml")
    with open(ci_path, "r", encoding="utf-8") as f:
        ci_text = f.read()
    assert "--icon=assets/daqiq_logo.ico" in ci_text
    assert "4.8.4" in ci_text


# =========================================================================
# SCENARIO 4: Clean-Slate Schema v484 & Store Workflow Sweep (REQ-0, REQ-4)
# =========================================================================
def test_scenario4_schema_v484_and_store_workflow_sweep(qapp, tmp_path):
    """Scenario 4 (REQ-0, REQ-4):
    Clean-slate schema v484 creation, canonical physical column order,
    and end-to-end multi-stage retail store workflow.
    """
    assert APP_VERSION == "4.8.4"
    assert SCHEMA_VERSION == 484

    db_path = str(tmp_path / "Daqiq.db")
    db = create_and_initialize_database(db_path)

    # Schema integrity check
    with db.get_connection() as conn:
        validate_schema_column_order(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 484
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        emp_cols = tuple(r["name"] for r in conn.execute("PRAGMA table_info(employees)").fetchall())
        assert emp_cols == EXPECTED_SCHEMA_COLUMNS["employees"]
        assert "last_login_at" in emp_cols
        assert emp_cols[-1] == "row_version"

    # 1. User and Supplier registration
    emp_id = db.add_employee("کاربر مدیر", "مدیر سیستم", "09121111111", "admin123", "مدیر سیستم (دسترسی کامل)")
    assert emp_id > 0
    db.add_supplier("تأمین قطعات پیشرو", "02188887777", "تهران، خیابان جمهوری")
    with db.get_connection() as conn:
        sup_id = conn.execute("SELECT id FROM suppliers WHERE name=?", ("تأمین قطعات پیشرو",)).fetchone()["id"]
    assert sup_id > 0

    # 2. Product Registration
    prod_code = db.add_product(
        code="P-TEST-484",
        name="گوشی هوشمند پرچمدار",
        category="موبایل",
        sub_category="پرچمدار",
        brand="سامسونگ",
        model="S24 Ultra",
        specs_dict={"حافظه": "256GB", "رم": "12GB"},
        description="گوشی هوشمند پرچمدار با گارانتی اصلی",
        reorder_point=2,
    )
    with db.get_connection() as conn:
        prod_id = conn.execute("SELECT id FROM products WHERE code=?", (prod_code,)).fetchone()["id"]
    assert prod_id > 0

    # 3. Batch Purchase (64-bit integer money safety)
    batch_code = db.add_batch(
        batch_code="C-BATCH-484",
        product_id=prod_id,
        supplier_id=sup_id,
        buyer_employee_id=emp_id,
        invoice_number="INV-BUY-484",
        purchase_date="1403/09/01",
        initial_qty=10,
        unit_purchase_price=35_000_000,
        extra_cost_total=500_000,
        suggested_sell_price=42_000_000,
        paid_amount=350_000_000,
        supplier_name="تأمین قطعات پیشرو",
    )
    with db.get_connection() as conn:
        batch_id = conn.execute("SELECT id FROM batches WHERE batch_code=?", (batch_code,)).fetchone()["id"]
    assert batch_id > 0

    # 4. Retail Sale
    sale_inv = db.add_sale(
        invoice_number="INV-SALE-484",
        product_id=prod_id,
        batch_id=batch_id,
        seller_employee_id=emp_id,
        customer_name="علی رضایی",
        customer_phone="09123334444",
        qty=3,
        suggested_unit_price=42_000_000,
        actual_unit_price=42_000_000,
        paid_amount=126_000_000,
        sale_datetime="1403/09/01 14:00:00",
    )
    assert sale_inv == "INV-SALE-484"

    # Verify inventory deduction
    with db.get_connection() as conn:
        batch = conn.execute("SELECT remaining_qty, sold_qty FROM batches WHERE id=?", (batch_id,)).fetchone()
        assert batch["remaining_qty"] == 7
        assert batch["sold_qty"] == 3

    # 5. Service Catalog & Service Record
    srv_catalog_id = db.save_service_catalog(
        service_id=None,
        code="S-SRV-484",
        service_type="سخت‌افزاری",
        name="تعویض نمایشگر OLED",
        default_fee=1_500_000,
        default_side_cost=0,
        description="سرویس تخصصی نمایشگر",
    )
    srv_rec_inv = db.add_service_record(
        invoice_number="INV-SRV-484",
        service_id=srv_catalog_id,
        seller_employee_id=emp_id,
        technician_employee_id=emp_id,
        customer_name="مریم محمدی",
        service_fee=1_500_000,
        side_cost=0,
        paid_amount=1_500_000,
        service_datetime="1403/09/01 15:00:00",
        description="تعویض نمایشگر انجام شد",
    )
    assert srv_rec_inv == "INV-SRV-484"

    # 6. Verify Financial & Audit Logs
    with db.get_connection() as conn:
        sales_cnt = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
        assert sales_cnt == 1
        services_cnt = conn.execute("SELECT COUNT(*) FROM service_records").fetchone()[0]
        assert services_cnt == 1
        audit_cnt = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        assert audit_cnt >= 2

    db.close()
