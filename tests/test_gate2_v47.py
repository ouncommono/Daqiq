import os
import tempfile
import pytest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import database
from database import DatabaseManager
import main as main_module
from main import MainWindow


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["test-gate2"])
    yield app


def test_gate2_deletion_invariant_v47(qapp):
    """
    MANDATORY GATE 2 TEST:
    If default_taxonomy.json is missing before creating a new database:
    - DB initializes cleanly.
    - Exactly 0 categories, 0 subcategories, 0 specs, and 0 service_types are created.
    - The application launches cleanly without error.
    - The user can manually define service_types and categories from scratch cleanly.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "clean_empty.db")
        config_path = os.path.join(tmp_dir, "app_config.json")
        tax_path = os.path.join(tmp_dir, "default_taxonomy.json")

        with patch.object(database, "CONFIG_FILE", config_path), \
             patch.object(database, "get_default_taxonomy_path", return_value=tax_path), \
             patch("main.QMessageBox.information", return_value=None), \
             patch("main.QMessageBox.warning", return_value=None), \
             patch("main.QMessageBox.question", return_value=None):

            # Ensure default_taxonomy.json does not exist
            if os.path.exists(tax_path):
                os.remove(tax_path)

            db = DatabaseManager(db_path)
            catalog = db.get_product_catalog_config()

            assert catalog["categories"] == [], f"Expected 0 categories, got {catalog['categories']}"
            assert catalog["subcategories"] == {}, f"Expected 0 subcategories, got {catalog['subcategories']}"
            assert catalog["attributes"] == {}, f"Expected 0 attributes, got {catalog['attributes']}"
            assert catalog.get("service_types") == [], f"Expected 0 service_types, got {catalog.get('service_types')}"

            # Verify MainWindow launches cleanly from this completely empty state
            window = MainWindow(db, active_employee=None)
            try:
                assert window.lst_cfg_service_types.count() == 0, "Expected empty service types list"
                assert window.cb_cfg_category.count() == 0, "Expected empty categories combobox"

                # Manually add a service type in settings
                window.ed_cfg_service_type.setText("پشتیبانی فنی")
                window._add_catalog_service_type()
                assert window.lst_cfg_service_types.count() == 1
                assert window.lst_cfg_service_types.item(0).text() == "پشتیبانی فنی"

                # Manually add a product category in settings
                window.ed_cfg_category.setText("قطعات سفارشی")
                window._add_catalog_category()
                assert window.cb_cfg_category.count() == 1
                assert window.cb_cfg_category.currentText() == "قطعات سفارشی"

                # Add a subcategory under the new category
                window.ed_cfg_subcategory.setText("کابل خاص")
                window._add_catalog_subcategory()
                assert window.lst_cfg_subcategories.count() == 1
                assert window.lst_cfg_subcategories.item(0).text() == "کابل خاص"

                # Save the new custom taxonomy
                window._save_general_settings()

                # Verify persisted state
                saved_catalog = db.get_product_catalog_config()
                assert saved_catalog["categories"] == ["قطعات سفارشی"]
                assert saved_catalog["subcategories"]["قطعات سفارشی"] == ["کابل خاص"]
                assert saved_catalog["service_types"] == ["پشتیبانی فنی"]

            finally:
                window.close()
