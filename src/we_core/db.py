"""Acesso a PostgreSQL com contexto de tenant transacional (seguro face a connection pools).

O contexto (`we.tenant_id`) é definido com `set_config(..., is_local => true)` dentro de uma transação
explícita: termina com COMMIT/ROLLBACK e nunca transita para o próximo utilizador da ligação.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

Conn = Connection[dict[str, Any]]


class Database:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10) -> None:
        self.pool: ConnectionPool[Conn] = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=False,
        )

    def open(self) -> None:
        self.pool.open(wait=True, timeout=30)

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def tenant_tx(self, tenant_id: UUID | None, *, platform_scope: bool = False) -> Iterator[Conn]:
        """Transação com contexto de tenant. Sem tenant (e sem platform scope) a RLS nega tudo."""
        with self.pool.connection() as conn, conn.transaction():
            conn.execute(
                "SELECT set_config('we.tenant_id', %s, true), set_config('we.platform_scope', %s, true)",
                (str(tenant_id) if tenant_id else "", "on" if platform_scope else ""),
            )
            yield conn

    def ping(self) -> bool:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT 1 AS ok").fetchone()
            return bool(row and row["ok"] == 1)
