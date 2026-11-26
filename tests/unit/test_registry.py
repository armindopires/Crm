import itertools

import pytest

from we_core.errors import ValidationFailed
from we_core.events.registry import SchemaRegistry


@pytest.fixture(scope="module")
def reg():
    return SchemaRegistry()


def test_all_schemas_load_and_are_closed(reg):
    assert len(reg.documents) >= 25
    for (t, v), doc in reg.documents.items():
        assert doc["additionalProperties"] is False, f"{t} v{v} tem de recusar campos extra (anti-PII)"


def test_payload_with_extra_field_is_rejected(reg):
    with pytest.raises(ValidationFailed):
        reg.validate(
            "kernel.entity_updated",
            1,
            {
                "changed_fields": [],
                "new_version": 2,
                "status": "active",
                "classification": "internal",
                "nif": "999999990",
            },
        )


def test_schema_evolution_is_backward_compatible(reg):
    """Cada versão nova aceita payloads válidos da versão anterior (só acrescenta campos opcionais)."""
    for t in reg.event_types():
        vs = reg.versions(t)
        for older, newer in itertools.pairwise(vs):
            o, n = reg.documents[(t, older)], reg.documents[(t, newer)]
            assert set(n["required"]) <= set(o["required"]), f"{t}: v{newer} exige campos novos"
            assert set(o["properties"]) <= set(n["properties"]), f"{t}: v{newer} remove campos"
    v1 = {
        "entity_type": "client",
        "classification": "internal",
        "organization_id": None,
        "attribute_keys": [],
    }
    reg.validate("kernel.entity_created", 1, v1)
    reg.validate("kernel.entity_created", 2, v1)
