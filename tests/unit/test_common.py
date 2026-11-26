from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from we_core.common import GENESIS_HASH, canonical_json, chain_hash, iso_utc, pseudonymize, uuid7


def test_uuid7_version_variant_and_order():
    ids = [uuid7() for _ in range(200)]
    assert all(u.version == 7 and u.variant == "specified in RFC 4122" for u in ids)
    assert len(set(ids)) == 200
    # ordenação temporal ao nível do milissegundo
    assert ids[0].int >> 80 <= ids[-1].int >> 80


def test_canonical_json_is_order_independent_and_exact():
    a = {"b": 1, "a": [Decimal("1.10"), "ç"], "c": {"z": None, "y": True}}
    b = {"c": {"y": True, "z": None}, "a": [Decimal("1.10"), "ç"], "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert '"1.10"' in canonical_json(a)  # decimal exato, nunca float


def test_iso_utc_normalizes_timezone_and_rejects_naive():
    lisbon_summer = timezone(timedelta(hours=1))
    assert iso_utc(datetime(2026, 7, 1, 13, 0, tzinfo=lisbon_summer)) == "2026-07-01T12:00:00.000000Z"
    with pytest.raises(ValueError):
        iso_utc(datetime(2026, 1, 1))
    assert iso_utc(datetime(2026, 1, 1, tzinfo=UTC)).endswith("Z")


def test_chain_hash_changes_with_any_field():
    rec = {"x": 1, "y": "a"}
    h = chain_hash(GENESIS_HASH, rec)
    assert h != chain_hash(GENESIS_HASH, {**rec, "y": "b"})
    assert h != chain_hash("1" * 64, rec)
    assert len(h) == 64


def test_pseudonymize_is_stable_and_keyed():
    assert pseudonymize("k1", "user@x") == pseudonymize("k1", "user@x")
    assert pseudonymize("k1", "user@x") != pseudonymize("k2", "user@x")
    assert "user" not in pseudonymize("k1", "user@x")
