"""Registo de schemas de payload por (event_type, schema_version), carregado de contracts/jsonschema."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from we_core.errors import ValidationFailed


def schemas_dir() -> Path:
    here = Path(__file__).resolve()
    packaged = here.parents[1] / "_schemas"
    if packaged.is_dir():
        return packaged
    return here.parents[3] / "contracts" / "jsonschema"


class SchemaRegistry:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or schemas_dir()
        self._validators: dict[tuple[str, int], Draft202012Validator] = {}
        self.documents: dict[tuple[str, int], dict[str, Any]] = {}
        for f in sorted((self.directory / "events").glob("*.v*.schema.json")):
            name = f.name.removesuffix(".schema.json")
            event_type, _, ver = name.rpartition(".v")
            doc = json.loads(f.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(doc)
            key = (event_type, int(ver))
            self.documents[key] = doc
            self._validators[key] = Draft202012Validator(doc, format_checker=FormatChecker())
        envelope = json.loads((self.directory / "event-envelope.v1.schema.json").read_text(encoding="utf-8"))
        self.envelope = Draft202012Validator(envelope, format_checker=FormatChecker())

    def latest_version(self, event_type: str) -> int:
        versions = [v for (t, v) in self._validators if t == event_type]
        if not versions:
            raise ValidationFailed(f"Tipo de evento não registado: {event_type}", code="WE-EVT-SCHEMA")
        return max(versions)

    def event_types(self) -> list[str]:
        return sorted({t for (t, _) in self._validators})

    def versions(self, event_type: str) -> list[int]:
        return sorted(v for (t, v) in self._validators if t == event_type)

    def validate(self, event_type: str, version: int, payload: dict[str, Any]) -> None:
        validator = self._validators.get((event_type, version))
        if validator is None:
            raise ValidationFailed(f"Schema inexistente: {event_type} v{version}", code="WE-EVT-SCHEMA")
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if errors:
            msgs = "; ".join(f"{'/'.join(map(str, e.path)) or '(raiz)'}: {e.message}" for e in errors[:5])
            raise ValidationFailed(
                f"Payload inválido para {event_type} v{version}: {msgs}", code="WE-EVT-SCHEMA"
            )


@lru_cache
def get_registry() -> SchemaRegistry:
    return SchemaRegistry()
