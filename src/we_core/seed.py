"""Seeds sintéticos (idempotentes). Nunca usa NIF/NISS/IBAN/nomes/emails reais: domínios .invalid, dados fictícios."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from we_core.config import Settings
from we_core.context import OpContext, Principal
from we_core.db import Database
from we_core.identity.principal import resolve_principal
from we_core.knowledge.importer import import_deposit
from we_core.platform.service import create_tenant

SEED_SLUG = "demo-seed"
ADMIN_SUB = "admin@demo-seed.example.invalid"
SEEDS = Path(__file__).resolve().parents[2] / "db" / "seeds" / "knowledge"


def seed_demo(settings: Settings) -> dict[str, Any]:
    db = Database(settings.dsn("app"), 1, 2)
    db.open()
    try:
        with db.tenant_tx(None, platform_scope=True) as conn:
            row = conn.execute(
                "SELECT tenant_id FROM platform.tenants WHERE slug = %s", (SEED_SLUG,)
            ).fetchone()
        if row:
            tenant_id = row["tenant_id"]
            created = False
        else:
            pctx = OpContext(
                principal=Principal(
                    subject="seed@we.invalid",
                    actor_id=None,
                    tenant_id=None,
                    actor_type="system",
                    platform_roles=frozenset({"platform_admin"}),
                )
            )
            tenant_id = create_tenant(db, pctx, slug=SEED_SLUG, display_name="Gabinete Fictício (seed)",
                                      organization_name="Organização Fictícia de Demonstração",
                                      admin_subject=ADMIN_SUB, admin_display_name="Administração Fictícia",
                                      is_synthetic=True)["tenant_id"]  # fmt: skip
            created = True
        principal = resolve_principal(
            db, settings, {"sub": ADMIN_SUB, settings.oidc_tenant_claim: str(tenant_id)}
        )
        ctx = OpContext(principal=principal)
        deposit = SEEDS / "crmcontab-metadados-sintetico.json"
        schema = SEEDS / "crmcontab-metadados-sintetico.schema.json"
        with db.tenant_tx(tenant_id) as conn:
            result = import_deposit(
                conn,
                ctx,
                deposit_bytes=deposit.read_bytes(),
                schema_bytes=schema.read_bytes(),
                logical_path="db/seeds/knowledge/" + deposit.name,
                schema_path="db/seeds/knowledge/" + schema.name,
                source_system_code="CRMCONTAB",
            )
        return {"tenant_id": str(tenant_id), "tenant_created": created, "admin_subject": ADMIN_SUB,
                "knowledge_import": result}  # fmt: skip
    finally:
        db.close()
