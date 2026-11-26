#!/usr/bin/env python3
"""Exporta o contrato OpenAPI da API e gera o AsyncAPI a partir do registo de schemas de eventos.

Ambos são versionados no Git; o teste de contrato falha se estiverem desatualizados.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def openapi_doc() -> dict:
    from we_core.api.app import create_app
    from we_core.config import Settings

    return create_app(Settings(env="test")).openapi()


def asyncapi_doc() -> dict:
    from we_core.events.registry import SchemaRegistry

    reg = SchemaRegistry(ROOT / "contracts" / "jsonschema")
    channels, operations, messages = {}, {}, {}
    for (t, v), doc in sorted(reg.documents.items()):
        mid = f"{t.replace('.', '_')}_v{v}"
        messages[mid] = {
            "name": t, "title": doc["title"], "summary": doc["description"], "contentType": "application/json",
            "headers": {"type": "object", "properties": {"Nats-Msg-Id": {"type": "string", "description":
                        "event_id (deduplicação JetStream)"}}},
            "payload": {"allOf": [{"$ref": "../jsonschema/event-envelope.v1.schema.json"},
                                  {"type": "object", "properties": {
                                      "event_type": {"const": t}, "schema_version": {"const": v},
                                      "payload": {"$ref": f"../jsonschema/events/{t}.v{v}.schema.json"}}}]},
        }  # fmt: skip
    for t in reg.event_types():
        cid = t.replace(".", "_")
        channels[cid] = {
            "address": "we.{tenant_id}." + t,
            "parameters": {"tenant_id": {"description": "UUID do tenant (ordenação garantida por agregado)"}},
            "messages": {
                f"{cid}_v{v}": {"$ref": f"#/components/messages/{cid}_v{v}"} for v in reg.versions(t)
            },
        }
        operations[f"publish_{cid}"] = {
            "action": "send", "channel": {"$ref": f"#/channels/{cid}"},
            "summary": "Publicado pelo worker a partir da transactional outbox (at-least-once).",
        }  # fmt: skip
    return {
        "asyncapi": "3.0.0",
        "info": {"title": "Wolf Enterprise — Eventos de domínio", "version": "1.0.0",
                 "description": "Catálogo de eventos da WE. Fonte de verdade: PostgreSQL (Event Store). "
                                "Transporte: NATS JetStream (stream WE_EVENTS, subjects we.<tenant>.<event_type>). "
                                "Entrega at-least-once; consumidores idempotentes por event_id."},
        "defaultContentType": "application/json",
        "servers": {"dev": {"host": "localhost:4222", "protocol": "nats", "description": "NATS local (perfil core)"}},
        "channels": channels, "operations": operations, "components": {"messages": messages},
    }  # fmt: skip


def write_all() -> None:
    (ROOT / "contracts/openapi/we-api.v1.json").write_text(
        json.dumps(openapi_doc(), indent=2, ensure_ascii=False) + "\n"
    )
    (ROOT / "contracts/asyncapi/we-events.v1.json").write_text(
        json.dumps(asyncapi_doc(), indent=2, ensure_ascii=False) + "\n"
    )


if __name__ == "__main__":
    write_all()
    print("contratos exportados", file=sys.stderr)
