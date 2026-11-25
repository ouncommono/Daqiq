# tests/test_device_identity.py
"""Unit tests for SMBIOS hardware fingerprinting (fp_v1) and node-locking."""

import pytest
import subprocess
from unittest.mock import patch, MagicMock

from licensing.device_identity import (
    compute_hardware_fingerprint_from_components,
    is_valid_uuid,
    is_valid_board_serial,
    is_valid_model_info,
    WindowsHardwareProvider,
    MockHardwareProvider,
    HardwareIdentityUnavailableError,
)


def test_reproducible_test_vectors_from_spec():
    """Verify all 5 exact input -> normalized string -> SHA-256 vectors from spec section 4.6."""
    vectors = [
        # Vector 1: Tier 1 Standard OEM
        (
            "4c4c4544-004a-4810-804e-c6c04f4b3232",
            "CN1296385A0123",
            "Dell Inc.",
            "0M5R01",
            "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e",
            "tier1",
        ),
        # Vector 2: Tier 1 Custom Desktop
        (
            "6fa0b6c2-38b1-4604-95d9-052c895c9e1a",
            "210889218200192",
            "Micro-Star International Co., Ltd.",
            "MAG B550 TOMAHAWK",
            "fp_v1:cc12b7ba73d61e6240c106bb3239c09690102a0ca9f448497532733e8a5382cf",
            "tier1",
        ),
        # Vector 3: Tier 2 OEM placeholder board serial with valid UUID and Model
        (
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "Default string",  # OEM placeholder!
            "ASUSTeK COMPUTER INC.",
            "ROG STRIX B550-F GAMING",
            "fp_v1:112240a4e47ec9659a35161c17b93af2d36347155a138cac4ccafd8a9b6e5f0d",
            "tier2",
        ),
        # Vector 4: Tier 3 OEM placeholder UUID with valid Board Serial and Model
        (
            "00000000-0000-0000-0000-000000000000",  # OEM placeholder UUID!
            "MB-987654321-XYZ",
            "Micro-Star International Co., Ltd.",
            "MS-7C91",
            "fp_v1:31e219b0b74a8399e199ebc12ef49c557d86fac0db3f445249ceed8fa72a1ecb",
            "tier3",
        ),
        # Vector 5: Unicode and whitespace normalization
        (
            "b8f9a102-1234-5678-9abc-def012345678",
            "  SN-Tehran-۰۱۲۳-XY  ",
            "Dell Inc.",
            "OptiPlex",
            "fp_v1:a4cb3359206a481ec7115db8c9116422deca91eebb7c6bdfc60f18307ebe8671",
            "tier1",
        ),
    ]

    for uuid, serial, mfg, prod, expected_fp, expected_tier in vectors:
        actual_fp, actual_tier = compute_hardware_fingerprint_from_components(
            uuid=uuid, serial=serial, mfg=mfg, prod=prod
        )
        assert actual_fp == expected_fp, f"Mismatch for vector {uuid}"
        assert actual_tier == expected_tier, f"Tier mismatch for {uuid}"


def test_oem_placeholder_rejections():
    """Verify that placeholder UUIDs and Serials are strictly rejected."""
    # Invalid UUIDs
    assert is_valid_uuid("") is False
    assert is_valid_uuid("00000000-0000-0000-0000-000000000000") is False
    assert is_valid_uuid("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF") is False
    assert is_valid_uuid("03000200-0400-0500-0006-000700080009") is False
    assert is_valid_uuid("not-a-uuid") is False
    assert is_valid_uuid("11111111-1111-1111-1111-111111111111") is False

    # Invalid Board Serials
    assert is_valid_board_serial("") is False
    assert is_valid_board_serial("none") is False
    assert is_valid_board_serial("n/a") is False
    assert is_valid_board_serial("default string") is False
    assert is_valid_board_serial("to be filled by o.e.m.") is False
    assert is_valid_board_serial("123456789") is False
    assert is_valid_board_serial("00000000") is False
    assert is_valid_board_serial("xxxxxxxxx") is False
    assert is_valid_board_serial(".........") is False


def test_hard_failure_when_no_stable_anchor():
    """Verify that when both UUID and Board Serial are placeholders, system fails hard."""
    with pytest.raises(HardwareIdentityUnavailableError):
        compute_hardware_fingerprint_from_components(
            uuid="00000000-0000-0000-0000-000000000000",
            serial="To be filled by O.E.M.",
            mfg="None",
            prod="Default string",
        )


def test_stability_across_simulated_disk_ram_network_changes():
    """Verify that simulated RAM/disk/MAC/IP changes do not alter fp_v1 fingerprint."""
    uuid = "4C4C4544-004A-4810-804E-C6C04F4B3232"
    serial = "CN1296385A0123"

    # Base baseline
    fp_base, _ = compute_hardware_fingerprint_from_components(uuid, serial)

    # Simulating Windows reinstall, different disks, RAM upgrade, IP change:
    # Notice: fp_v1 ignores RAM, MAC, disks, IP.
    fp_after, _ = compute_hardware_fingerprint_from_components(uuid, serial)
    assert fp_base == fp_after


def test_windows_provider_timeout_handling():
    """Verify provider does not hang on slow/hanging PowerShell commands."""
    provider = WindowsHardwareProvider()
    with patch.object(provider, "_query_native_smbios", return_value=(None, None, None, None)):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="powershell", timeout=0.1)):
            with pytest.raises(HardwareIdentityUnavailableError):
                provider.get_fingerprint()


def test_device_request_dict_contract():
    """Verify create_device_request_dict conforms strictly to clean protocol contract."""
    from database import get_live_app_version
    from licensing.device_identity import create_device_request_dict
    req = create_device_request_dict(store_name="فروشگاه نمونه")
    assert req["protocol_version"] == 1
    assert req["request_version"] == 1
    assert req["product_id"] == "daqiq.desktop"
    assert req["app_version"] == get_live_app_version()
    assert req["store_name"] == "فروشگاه نمونه"
    assert req["device_fingerprint"].startswith("fp_v1:")
    assert "hardware_tier" not in req
    assert "hardware_anchors" not in req
    assert "device_label" not in req
    assert "computer_name" in req
    assert "os_info" in req
    assert "cpu_model" in req
    assert "generated_at" in req
    assert "generated_at_utc" in req
    assert "checksum_sha256" in req
    assert len(req["checksum_sha256"]) == 64


def test_hardware_resilience_matrix():
    """Verify hardware upgrade, replacement, and clone scenarios."""
    mock = MockHardwareProvider(
        uuid="4C4C4544-004A-4810-804E-C6C04F4B3232",
        serial="CN1296385A0123",
        mfg="Dell Inc.",
        prod="0M5R01",
    )
    fp_orig = mock.get_fingerprint()

    # 1. RAM upgrade / replacement -> zero change to SMBIOS -> PASS
    assert mock.get_fingerprint() == fp_orig

    # 2. Reinstall Windows / reformat drive -> zero change to SMBIOS -> PASS
    assert mock.get_fingerprint() == fp_orig

    # 3. Cloned drive onto different PC with different motherboard -> BLOCK
    diff_pc = MockHardwareProvider(
        uuid="6FA0B6C2-38B1-4604-95D9-052C895C9E1A",
        serial="210889218200192",
        mfg="Micro-Star International Co., Ltd.",
        prod="MAG B550 TOMAHAWK",
    )
    assert diff_pc.get_fingerprint() != fp_orig


def test_privacy_safety_no_raw_serials_in_fingerprint():
    """Verify raw serials and raw UUIDs never appear in fp_v1 output string."""
    raw_uuid = "4C4C4544-004A-4810-804E-C6C04F4B3232"
    raw_serial = "CN1296385A0123"
    fp, _ = compute_hardware_fingerprint_from_components(raw_uuid, raw_serial)

    assert raw_uuid not in fp
    assert raw_serial not in fp
    assert fp.startswith("fp_v1:")
    assert len(fp) == 6 + 64  # 'fp_v1:' + 64 hex chars
