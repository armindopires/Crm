"""CLI `we`: migrate, worker, dev-token, dev-idp, verify-chains, verify-evidence, replay, seed-demo,
source-manifest, import-knowledge."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from uuid import UUID

from we_core.config import get_settings


def _tenant_ctx(tenant: str):  # type: ignore[no-untyped-def]
    from we_core.context import OpContext, Principal

    return OpContext(
        principal=Principal(
            subject="cli:operator",
            actor_id=None,
            tenant_id=UUID(tenant),
            actor_type="system",
            roles=frozenset({"auditor"}),
            clearance="secret",
        )
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="we", description="Ferramentas operacionais da Wolf Enterprise")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="aplicar migrações")
    sub.add_parser("migration-status", help="estado das migrações")
    sub.add_parser("worker", help="arrancar worker (outbox + projeções)")
    sub.add_parser("seed-demo", help="criar tenant sintético e importar depósito sintético (idempotente)")
    t = sub.add_parser("dev-token", help="emitir token de desenvolvimento (só dev/test)")
    t.add_argument("--sub", required=True)
    t.add_argument("--tenant")
    t.add_argument("--platform-admin", action="store_true")
    t.add_argument("--ttl", type=int, default=3600)
    i = sub.add_parser("dev-idp", help="servir JWKS/discovery de desenvolvimento")
    i.add_argument("--host", default="127.0.0.1")
    i.add_argument("--port", type=int, default=8090)
    v = sub.add_parser("verify-chains", help="verificar cadeias de eventos e auditoria de um tenant")
    v.add_argument("--tenant", required=True)
    e = sub.add_parser("verify-evidence", help="verificar SHA-256 de todas as evidências de um tenant")
    e.add_argument("--tenant", required=True)
    r = sub.add_parser("replay", help="reconstruir projeção entity_summary de um tenant")
    r.add_argument("--tenant", required=True)
    m = sub.add_parser("source-manifest", help="gerar manifesto SHA-256 das fontes de referência")
    m.add_argument("--root", default="reference/legacy-sources")
    m.add_argument("--out", default="reference/manifests/sources.manifest.json")
    k = sub.add_parser("import-knowledge", help="importar depósito JSON validado por JSON Schema")
    k.add_argument("--tenant", required=True)
    k.add_argument("--actor-subject", required=True)
    k.add_argument("--deposit", required=True)
    k.add_argument("--schema", required=True)
    k.add_argument("--source-system", default="CRMCONTAB")
    args = parser.parse_args(argv)
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s %(message)s")
    s = get_settings()

    if args.cmd == "migrate":
        from we_core.migrate import run_migrations

        print(json.dumps({"applied": run_migrations(s)}))
    elif args.cmd == "migration-status":
        from we_core.migrate import migration_status

        print(json.dumps(migration_status(s), indent=2))
    elif args.cmd == "worker":
        from we_core.worker.main import main as worker_main

        worker_main()
    elif args.cmd == "seed-demo":
        from we_core.seed import seed_demo

        print(json.dumps(seed_demo(s), indent=2, default=str))
    elif args.cmd == "dev-token":
        from we_core.identity.devissuer import mint_token

        print(
            mint_token(
                s,
                args.sub,
                tenant_id=args.tenant,
                platform_roles=["platform_admin"] if args.platform_admin else None,
                ttl_seconds=args.ttl,
            )
        )
    elif args.cmd == "dev-idp":
        from we_core.identity.devidp import serve

        serve(s, args.host, args.port)
    elif args.cmd in ("verify-chains", "verify-evidence", "replay"):
        import dataclasses

        from psycopg.rows import dict_row

        from we_core.db import Database
        from we_core.integrity import verify_audit, verify_events

        db = Database(s.dsn("app"), 1, 2)
        db.open()
        tenant = UUID(args.tenant)
        ok = True
        with db.tenant_tx(tenant) as conn:
            conn.row_factory = dict_row
            if args.cmd == "verify-chains":
                reps = [verify_events(conn, tenant), verify_audit(conn, tenant)]
                ok = all(r.valid for r in reps)
                print(json.dumps([dataclasses.asdict(r) for r in reps], indent=2, default=str))
            elif args.cmd == "replay":
                from we_core.events.projections import replay

                out = replay(conn, tenant)
                ok = out["deterministic"]
                print(json.dumps(out, indent=2, default=str))
            else:
                import hashlib

                from we_core.evidence.storage import S3Storage

                store = S3Storage(s)
                results = []
                for row in conn.execute("SELECT evidence_id, sha256, storage_key FROM evidence.evidence"):
                    data = store.get(row["storage_key"])
                    observed = hashlib.sha256(data).hexdigest() if data is not None else None
                    results.append(
                        {"evidence_id": str(row["evidence_id"]), "valid": observed == row["sha256"]}
                    )
                ok = all(r["valid"] for r in results)
                print(json.dumps(results, indent=2))
        db.close()
        sys.exit(0 if ok else 1)
    elif args.cmd == "source-manifest":
        from we_core.knowledge.manifest import build_manifest

        manifest = build_manifest(Path(args.root))
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(manifest["summary"], indent=2, ensure_ascii=False))
    elif args.cmd == "import-knowledge":
        from we_core.knowledge.importer import import_deposit_cli

        print(
            json.dumps(
                import_deposit_cli(
                    s,
                    UUID(args.tenant),
                    args.actor_subject,
                    Path(args.deposit),
                    Path(args.schema),
                    args.source_system,
                ),
                indent=2,
                default=str,
            )
        )


if __name__ == "__main__":
    main()
