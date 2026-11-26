"""Runner de migrações SQL versionadas e com checksum (sem ORM; ver ADR-0005).

- cada ficheiro corre numa transação própria;
- uma migração já aplicada cujo checksum mude é um erro (migrações são imutáveis);
- no fim, ativa LOGIN dos roles aplicacionais com as passwords do ambiente.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg
from psycopg import sql

from we_core.common import sha256_hex
from we_core.config import Settings

log = logging.getLogger("we.migrate")


def migrations_dir() -> Path:
    here = Path(__file__).resolve()
    packaged = here.parent / "_migrations"
    if packaged.is_dir():
        return packaged
    return here.parents[2] / "db" / "migrations"


def run_migrations(settings: Settings, directory: Path | None = None) -> list[str]:
    directory = directory or migrations_dir()
    files = sorted(p for p in directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    applied_now: list[str] = []
    with psycopg.connect(settings.dsn("admin"), autocommit=True) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS public.we_schema_migrations (
                 version text PRIMARY KEY, checksum text NOT NULL,
                 applied_at timestamptz NOT NULL DEFAULT now())"""
        )
        conn.execute("SELECT pg_advisory_lock(727001)")
        try:
            applied = {
                r[0]: r[1] for r in conn.execute("SELECT version, checksum FROM public.we_schema_migrations")
            }
            for f in files:
                checksum = sha256_hex(f.read_bytes())
                if f.name in applied:
                    if applied[f.name] != checksum:
                        raise RuntimeError(
                            f"Migração {f.name} foi alterada após aplicação (checksum diferente)."
                        )
                    continue
                log.info("a aplicar %s", f.name)
                with conn.transaction():
                    conn.execute(f.read_bytes())
                    conn.execute(
                        "INSERT INTO public.we_schema_migrations (version, checksum) VALUES (%s, %s)",
                        (f.name, checksum),
                    )
                applied_now.append(f.name)
            _ensure_login_roles(conn, settings)
        finally:
            conn.execute("SELECT pg_advisory_unlock(727001)")
    return applied_now


def _ensure_login_roles(conn: psycopg.Connection[tuple[object, ...]], settings: Settings) -> None:
    for role, secret in (("we_app", settings.pg_app_password), ("we_worker", settings.pg_worker_password)):
        pw = secret.get_secret_value()
        if not pw:
            raise RuntimeError(f"Password para {role} não definida (WE_PG_{role[3:].upper()}_PASSWORD).")
        conn.execute(
            sql.SQL("ALTER ROLE {} LOGIN PASSWORD {} CONNECTION LIMIT 50").format(
                sql.Identifier(role), sql.Literal(pw)
            )
        )


def migration_status(settings: Settings) -> list[dict[str, str]]:
    files = sorted(p.name for p in migrations_dir().glob("[0-9][0-9][0-9][0-9]_*.sql"))
    with psycopg.connect(settings.dsn("admin"), autocommit=True) as conn:
        exists = conn.execute("SELECT to_regclass('public.we_schema_migrations') IS NOT NULL").fetchone()
        applied = (
            {r[0] for r in conn.execute("SELECT version FROM public.we_schema_migrations")}
            if exists and exists[0]
            else set()
        )
    return [{"version": f, "state": "applied" if f in applied else "pending"} for f in files]
