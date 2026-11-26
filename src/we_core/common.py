"""Utilitários transversais: UUIDv7, tempo UTC, JSON canónico e hashing."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

GENESIS_HASH = "0" * 64
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted", "secret")


def uuid7() -> uuid.UUID:
    """UUID versão 7 (RFC 9562): ordenável por tempo, adequado a índices B-tree."""
    ts_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ts_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= ((rand >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= rand & ((1 << 62) - 1)
    return uuid.UUID(int=value)


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso_utc(dt: datetime) -> str:
    """Formato temporal estável para hashing: UTC, microssegundos, sufixo Z."""
    if dt.tzinfo is None:
        raise ValueError("datetime sem timezone não é permitido")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _default(o: Any) -> Any:
    if isinstance(o, datetime):
        return iso_utc(o)
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(f"tipo não serializável: {type(o)!r}")


def canonical_json(obj: Any) -> str:
    """JSON canónico (chaves ordenadas, sem espaços, UTF-8) — base de todas as cadeias de hash."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def chain_hash(previous_hash: str, record: dict[str, Any]) -> str:
    return sha256_hex(previous_hash + "|" + canonical_json(record))


def pseudonymize(key: str, value: str | None) -> str:
    """Pseudónimo HMAC-SHA256 estável; permite correlação sem guardar o valor em claro."""
    if not value:
        return "anon"
    return "hm:" + hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def to_jsonable(obj: Any) -> Any:
    return json.loads(canonical_json(obj))
