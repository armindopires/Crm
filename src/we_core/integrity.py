"""Verificação das cadeias de integridade (eventos e auditoria). Deteta alteração, remoção e reordenação."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from we_core.audit.log import audit_hash_record
from we_core.common import GENESIS_HASH, chain_hash
from we_core.db import Conn
from we_core.events.store import hash_record


@dataclass
class ChainReport:
    chain: str
    tenant_id: str
    records: int = 0
    valid: bool = True
    head_seq: int | None = None
    problems: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, seq: int | None, kind: str, detail: str) -> None:
        self.valid = False
        if len(self.problems) < 50:
            self.problems.append({"chain_seq": seq, "kind": kind, "detail": detail})


def _verify(conn: Conn, tenant_id: UUID, chain: str, sql: str, hasher: Any, hash_col: str) -> ChainReport:
    report = ChainReport(chain=chain, tenant_id=str(tenant_id))
    expected_prev, expected_seq = GENESIS_HASH, 1
    with conn.cursor() as cur:
        cur.execute(sql, (tenant_id,))
        for row in cur:
            report.records += 1
            seq = int(row["chain_seq"])
            if seq != expected_seq:
                report.fail(seq, "gap", f"esperado chain_seq {expected_seq}, encontrado {seq}")
            if row["previous_hash"] != expected_prev:
                report.fail(seq, "link", "previous_hash não corresponde ao registo anterior")
            recomputed = chain_hash(row["previous_hash"], hasher(row))
            if recomputed != row[hash_col]:
                report.fail(seq, "content", "conteúdo alterado: hash recalculado difere do gravado")
            expected_prev, expected_seq = row[hash_col], seq + 1
    head = conn.execute(
        "SELECT last_seq, last_hash FROM platform.chain_heads WHERE tenant_id = %s AND chain_name = %s",
        (tenant_id, chain),
    ).fetchone()
    if head:
        report.head_seq = int(head["last_seq"])
        if int(head["last_seq"]) != expected_seq - 1 or head["last_hash"] != expected_prev:
            report.fail(None, "head", "cabeça da cadeia não corresponde ao último registo (truncagem?)")
    elif report.records:
        report.fail(None, "head", "cabeça da cadeia em falta")
    return report


def verify_events(conn: Conn, tenant_id: UUID) -> ChainReport:
    return _verify(
        conn, tenant_id, "events",
        "SELECT * FROM event_store.events WHERE tenant_id = %s ORDER BY chain_seq",
        hash_record, "event_hash",
    )  # fmt: skip


def verify_audit(conn: Conn, tenant_id: UUID) -> ChainReport:
    return _verify(
        conn, tenant_id, "audit",
        "SELECT * FROM audit.audit_log WHERE tenant_id = %s ORDER BY chain_seq",
        audit_hash_record, "record_hash",
    )  # fmt: skip
