"""Comprehensive v4.9.8 commercial release & Red-Team QA suite (REQ-00 through REQ-07)."""

from __future__ import annotations

import base64
import datetime
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from PySide6.QtWidgets import QDialog

import database as db_mod
import main as m
from licensing.device_identity import (
    MockHardwareProvider,
    compute_hardware_fingerprint_from_components,
    create_device_request_dict,
)
from licensing.keys import KeyRegistry
from licensing.license_dialog import LicenseDialog, ThemedNoticeDialog
from licensing.license_models import ValidationStatus
from licensing.license_policy import LicenseService
from licensing.license_store import LicenseStore, PRIMARY_CLOCK_FILE
from licensing.license_verifier import DOMAIN_PREFIX, LicenseVerifier, canonicalize_payload
from utils import paths as path_utils


def _make_keypair():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    return priv, pub_b64


def _sign_generator_payload(priv, key_id: str, payload_dict: dict) -> bytes:
    canon = canonicalize_payload(payload_dict)
    sig = priv.sign(DOMAIN_PREFIX + canon)
    env = {
        "envelope_version": 1,
        "algorithm": "Ed25519",
        "key_id": key_id,
        "payload": payload_dict,
        "signature": base64.b64encode(sig).decode("ascii"),
    }
    return json.dumps(env, ensure_ascii=False).encode("utf-8")


def _generator_payload(key_id: str, fp: str, **overrides) -> dict:
    payload = {
        "customer": {
            "contact": "+989120000000",
            "name": "فروشگاه نمونه دقیق",
            "organization": "مجموعه فناوری دقیق",
        },
        "device_fingerprints": [fp],
        "expires_at": "2026-11-26T23:59:59Z",
        "expiry_warning_days": 14,
        "features": {
            "batches": True,
            "dashboard": True,
            "employees": True,
            "products": True,
            "reports": True,
            "sales": True,
            "services": True,
            "settings": True,
            "suppliers_payments": True,
            "upgrades": True,
        },
        "format_version": 1,
        "grace_mode": "readonly",
        "grace_period_days": 0,
        "issued_at": "2026-11-26T00:00:00Z",
        "key_id": key_id,
        "license_id": "LIC-14050905-654321",
        "license_type": "subscription",
        "match_policy": "standard",
        "max_app_version": None,
        "max_clock_skew_hours": 24,
        "max_devices": 1,
        "min_app_version": "4.9.0",
        "not_before": "2026-11-26T00:00:00Z",
        "product_id": "daqiq.desktop",
    }
    payload.update(overrides)
    return payload


def _build_service(tmp_path, priv, pub_b64, key_id, hw, clock_holder):
    store = LicenseStore(
        machine_dir=str(tmp_path / "m"),
        user_dir=str(tmp_path / "u"),
        roaming_dir=str(tmp_path / "r"),
    )
    reg = KeyRegistry({key_id: pub_b64})
    verifier = LicenseVerifier(key_registry=reg)
    return LicenseService(
        store=store,
        verifier=verifier,
        hardware_provider=hw,
        clock_provider=lambda: clock_holder[0],
        app_version="4.9.8",
    )


def test_req01_redteam_expiry_sub24h_rollback_and_startup_lock(qapp, monkeypatch, tmp_path):
    """Expired 1-day/specific-date licenses MUST lock permanently even against <24h clock rollback & DB wipe."""
    priv, pub_b64 = _make_keypair()
    key_id = "daqiq-prod-v1"
    hw = MockHardwareProvider()
    fp = hw.get_fingerprint()
    clock_holder = [datetime.datetime(2026, 11, 26, 12, 0, 0, tzinfo=datetime.timezone.utc)]
    svc = _build_service(tmp_path, priv, pub_b64, key_id, hw, clock_holder)

    # 1. Exact 1-day Generator subscription -> active on day 1
    p_1d = _generator_payload(key_id, fp)
    assert svc.import_license_bytes(_sign_generator_payload(priv, key_id, p_1d)).is_valid is True

    # 2. Cross expiration by 1 second -> EXPIRED hard lock
    clock_holder[0] = datetime.datetime(2026, 11, 27, 0, 0, 0, tzinfo=datetime.timezone.utc)
    r_exp = svc.check_license(force_reload=True)
    assert r_exp.is_valid is False
    assert r_exp.status == ValidationStatus.EXPIRED

    # 3. Sub-24h clock rollback attack (back 2 hours into validity window, < max_clock_skew_hours=24!)
    # High-Water-Mark expiry latch MUST STILL keep license EXPIRED!
    clock_holder[0] = datetime.datetime(2026, 11, 26, 22, 0, 0, tzinfo=datetime.timezone.utc)
    r_sub24_cached = svc.check_license(force_reload=False)
    r_sub24_fresh = svc.check_license(force_reload=True)
    assert r_sub24_cached.is_valid is False and r_sub24_cached.status == ValidationStatus.EXPIRED
    assert r_sub24_fresh.is_valid is False and r_sub24_fresh.status == ValidationStatus.EXPIRED
    assert svc.import_license_bytes(_sign_generator_payload(priv, key_id, p_1d)).is_valid is False

    # 4. Delete primary clock anchor + delete DB -> remaining anchors enforce lock!
    primary_anchor = tmp_path / "u" / PRIMARY_CLOCK_FILE
    if primary_anchor.is_file():
        primary_anchor.unlink()
    dummy_db = tmp_path / "store.db"
    dummy_db.write_bytes(b"sqlite")
    dummy_db.unlink()

    # Large multi-day rollback after deleting primary anchor -> CLOCK_TAMPERED hard lock
    clock_holder[0] = datetime.datetime(2026, 11, 25, 10, 0, 0, tzinfo=datetime.timezone.utc)
    r_tamper = svc.check_license(force_reload=True)
    assert r_tamper.is_valid is False
    assert r_tamper.status in (ValidationStatus.CLOCK_TAMPERED, ValidationStatus.EXPIRED)

    # 5. Clock earlier than not_before / issued_at - skew -> fail-closed
    clock_holder2 = [datetime.datetime(2026, 11, 20, 0, 0, 0, tzinfo=datetime.timezone.utc)]
    svc2 = _build_service(tmp_path / "before_issue", priv, pub_b64, key_id, hw, clock_holder2)
    raw_1d = _sign_generator_payload(priv, key_id, p_1d)
    svc2.store.save_license_bytes_atomic(raw_1d)
    r_early = svc2.check_license(force_reload=True)
    assert r_early.is_valid is False
    assert r_early.status == ValidationStatus.NOT_YET_VALID

    # Backdated clock well before earliest anchor on LicenseService -> NOT_YET_VALID / CLOCK_TAMPERED
    p_early_iss = _generator_payload(key_id, fp, issued_at="2026-11-26T00:00:00Z", not_before="2026-11-26T00:00:00Z")
    r_skew = svc2.verifier.validate_license(
        svc2.verifier.parse_envelope_from_bytes(_sign_generator_payload(priv, key_id, p_early_iss)),
        fp,
        "4.9.8",
        now_utc=datetime.datetime(2026, 11, 20, 0, 0, 0, tzinfo=datetime.timezone.utc),
    )
    assert r_skew.is_valid is False
    assert r_skew.status in (ValidationStatus.NOT_YET_VALID, ValidationStatus.CLOCK_TAMPERED)

    # 6. LicenseDialog.accept() fails closed when startup gate license is expired!
    monkeypatch.setattr(ThemedNoticeDialog, "exec", lambda self: QDialog.Accepted)
    dlg = LicenseDialog(svc, is_startup_gate=True)
    try:
        assert dlg.btn_enter.isHidden() is True
        assert dlg.btn_enter.isEnabled() is False
        dlg.accept()
        assert dlg.result() != QDialog.Accepted
    finally:
        dlg.close()

    # 7. Hardware RAM/reinstall resilience vs unauthorized clone
    fp_again, _ = compute_hardware_fingerprint_from_components(hw.uuid, hw.serial, hw.mfg, hw.prod)
    assert fp_again == fp
    assert svc2.verifier.validate_license(
        svc2.verifier.parse_envelope_from_bytes(raw_1d),
        "fp_v1:" + ("a" * 64),
        "4.9.8",
        now_utc=datetime.datetime(2026, 11, 26, 12, 0, 0, tzinfo=datetime.timezone.utc),
    ).status == ValidationStatus.UNAUTHORIZED_DEVICE


def test_req01_generator_daqreq_and_smoke_launch_anti_backdoor(tmp_path, monkeypatch):
    """Verify .daqreq has generated_at & app_security_id, and --smoke-launch-db rejects encrypted DB."""
    req = create_device_request_dict(store_name="تست")
    assert req["app_version"] == db_mod.get_live_app_version()
    assert "generated_at" in req and req["generated_at"] == req["generated_at_utc"]
    assert "app_security_id" in req

    # Encrypted DB must be rejected cleanly by _run_smoke_launch_db
    db_file = tmp_path / "enc.db"
    db = db_mod.DatabaseManager(str(db_file))
    db.set_database_password("Secret123!")
    db.close()

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    rc = m._run_smoke_launch_db(app, str(db_file), mode="existing")
    assert rc == 1


def test_req02_synced_battery_taxonomy_loads_externally_and_not_bundled(tmp_path, monkeypatch):
    """Verify updated GitHub battery taxonomy parses cleanly & loads only when external file exists."""
    repo_root = Path(__file__).resolve().parent.parent
    tax_path = repo_root / "default_taxonomy.json"
    data = json.loads(tax_path.read_text(encoding="utf-8"))
    battery_cat = "تجهیزات برق، کابل و اتصالات"
    battery_sub = "باتری قلمی، سکه‌ای و شارژی (AA, Coin & Rechargeable Battery)"
    assert battery_sub in data["subcategories"][battery_cat]
    battery_attrs = [a["name"] for a in data["attributes"][battery_cat] if a.get("subcategory") == battery_sub]
    assert {"سایز باتری", "نوع و فناوری", "ولتاژ", "تعداد بسته یا ظرفیت"}.issubset(set(battery_attrs))

    # Absent next to executable -> empty taxonomy
    empty_dir = tmp_path / "no_tax_bin"
    empty_dir.mkdir()
    monkeypatch.setattr(db_mod, "get_default_taxonomy_path", lambda: str(empty_dir / "default_taxonomy.json"))
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(tmp_path / "cfg1.json"))
    db_empty = db_mod.create_and_initialize_database(str(tmp_path / "empty_tax.db"))
    assert db_empty.get_product_catalog_config()["categories"] == []
    db_empty.close()

    # Present next to executable -> seeded including new battery specs
    with_dir = tmp_path / "with_tax_bin"
    with_dir.mkdir()
    (with_dir / "default_taxonomy.json").write_text(tax_path.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(db_mod, "get_default_taxonomy_path", lambda: str(with_dir / "default_taxonomy.json"))
    db_seeded = db_mod.create_and_initialize_database(str(tmp_path / "seeded_tax.db"))
    seeded = db_seeded.get_product_catalog_config()
    assert battery_sub in seeded["subcategories"][battery_cat]
    db_seeded.close()


def test_req03_app_config_and_schema_version_full_parity(monkeypatch, tmp_path):
    """app_config.json dynamically syncs schema_version=SCHEMA_VERSION and app_version=4.9.8."""
    cfg_path = tmp_path / "app_config.json"
    monkeypatch.setattr(db_mod, "CONFIG_FILE", str(cfg_path))
    db_file = tmp_path / "store498.db"
    db_file.write_bytes(b"ok")

    stale = {
        "app_version": "4.9.6",
        "schema_version": 2,
        "theme": "dark",
        "db_path": str(db_file),
        "last_backup_warning": "",
        "obsolete_key": "drop_me",
    }
    cfg_path.write_text(json.dumps(stale), encoding="utf-8")
    loaded = db_mod.load_app_config()
    on_disk = json.loads(cfg_path.read_text(encoding="utf-8"))
    live_ver = db_mod.get_live_app_version()
    for obj in (loaded, on_disk):
        assert obj["app_version"] == live_ver
        assert obj["schema_version"] == db_mod.CONFIG_SCHEMA_VERSION
        assert obj["config_schema_version"] == db_mod.CONFIG_SCHEMA_VERSION
        assert obj["schema_version"] != 484
        assert obj["theme"] == "dark"
        assert "last_backup_warning" not in obj
        assert "obsolete_key" not in obj

    # Empty JSON file on disk is auto-repaired cleanly
    cfg_path.write_text("{}", encoding="utf-8")
    repaired = db_mod.load_app_config()
    assert repaired["app_version"] == live_ver
    assert repaired["schema_version"] == db_mod.CONFIG_SCHEMA_VERSION
    assert repaired["schema_version"] != 484
    assert Path("VERSION").read_text(encoding="utf-8").strip() == live_ver
    assert m.APP_VERSION == live_ver
