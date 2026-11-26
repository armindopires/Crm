"""Fixtures partilhadas. Testes de integração exigem o perfil core (ver docs/runbooks/arranque-paragem.md)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


_load_env()


@pytest.fixture(scope="session")
def settings():  # type: ignore[no-untyped-def]
    from we_core.config import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def db(settings) -> Iterator[object]:  # type: ignore[no-untyped-def]
    from we_core.db import Database

    d = Database(settings.dsn("app"), 1, 4)
    try:
        d.open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"BLOCKED: PostgreSQL indisponível ({exc}); arranque o perfil core")
    yield d
    d.close()


@pytest.fixture(scope="session")
def admin_dsn(settings) -> str:  # type: ignore[no-untyped-def]
    return settings.dsn("admin")


@pytest.fixture
def tenant_factory(db):  # type: ignore[no-untyped-def]
    """Cria tenants sintéticos via serviço de plataforma e devolve (tenant, ctx_admin)."""
    import secrets

    from we_core.config import get_settings
    from we_core.context import OpContext, Principal
    from we_core.identity.principal import resolve_principal
    from we_core.platform.service import create_tenant

    def make(prefix: str = "t"):  # type: ignore[no-untyped-def]
        run = secrets.token_hex(4)
        sub = f"admin-{run}@{prefix}.example.invalid"
        pctx = OpContext(
            principal=Principal(
                subject="platform@test.invalid",
                actor_id=None,
                tenant_id=None,
                actor_type="human",
                platform_roles=frozenset({"platform_admin"}),
            )
        )
        t = create_tenant(
            db,
            pctx,
            slug=f"{prefix}-{run}",
            display_name=f"Tenant teste {run}",
            organization_name="Org fictícia",
            admin_subject=sub,
            admin_display_name="Admin teste",
            is_synthetic=True,
        )
        s = get_settings()
        principal = resolve_principal(db, s, {"sub": sub, s.oidc_tenant_claim: str(t["tenant_id"])})
        return t, OpContext(principal=principal)

    return make
