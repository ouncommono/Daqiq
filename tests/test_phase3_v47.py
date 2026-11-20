import os
import sys
import json
import pytest
from PySide6.QtWidgets import QApplication

from database import DatabaseManager, load_default_taxonomy_from_seed, get_default_taxonomy_path
from main import MainWindow
from utils_and_widgets import normalize_catalog_label

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["daqiq_test", "-platform", "offscreen"])
    return app

def test_phase3_taxonomy_file_and_seed(tmp_path):
    tax_path = get_default_taxonomy_path()
    assert os.path.exists(tax_path), f"default_taxonomy.json not found at {tax_path}"
    
    with open(tax_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # 1. Categories
    categories = data.get("categories", [])
    assert len(categories) >= 8
    assert categories[-1] == "سایر موارد", f"Last category is {categories[-1]}, expected 'سایر موارد'"
    
    # 2. Subcategories
    for cat in categories:
        subs = data.get("subcategories", {}).get(cat, [])
        assert len(subs) > 0, f"No subcategories for category {cat}"
        assert subs[-1] == "سایر موارد", f"Last subcategory for {cat} is {subs[-1]}, expected 'سایر موارد'"
    
    # 3. Attributes
    for cat in categories:
        attrs = data.get("attributes", {}).get(cat, [])
        assert len(attrs) > 0, f"No attributes for category {cat}"
        assert attrs[-1]["name"] == "مشخصات", f"Last attribute for {cat} is {attrs[-1]['name']}, expected 'مشخصات'"
        if cat == "سایر موارد":
            assert len(attrs) == 1, f"'سایر موارد' category should have exactly 1 attribute (مشخصات), got {len(attrs)}"

    # 4. Service types
    st = data.get("service_types", [])
    assert len(st) == 6
    assert "تعمیرات سخت‌افزاری" in st
    assert "نصب سیستم‌عامل و نرم‌افزار" in st
    assert "کانفیگ و راه‌اندازی شبکه" in st

    # 5. DB Seeding
    db_file = os.path.join(tmp_path, "seed_test.db")
    db = DatabaseManager(db_file)
    cfg = db.get_product_catalog_config()
    assert cfg.get("categories")[-1] == "سایر موارد"
    assert len(cfg.get("service_types")) == 6
    db.close()

def test_phase3_sayer_mowared_ux(qapp, tmp_path):
    db_file = os.path.join(tmp_path, "ux_test.db")
    db = DatabaseManager(db_file)
    
    win = MainWindow(db=db)
    
    # Ensure window initialized
    assert hasattr(win, "specs_widget")
    assert hasattr(win, "cb_prod_cat")
    
    # 1. Switch to 'سایر موارد' category
    sayer_index = -1
    for i in range(win.cb_prod_cat.count()):
        if normalize_catalog_label(win.cb_prod_cat.itemText(i)) == normalize_catalog_label("سایر موارد"):
            sayer_index = i
            break
    assert sayer_index >= 0, "Category 'سایر موارد' not found in cb_prod_cat"
    
    win.cb_prod_cat.setCurrentIndex(sayer_index)
    
    # Verify cb_sub is editable
    assert win.specs_widget.cb_sub.isEditable() == True
    
    # Verify typing custom subcategory works
    win.specs_widget.set_sub_category("کارت خوان سفارشی")
    assert win.specs_widget.get_sub_category() == "کارت خوان سفارشی"
    
    # Verify ONLY 'مشخصات' attribute is visible/present in fields
    visible_fields = list(win.specs_widget.fields.keys())
    assert len(visible_fields) == 1
    assert normalize_catalog_label(visible_fields[0]) == normalize_catalog_label("مشخصات")
    
    # 2. Switch back to 'قطعات اصلی کامپیوتر'
    pc_index = -1
    for i in range(win.cb_prod_cat.count()):
        if normalize_catalog_label(win.cb_prod_cat.itemText(i)) == normalize_catalog_label("قطعات اصلی کامپیوتر"):
            pc_index = i
            break
    assert pc_index >= 0
    win.cb_prod_cat.setCurrentIndex(pc_index)
    
    # Verify cb_sub is NOT editable
    assert win.specs_widget.cb_sub.isEditable() == False
    
    # Select RAM subcategory
    ram_index = -1
    for i in range(win.specs_widget.cb_sub.count()):
        if "Desktop RAM" in win.specs_widget.cb_sub.itemText(i) or "رم کامپیوتر" in win.specs_widget.cb_sub.itemText(i):
            ram_index = i
            break
    assert ram_index >= 0
    win.specs_widget.cb_sub.setCurrentIndex(ram_index)
    
    # Check that multiple fields exist and 'مشخصات' is strictly the last field
    ram_fields = list(win.specs_widget.fields.keys())
    assert len(ram_fields) > 1
    assert normalize_catalog_label(ram_fields[-1]) == normalize_catalog_label("مشخصات")
    
    # Now select 'سایر موارد' as the subcategory in 'قطعات اصلی کامپیوتر'
    other_sub_index = -1
    for i in range(win.specs_widget.cb_sub.count()):
        if normalize_catalog_label(win.specs_widget.cb_sub.itemText(i)) == normalize_catalog_label("سایر موارد"):
            other_sub_index = i
            break
    assert other_sub_index >= 0
    win.specs_widget.cb_sub.setCurrentIndex(other_sub_index)
    
    # Verify ONLY 'مشخصات' is visible
    fields_under_other_sub = list(win.specs_widget.fields.keys())
    assert len(fields_under_other_sub) == 1
    assert normalize_catalog_label(fields_under_other_sub[0]) == normalize_catalog_label("مشخصات")
    
    win.close()
    db.close()
