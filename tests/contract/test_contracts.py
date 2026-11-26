"""Testes de contrato: OpenAPI/AsyncAPI atualizados e coerentes; eventos emitidos existem no registo."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import export_openapi  # noqa: E402
from we_core.events.registry import SchemaRegistry  # noqa: E402


def test_openapi_committed_is_up_to_date():
    committed = json.loads((ROOT / "contracts/openapi/we-api.v1.json").read_text())
    assert committed == json.loads(json.dumps(export_openapi.openapi_doc())), (
        "OpenAPI desatualizado: corra `python scripts/dev.py contracts`"
    )


def test_asyncapi_committed_is_up_to_date_and_complete():
    committed = json.loads((ROOT / "contracts/asyncapi/we-events.v1.json").read_text())
    assert committed == json.loads(json.dumps(export_openapi.asyncapi_doc()))
    reg = SchemaRegistry(ROOT / "contracts/jsonschema")
    assert len(committed["components"]["messages"]) == len(reg.documents)


def test_every_emitted_event_type_is_registered():
    reg = SchemaRegistry(ROOT / "contracts/jsonschema")
    known = set(reg.event_types())
    emitted: set[str] = set()
    for f in (ROOT / "src/we_core").rglob("*.py"):
        emitted |= set(re.findall(r'event_type="([a-z_]+\.[a-z_.]+)"', f.read_text()))
    emitted |= {"governance.decision_approved", "governance.decision_rejected"}  # f-string em governance
    assert emitted, "nenhum evento encontrado"
    assert emitted <= known, f"eventos sem schema: {sorted(emitted - known)}"


def test_error_responses_use_problem_json_codes():
    doc = export_openapi.openapi_doc()
    assert doc["info"]["version"] and doc["openapi"].startswith("3.")
    paths = doc["paths"]
    for required in (
        "/health/live",
        "/health/ready",
        "/v1/tenants",
        "/v1/entities",
        "/v1/context-frames",
        "/v1/events",
        "/v1/admin/projections/{name}/replay",
        "/v1/evidence",
        "/v1/evidence/{evidence_id}/verify",
        "/v1/decisions/{decision_id}/review",
        "/v1/signals",
        "/v1/signals/{signal_id}/promote",
        "/v1/audit/verify",
        "/v1/sources",
        "/v1/import-batches",
    ):
        assert required in paths, required
