# tests/test_license_store.py
"""Unit tests for persistent license storage, atomic updates, recovery, and clock-rollback protection."""

import datetime
import json
import os
import pytest
from unittest.mock import patch

from licensing.license_models import (
    ValidationStatus,
    ClockRollbackError,
    StorageError,
)
from licensing.license_store import (
    LicenseStore,
    LICENSE_FILENAME,
    CLOCK_STATE_FILENAME,
    CLOCK_TOLERANCE_SECONDS,
)
from licensing.license_policy import LicenseService
from licensing.license_verifier import LicenseVerifier
from licensing.device_identity import MockHardwareProvider


@pytest.fixture
def store_paths(tmp_path):
    machine_dir = str(tmp_path / "ProgramData" / "Daqiq" / "Licensing")
    user_dir = str(tmp_path / "LocalAppData" / "Daqiq" / "Licensing")
    return machine_dir, user_dir


def test_first_import_and_reload(store_paths):
    m_dir, u_dir = store_paths
    store = LicenseStore(machine_dir=m_dir, user_dir=u_dir)

    dummy_license = b'{"envelope_version": 1, "test": "data"}'
    saved_path = store.save_license_bytes_atomic(dummy_license)

    assert os.path.isfile(saved_path)
    loaded = store.load_license_bytes()
    assert loaded == dummy_license


def test_permission_error_fallback_to_user_dir(store_paths):
    m_dir, u_dir = store_paths
    store = LicenseStore(machine_dir=m_dir, user_dir=u_dir)

    dummy_license = b'{"envelope_version": 1, "user_fallback": true}'

    # Mock PermissionError when writing to machine directory
    orig_open = open
    def mock_open_func(file, mode="r", *args, **kwargs):
        if str(m_dir) in str(file) and "w" in mode:
            raise PermissionError("Access is denied to ProgramData")
        return orig_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open_func):
        saved_path = store.save_license_bytes_atomic(dummy_license)
        assert u_dir in saved_path
        assert os.path.isfile(saved_path)

    loaded = store.load_license_bytes()
    assert loaded == dummy_license


def test_invalid_import_preserves_existing_valid_license(store_paths, tmp_path):
    m_dir, u_dir = store_paths
    store = LicenseStore(machine_dir=m_dir, user_dir=u_dir)
    hw = MockHardwareProvider()

    service = LicenseService(store=store, hardware_provider=hw)

    # 1. Store initial content
    valid_initial = b'{"valid": "original_content"}'
    store.save_license_bytes_atomic(valid_initial)

    # 2. Candidate invalid license file
    bad_file = tmp_path / "corrupted.daqlic"
    bad_file.write_bytes(b"NOT_A_VALID_JSON_OR_LICENSE")

    res = service.import_license_file(str(bad_file))
    assert res.is_valid is False

    # 3. Ensure store still holds original valid content untouched
    assert store.load_license_bytes() == valid_initial


def test_clock_rollback_detection_on_subscription(store_paths):
    m_dir, u_dir = store_paths
    store = LicenseStore(machine_dir=m_dir, user_dir=u_dir)
    fp = "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"

    t1 = datetime.datetime(2026, 11, 22, 12, 0, 0, tzinfo=datetime.timezone.utc)
    store.check_and_update_clock_state(fp, is_subscription=True, now_utc=t1)

    # Move clock back 1 hour (3600s > tolerance 900s)
    t2_rollback = datetime.datetime(2026, 11, 22, 11, 0, 0, tzinfo=datetime.timezone.utc)
    with pytest.raises(ClockRollbackError, match="عقب کشیدن ساعت"):
        store.check_and_update_clock_state(fp, is_subscription=True, now_utc=t2_rollback)


def test_clock_tolerance_window_accepted(store_paths):
    m_dir, u_dir = store_paths
    store = LicenseStore(machine_dir=m_dir, user_dir=u_dir)
    fp = "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"

    t1 = datetime.datetime(2026, 11, 22, 12, 0, 0, tzinfo=datetime.timezone.utc)
    store.check_and_update_clock_state(fp, is_subscription=True, now_utc=t1)

    # Move clock back by 5 minutes (300s < tolerance 900s) -> allowed without error!
    t2_jitter = datetime.datetime(2026, 11, 22, 11, 55, 0, tzinfo=datetime.timezone.utc)
    store.check_and_update_clock_state(fp, is_subscription=True, now_utc=t2_jitter)


def test_perpetual_license_immunity_to_clock_rollback(store_paths):
    m_dir, u_dir = store_paths
    store = LicenseStore(machine_dir=m_dir, user_dir=u_dir)
    fp = "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"

    t1 = datetime.datetime(2026, 11, 22, 12, 0, 0, tzinfo=datetime.timezone.utc)
    store.check_and_update_clock_state(fp, is_subscription=False, now_utc=t1)

    # Significant clock rollback on perpetual license: should NOT raise ClockRollbackError!
    t2_rollback = datetime.datetime(2020, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
    store.check_and_update_clock_state(fp, is_subscription=False, now_utc=t2_rollback)


def test_corrupted_clock_file_handles_gracefully(store_paths):
    m_dir, u_dir = store_paths
    os.makedirs(m_dir, exist_ok=True)
    bad_clock = os.path.join(m_dir, CLOCK_STATE_FILENAME)
    with open(bad_clock, "w", encoding="utf-8") as f:
        f.write("{broken_json]")

    store = LicenseStore(machine_dir=m_dir, user_dir=u_dir)
    fp = "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"

    # Should not crash on corrupted clock state
    t1 = datetime.datetime(2026, 11, 22, 12, 0, 0, tzinfo=datetime.timezone.utc)
    store.check_and_update_clock_state(fp, is_subscription=True, now_utc=t1)
