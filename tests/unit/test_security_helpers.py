import io
import zipfile

import pytest

from we_core.ai.gateway import redact as ai_redact
from we_core.errors import ValidationFailed
from we_core.evidence.service import safe_filename, sniff
from we_core.knowledge.importer import embed, sanitize
from we_core.knowledge.manifest import build_manifest
from we_core.observability import redact


def test_log_redaction_removes_secrets_and_pii():
    line = "authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.sig password=hunter2 a@b.pt postgresql://u:p@h/db"
    out = redact(line)
    for leak in ("hunter2", "a@b.pt", "u:p@h", "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0"):
        assert leak not in out


def test_ai_redaction():
    assert "123456789" not in ai_redact("NIF 123456789 email x@y.pt")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\x\\..\\a b.pdf", "a_b.pdf"),
        ("ação.txt", "acao.txt"),
        ("", "evidencia"),
    ],
)
def test_safe_filename_blocks_traversal(raw, expected):
    assert safe_filename(raw) == expected


def test_sniff_rejects_mime_mismatch_and_disallowed():
    with pytest.raises(ValidationFailed):
        sniff("application/pdf", b"not a pdf")
    with pytest.raises(ValidationFailed):
        sniff("application/x-msdownload", b"MZ")
    with pytest.raises(ValidationFailed):
        sniff("text/plain", b"\xff\xfe\x00")
    sniff("application/pdf", b"%PDF-1.7 ...")


def test_sanitize_drops_secrets_and_excludes_pii():
    excluded: list[str] = []
    out = sanitize(
        {"nome": "Tabela X", "Password": "x", "nif": "999999990", "sub": {"api_key": "k"}}, "", excluded
    )
    assert "Password" not in out and "api_key" not in out["sub"]
    assert out["nif"] == "[EXCLUIDO:pii]"
    assert sorted(excluded) == ["pii:/nif", "secret:/Password", "secret:/sub/api_key"]


def test_embed_is_deterministic_and_normalized():
    a, b = embed("tabela clientes"), embed("tabela clientes")
    assert a == b and len(a) == 256
    assert abs(sum(v * v for v in a) - 1) < 1e-3


def test_manifest_flags_missing_sources_and_blocks_zip_slip(tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("00_LEIA-ME.md", "# leia-me sintético")
        zf.writestr("../evil.txt", "x")
        zf.writestr("tools/dbisam_decrypt.exe", "MZ")
    (root / "WE_Pacote_Equipa_2026-06-18.zip").write_bytes(buf.getvalue())
    m = build_manifest(root, extracted_root=tmp_path / "ex")
    assert m["summary"]["expected_missing"] == ["Nova_Geracao_Manuais_Wolf_Enterprise.txt"]
    zip_entry = next(e for e in m["entries"] if e["kind"] == "zip")
    assert any(x["status"] == "REJEITADO_ZIP_SLIP" for x in zip_entry["members"])
    assert not (tmp_path / "evil.txt").exists()
    tool = next(e for e in m["entries"] if e["logical_path"].endswith("dbisam_decrypt.exe"))
    assert tool["requires_explicit_authorization"] and tool["classification"] == "restricted"
