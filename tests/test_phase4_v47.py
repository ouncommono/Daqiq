import os
import sys
import json
import time
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from database import DatabaseManager, sqlite3
from main import MainWindow, _is_valid_sqlite_database_file

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["daqiq_test", "-platform", "offscreen"])
    return app

def test_phase4_encryption_lifecycle_and_reconnect(tmp_path):
    db_file = os.path.join(tmp_path, "secure_vault.db")
    db = DatabaseManager(db_file)
    assert not db.is_password_protected()
    assert _is_valid_sqlite_database_file(db_file)

    # 1. Set password to '12345'
    db.set_database_password("12345")
    assert db.is_password_protected()
    assert DatabaseManager.is_database_file_encrypted(db_file)
    db.close()

    # 2. Reconnect integrity check: _is_valid_sqlite_database_file MUST return True
    assert _is_valid_sqlite_database_file(db_file) == True

    # 3. External interoperability check: without key must fail
    c_bad = sqlite3.connect(db_file)
    try:
        with pytest.raises(Exception):
            c_bad.execute("SELECT count(*) FROM sqlite_master")
    finally:
        c_bad.close()

    # 4. External interoperability check: with SQLCipher key '12345' must succeed
    c_good = sqlite3.connect(db_file)
    try:
        c_good.execute("PRAGMA key = '12345'")
        row = c_good.execute("PRAGMA quick_check").fetchone()
        assert row and row[0] == "ok"
    finally:
        c_good.close()

    # 5. Zero plaintext password leakage: app_config.json check
    with open(db.cfg.get("config_file", "app_config.json"), "r", encoding="utf-8") as f:
        cfg_disk = json.load(f)
    assert "local_db_unlock_tokens" not in cfg_disk
    for k, v in cfg_disk.items():
        assert "12345" not in str(v)

    # 6. Change password to '54321'
    db_reopened = DatabaseManager(db_file)
    assert db_reopened.verify_database_password("12345") == True
    db_reopened.change_database_password("12345", "54321")
    db_reopened.close()

    # Verify old password fails, new succeeds
    db_reopened2 = DatabaseManager(db_file)
    assert db_reopened2.verify_database_password("12345") == False
    assert db_reopened2.verify_database_password("54321") == True
    
    # 7. Remove password (decrypt to plain SQLite)
    db_reopened2.remove_database_password("54321")
    assert not db_reopened2.is_password_protected()
    db_reopened2.close()

    # Verify plain connect now works
    c_plain = sqlite3.connect(db_file)
    try:
        assert c_plain.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        c_plain.close()

def test_phase4_settings_save_latency_and_ui_polish(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    db_file = os.path.join(tmp_path, "ui_polish_test.db")
    db = DatabaseManager(db_file)
    win = MainWindow(db=db)

    # Check UI Polish
    assert hasattr(win, "lbl_db_pwd_status")
    assert win.lbl_db_pwd_status.wordWrap() == False

    # Check settings save latency
    start = time.perf_counter()
    win._save_general_settings()
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"Settings save too slow: {elapsed:.2f}s"

    win.close()
    db.close()
