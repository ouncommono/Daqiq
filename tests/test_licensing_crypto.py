# tests/test_licensing_crypto.py
"""Comprehensive unit tests for Ed25519 licensing cryptography, canonicalization, and schemas."""

import base64
import copy
import datetime
import json
import pytest
import unicodedata
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from licensing.license_models import (
    CustomerInfo,
    LicensePayload,
    LicenseEnvelope,
    ValidationStatus,
    ValidationResult,
    LicensingError,
    CryptoVerificationError,
)
from licensing.keys import KeyRegistry
from licensing.license_verifier import (
    LicenseVerifier,
    canonicalize_payload,
    DOMAIN_PREFIX,
    MAX_LICENSE_FILE_BYTES,
)


@pytest.fixture
def ephemeral_keypair():
    """Generate ephemeral Ed25519 keypair in memory for test duration (never committed)."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    return priv, pub, pub_b64


@pytest.fixture
def valid_payload_dict():
    return {
        "customer": {
            "contact": "+989120000000",
            "name": "فروشگاه تست دقت",
            "organization": "شرکت تست",
        },
        "device_fingerprints": [
            "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"
        ],
        "expires_at": None,
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
        "issued_at": "2026-11-22T00:00:00Z",
        "key_id": "test-key-v1",
        "license_id": "LIC-2026-TEST-001",
        "license_type": "perpetual",
        "max_app_version": None,
        "max_devices": 1,
        "min_app_version": "4.9.0",
        "not_before": "2026-11-22T00:00:00Z",
        "product_id": "daqiq.desktop",
    }


def make_signed_envelope(priv_key, key_id, payload_dict):
    canon = canonicalize_payload(payload_dict)
    sig = priv_key.sign(DOMAIN_PREFIX + canon)
    sig_b64 = base64.b64encode(sig).decode("ascii")
    return {
        "envelope_version": 1,
        "algorithm": "Ed25519",
        "key_id": key_id,
        "payload": payload_dict,
        "signature": sig_b64,
    }


def test_valid_perpetual_license(ephemeral_keypair, valid_payload_dict):
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    doc = make_signed_envelope(priv, "test-key-v1", valid_payload_dict)
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")

    envelope = verifier.parse_envelope_from_bytes(raw)
    res = verifier.validate_license(
        envelope,
        current_hardware_fingerprint="fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e",
        current_app_version="4.9.0",
        now_utc=datetime.datetime(2026, 11, 22, 12, 0, 0, tzinfo=datetime.timezone.utc),
    )

    assert res.is_valid is True
    assert res.status == ValidationStatus.VALID


def test_compact_token_and_trial_license(ephemeral_keypair, valid_payload_dict):
    """Verify compact base64-encoded token and trial license type."""
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    trial_payload = copy.deepcopy(valid_payload_dict)
    trial_payload["license_type"] = "trial"
    trial_payload["expires_at"] = "2026-12-01T00:00:00Z"

    doc = make_signed_envelope(priv, "test-key-v1", trial_payload)
    json_bytes = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    compact_token = base64.b64encode(json_bytes).decode("ascii")

    # Parse compact token
    env = verifier.parse_envelope_from_bytes(compact_token.encode("ascii"))
    assert env.payload.license_type == "trial"

    res = verifier.validate_license(
        env,
        current_hardware_fingerprint="fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e",
        current_app_version="4.9.2",
        now_utc=datetime.datetime(2026, 11, 25, 0, 0, 0, tzinfo=datetime.timezone.utc),
    )
    assert res.is_valid is True
    assert res.is_trial is True
    assert res.status == ValidationStatus.TRIAL
    assert res.days_remaining == 6


def test_grace_period_and_match_policy(ephemeral_keypair, valid_payload_dict):
    """Verify grace period expiration and standard/strict match policies."""
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    sub_payload = copy.deepcopy(valid_payload_dict)
    sub_payload["license_type"] = "subscription"
    sub_payload["expires_at"] = "2026-12-01T00:00:00Z"
    sub_payload["grace_period_days"] = 7
    sub_payload["grace_mode"] = "readonly"
    sub_payload["match_policy"] = "standard"

    doc = make_signed_envelope(priv, "test-key-v1", sub_payload)
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    env = verifier.parse_envelope_from_bytes(raw)

    primary_fp = "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"
    secondary_fp = "fp_v1:11112278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"

    # In grace period: now is 2 days after expires_at (within 7 days grace)
    now_grace = datetime.datetime(2026, 12, 3, 0, 0, 0, tzinfo=datetime.timezone.utc)
    res_grace = verifier.validate_license(env, primary_fp, "4.9.2", now_utc=now_grace)
    assert res_grace.is_valid is True
    assert res_grace.in_grace_period is True
    assert res_grace.grace_mode == "readonly"
    assert res_grace.status == ValidationStatus.GRACE_PERIOD

    # Past grace period: now is 10 days after expires_at (> 7 days grace)
    now_past = datetime.datetime(2026, 12, 11, 0, 0, 0, tzinfo=datetime.timezone.utc)
    res_past = verifier.validate_license(env, primary_fp, "4.9.2", now_utc=now_past)
    assert res_past.is_valid is False
    assert res_past.status == ValidationStatus.EXPIRED

    # Secondary tier match under standard policy
    tiers = {"tier1": "fp_v1:other", "tier2": primary_fp}
    res_tier2 = verifier.validate_license(
        env,
        current_hardware_fingerprint="fp_v1:other",
        current_app_version="4.9.2",
        now_utc=datetime.datetime(2026, 11, 25, 0, 0, 0, tzinfo=datetime.timezone.utc),
        available_hardware_tiers=tiers,
    )
    assert res_tier2.is_valid is True


def test_fail_closed_on_invalid_or_missing_keys():
    """Verify KeyRegistry rejects empty or malformed keys immediately."""
    reg = KeyRegistry({})
    verifier = LicenseVerifier(reg)

    with pytest.raises(CryptoVerificationError):
        reg.register_key_base64("bad-key", "")

    with pytest.raises(CryptoVerificationError):
        reg.register_key_base64("bad-key-len", base64.b64encode(b"short").decode("ascii"))

    assert res.license.payload.license_type == "perpetual"


def test_signature_tampering_detected(ephemeral_keypair, valid_payload_dict):
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    doc = make_signed_envelope(priv, "test-key-v1", valid_payload_dict)
    # Modify customer name without updating signature
    doc["payload"]["customer"]["name"] = "فروشگاه دستکاری‌شده"
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")

    envelope = verifier.parse_envelope_from_bytes(raw)
    res = verifier.validate_license(
        envelope,
        current_hardware_fingerprint="fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e",
    )

    assert res.is_valid is False
    assert res.status == ValidationStatus.INVALID_SIGNATURE


def test_wrong_public_key_or_unknown_key_id(ephemeral_keypair, valid_payload_dict):
    priv1, pub1, pub1_b64 = ephemeral_keypair
    # Another keypair
    priv2 = ed25519.Ed25519PrivateKey.generate()
    pub2_b64 = base64.b64encode(priv2.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")

    # Register only key 2, but doc is signed with key 1
    reg = KeyRegistry({"test-key-v1": pub2_b64})
    verifier = LicenseVerifier(reg)

    doc = make_signed_envelope(priv1, "test-key-v1", valid_payload_dict)
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    envelope = verifier.parse_envelope_from_bytes(raw)
    res = verifier.validate_license(envelope, current_hardware_fingerprint="fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e")

    assert res.is_valid is False
    assert res.status == ValidationStatus.INVALID_SIGNATURE


def test_key_rotation_support(ephemeral_keypair, valid_payload_dict):
    priv1, pub1, pub1_b64 = ephemeral_keypair
    priv2 = ed25519.Ed25519PrivateKey.generate()
    pub2_b64 = base64.b64encode(priv2.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")

    reg = KeyRegistry({
        "old-key-v1": pub1_b64,
        "new-key-v2": pub2_b64,
    })
    verifier = LicenseVerifier(reg)

    # Sign with new rotated key
    p2 = copy.deepcopy(valid_payload_dict)
    p2["key_id"] = "new-key-v2"
    doc2 = make_signed_envelope(priv2, "new-key-v2", p2)
    raw2 = json.dumps(doc2, ensure_ascii=False).encode("utf-8")

    envelope2 = verifier.parse_envelope_from_bytes(raw2)
    res2 = verifier.validate_license(envelope2, current_hardware_fingerprint="fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e")
    assert res2.is_valid is True


def test_reject_floats_in_payload(ephemeral_keypair, valid_payload_dict):
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    p = copy.deepcopy(valid_payload_dict)
    p["max_devices"] = 1.0  # float not allowed!

    # 1. canonicalize_payload rejects float
    with pytest.raises(ValueError, match="float"):
        canonicalize_payload(p)

    # 2. verifier.parse_envelope_from_bytes rejects float
    doc = {
        "envelope_version": 1,
        "algorithm": "Ed25519",
        "key_id": "test-key-v1",
        "signature": "xxx",
        "payload": p,
    }
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    with pytest.raises(LicensingError, match="float"):
        verifier.parse_envelope_from_bytes(raw)


def test_reject_duplicate_keys_in_json():
    verifier = LicenseVerifier()
    dup_json = b'{"envelope_version": 1, "envelope_version": 1, "algorithm": "Ed25519"}'
    with pytest.raises(LicensingError, match="تکراری"):
        verifier.parse_envelope_from_bytes(dup_json)


def test_reject_oversized_file():
    verifier = LicenseVerifier()
    oversized = b"a" * (MAX_LICENSE_FILE_BYTES + 10)
    with pytest.raises(LicensingError, match="بیش از حد مجاز"):
        verifier.parse_envelope_from_bytes(oversized)


def test_unauthorized_hardware_device(ephemeral_keypair, valid_payload_dict):
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    doc = make_signed_envelope(priv, "test-key-v1", valid_payload_dict)
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    envelope = verifier.parse_envelope_from_bytes(raw)

    res = verifier.validate_license(
        envelope,
        current_hardware_fingerprint="fp_v1:0000000000000000000000000000000000000000000000000000000000000000",
    )
    assert res.is_valid is False
    assert res.status == ValidationStatus.UNAUTHORIZED_DEVICE


def test_subscription_boundaries(ephemeral_keypair, valid_payload_dict):
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    sub_p = copy.deepcopy(valid_payload_dict)
    sub_p["license_type"] = "subscription"
    sub_p["not_before"] = "2026-11-01T00:00:00Z"
    sub_p["expires_at"] = "2026-12-01T00:00:00Z"

    doc = make_signed_envelope(priv, "test-key-v1", sub_p)
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    envelope = verifier.parse_envelope_from_bytes(raw)
    current_fp = sub_p["device_fingerprints"][0]

    # 1. Before not_before -> NOT_YET_VALID
    res_early = verifier.validate_license(
        envelope, current_fp,
        now_utc=datetime.datetime(2026, 10, 31, 23, 59, 59, tzinfo=datetime.timezone.utc),
    )
    assert res_early.status == ValidationStatus.NOT_YET_VALID

    # 2. Exactly at not_before -> VALID
    res_start = verifier.validate_license(
        envelope, current_fp,
        now_utc=datetime.datetime(2026, 11, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
    )
    assert res_start.status == ValidationStatus.VALID

    # 3. Inside window -> VALID
    res_mid = verifier.validate_license(
        envelope, current_fp,
        now_utc=datetime.datetime(2026, 11, 15, 12, 0, 0, tzinfo=datetime.timezone.utc),
    )
    assert res_mid.status == ValidationStatus.VALID

    # 4. Exactly at expires_at -> EXPIRED (boundary: < expires_at)
    res_at_exp = verifier.validate_license(
        envelope, current_fp,
        now_utc=datetime.datetime(2026, 12, 1, 0, 0, 0, tzinfo=datetime.timezone.utc),
    )
    assert res_at_exp.status == ValidationStatus.EXPIRED

    # 5. After expires_at -> EXPIRED
    res_after = verifier.validate_license(
        envelope, current_fp,
        now_utc=datetime.datetime(2026, 12, 1, 0, 0, 1, tzinfo=datetime.timezone.utc),
    )
    assert res_after.status == ValidationStatus.EXPIRED


def test_app_version_constraints(ephemeral_keypair, valid_payload_dict):
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    v_p = copy.deepcopy(valid_payload_dict)
    v_p["min_app_version"] = "4.9.0"
    v_p["max_app_version"] = "4.9.9"

    doc = make_signed_envelope(priv, "test-key-v1", v_p)
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    envelope = verifier.parse_envelope_from_bytes(raw)
    current_fp = v_p["device_fingerprints"][0]

    # App version 4.8.4 < 4.9.0 -> UNSUPPORTED_APP_VERSION
    res_low = verifier.validate_license(envelope, current_fp, current_app_version="4.8.4")
    assert res_low.status == ValidationStatus.UNSUPPORTED_APP_VERSION

    # App version 4.9.0 -> VALID
    res_exact = verifier.validate_license(envelope, current_fp, current_app_version="4.9.0")
    assert res_exact.status == ValidationStatus.VALID

    # App version 5.0.0 > 4.9.9 -> UNSUPPORTED_APP_VERSION
    res_high = verifier.validate_license(envelope, current_fp, current_app_version="5.0.0")
    assert res_high.status == ValidationStatus.UNSUPPORTED_APP_VERSION


def test_reproducible_canonical_test_vector():
    """Verify exact canonical serialization matching docs/licensing-protocol-v1.md."""
    # Test vector from section 3.2 of the spec
    raw_pub_b64 = "tZwFxuCGOF+WZqVF+PeKwpoIpOZovHLFRVSQxGaXJXA="
    expected_sha = "52bdf69ad45d565685bae87f75c03d4a5baa43a3acafe785499b16ee5618366a"
    sig_b64 = "kgrF5f89h9JBIHiQ55H5J+jZul3ZwC6NdeEDXtrlxMDWWlBr892vliqLsTxPD0q+RlEJaXsIQZUSjaevKSGjCA=="

    payload = {
        "customer": {
            "contact": "+989120000000",
            "name": "فروشگاه تستی نمونه",
            "organization": "مجموعه آزمایشی",
        },
        "device_fingerprints": [
            "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"
        ],
        "expires_at": None,
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
        "issued_at": "2026-11-22T00:00:00Z",
        "key_id": "daqiq-test-v1",
        "license_id": "LIC-2026-TEST01",
        "license_type": "perpetual",
        "max_app_version": None,
        "max_devices": 1,
        "min_app_version": "4.9.0",
        "not_before": "2026-11-22T00:00:00Z",
        "product_id": "daqiq.desktop",
    }

    canon_bytes = canonicalize_payload(payload)
    import hashlib
    data_to_verify = DOMAIN_PREFIX + canon_bytes
    actual_sha = hashlib.sha256(data_to_verify).hexdigest()
    assert actual_sha == expected_sha

    reg = KeyRegistry({"daqiq-test-v1": raw_pub_b64})
    verifier = LicenseVerifier(reg)

    doc = {
        "envelope_version": 1,
        "algorithm": "Ed25519",
        "key_id": "daqiq-test-v1",
        "payload": payload,
        "signature": sig_b64,
    }
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    env = verifier.parse_envelope_from_bytes(raw)
    res = verifier.validate_license(
        env,
        current_hardware_fingerprint="fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e",
        current_app_version="4.9.0",
        now_utc=datetime.datetime(2026, 11, 22, 1, 0, 0, tzinfo=datetime.timezone.utc),
    )
    assert res.is_valid is True
    assert res.status == ValidationStatus.VALID


def test_compact_token_and_trial_license(ephemeral_keypair, valid_payload_dict):
    """Verify compact base64-encoded token and trial license type."""
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    trial_payload = copy.deepcopy(valid_payload_dict)
    trial_payload["license_type"] = "trial"
    trial_payload["expires_at"] = "2026-12-01T00:00:00Z"

    doc = make_signed_envelope(priv, "test-key-v1", trial_payload)
    json_bytes = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    compact_token = base64.b64encode(json_bytes).decode("ascii")

    # Parse compact token
    env = verifier.parse_envelope_from_bytes(compact_token.encode("ascii"))
    assert env.payload.license_type == "trial"

    res = verifier.validate_license(
        env,
        current_hardware_fingerprint="fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e",
        current_app_version="4.9.2",
        now_utc=datetime.datetime(2026, 11, 25, 0, 0, 0, tzinfo=datetime.timezone.utc),
    )
    assert res.is_valid is True
    assert res.is_trial is True
    assert res.status == ValidationStatus.TRIAL
    assert res.days_remaining == 6


def test_grace_period_and_match_policy(ephemeral_keypair, valid_payload_dict):
    """Verify grace period expiration and standard/strict match policies."""
    priv, pub, pub_b64 = ephemeral_keypair
    reg = KeyRegistry({"test-key-v1": pub_b64})
    verifier = LicenseVerifier(reg)

    sub_payload = copy.deepcopy(valid_payload_dict)
    sub_payload["license_type"] = "subscription"
    sub_payload["expires_at"] = "2026-12-01T00:00:00Z"
    sub_payload["grace_period_days"] = 7
    sub_payload["grace_mode"] = "readonly"
    sub_payload["match_policy"] = "standard"

    doc = make_signed_envelope(priv, "test-key-v1", sub_payload)
    raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    env = verifier.parse_envelope_from_bytes(raw)

    primary_fp = "fp_v1:b8782278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"
    secondary_fp = "fp_v1:11112278c4c15107a8fd2a5d21718e3328c8baeac5d1a3f0664701ac2983e52e"

    # In grace period: now is 2 days after expires_at (within 7 days grace)
    now_grace = datetime.datetime(2026, 12, 3, 0, 0, 0, tzinfo=datetime.timezone.utc)
    res_grace = verifier.validate_license(env, primary_fp, "4.9.2", now_utc=now_grace)
    assert res_grace.is_valid is True
    assert res_grace.in_grace_period is True
    assert res_grace.grace_mode == "readonly"
    assert res_grace.status == ValidationStatus.GRACE_PERIOD

    # Past grace period: now is 10 days after expires_at (> 7 days grace)
    now_past = datetime.datetime(2026, 12, 11, 0, 0, 0, tzinfo=datetime.timezone.utc)
    res_past = verifier.validate_license(env, primary_fp, "4.9.2", now_utc=now_past)
    assert res_past.is_valid is False
    assert res_past.status == ValidationStatus.EXPIRED

    # Secondary tier match under standard policy
    tiers = {"tier1": "fp_v1:other", "tier2": primary_fp}
    res_tier2 = verifier.validate_license(
        env,
        current_hardware_fingerprint="fp_v1:other",
        current_app_version="4.9.2",
        now_utc=datetime.datetime(2026, 11, 25, 0, 0, 0, tzinfo=datetime.timezone.utc),
        available_hardware_tiers=tiers,
    )
    assert res_tier2.is_valid is True


def test_fail_closed_on_invalid_or_missing_keys():
    """Verify KeyRegistry rejects empty or malformed keys immediately."""
    reg = KeyRegistry({})
    verifier = LicenseVerifier(reg)

    with pytest.raises(CryptoVerificationError):
        reg.register_key_base64("bad-key", "")

    with pytest.raises(CryptoVerificationError):
        reg.register_key_base64("bad-key-len", base64.b64encode(b"short").decode("ascii"))

