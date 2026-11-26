"""Manifesto de fontes de referência: SHA-256, tamanho, tipo, autoridade e alertas de sensibilidade.

As fontes originais nunca são alteradas. Um ZIP é extraído (com proteção zip-slip e limites) para
reference/extracted/<sha256-curto>/, área ignorada pelo Git, e cada membro entra no manifesto.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from we_core.common import iso_utc, utcnow

EXPECTED_SOURCES = ["Nova_Geracao_Manuais_Wolf_Enterprise.txt", "WE_Pacote_Equipa_2026-06-18.zip"]
KIND_BY_EXT = {".json": "json_deposit", ".xlsx": "xlsx", ".docx": "docx", ".sql": "sql", ".md": "markdown",
               ".txt": "txt", ".zip": "zip"}  # fmt: skip
SENSITIVE_HINTS = ("decrypt", "desencript", "decifr", "password", "passwd", "senha", "credential", ".fdb",
                   ".gdb", ".dat", ".key", ".pem", ".pfx", ".p12", "dbisam")  # fmt: skip
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 20_000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def authority_rank(rel: str) -> tuple[int, str]:
    """Hierarquia de autoridade do prompt mestre (1 = decisão explícita do utilizador)."""
    low = rel.lower()
    if "nova_geracao_manuais" in low:
        return 2, "Documento constitucional e manuais estruturantes"
    if "/adr" in low or low.startswith("adr"):
        return 3, "ADR"
    if "base_conhecimento_master" in low or "decisao_senior_migracao" in low:
        return 4, "Base de conhecimento MASTER / Decisão sénior"
    if low.endswith(".schema.json") or (low.endswith(".json") and "schema" in low):
        return 5, "JSON Schema de depósito"
    if low.endswith(".json"):
        return 5, "Depósito JSON (validar contra schema)"
    if any(
        k in low for k in ("mapeamento", "mapping", "manual", "relatorio", "relatório", "er_", "diagrama")
    ):
        return 6, "Mapeamentos, manuais e relatórios"
    if low.endswith((".sql", ".py", ".js", ".ts", ".ps1", ".bat", ".pas")):
        return 7, "DDL, ETL e código de protótipo"
    return 8, "Inferência / não classificado"


def classify(rel: str) -> dict[str, Any]:
    low = rel.lower()
    flags = [h for h in SENSITIVE_HINTS if h in low]
    return {
        "classification": "restricted" if flags else "confidential",
        "sensitivity_flags": flags,
        "requires_explicit_authorization": bool(flags),
    }


def _safe_extract(zip_path: Path, dest: Path) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError("ZIP com demasiados membros")
        for info in infos:
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts:
                members.append({"path": info.filename, "status": "REJEITADO_ZIP_SLIP"})
                continue
            if info.is_dir():
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                members.append(
                    {"path": info.filename, "status": "REJEITADO_TAMANHO", "size_bytes": info.file_size}
                )
                continue
            target = dest / Path(*name.parts)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(1 << 20):
                        out.write(chunk)
            members.append({"path": info.filename, "status": "EXTRAIDO", "size_bytes": info.file_size})
    return members


def build_manifest(root: Path, extracted_root: Path = Path("reference/extracted")) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    found: dict[str, str] = {}
    files = (
        sorted(p for p in root.rglob("*") if p.is_file() and p.name != "README.md") if root.exists() else []
    )
    for p in files:
        rel = p.relative_to(root).as_posix()
        digest = sha256_file(p)
        rank, rank_label = authority_rank(rel)
        entry: dict[str, Any] = {
            "logical_path": rel, "sha256": digest, "size_bytes": p.stat().st_size,
            "kind": KIND_BY_EXT.get(p.suffix.lower(), "other"), "authority_rank": rank,
            "authority_label": rank_label, "evidence_status": "INFERIDO_A_VALIDAR", "origin": "original",
            **classify(rel),
        }  # fmt: skip
        for exp in EXPECTED_SOURCES:
            if p.name.lower() == exp.lower():
                found[exp] = rel
        if p.suffix.lower() == ".zip":
            dest = extracted_root / digest[:16]
            entry["extracted_to"] = dest.as_posix()
            entry["members"] = _safe_extract(p, dest)
            for member in entry["members"]:
                if member["status"] != "EXTRAIDO":
                    continue
                mp = dest / member["path"]
                mrank, mlabel = authority_rank(member["path"])
                entries.append({
                    "logical_path": f"{rel}!/{member['path']}", "sha256": sha256_file(mp),
                    "size_bytes": member["size_bytes"], "kind": KIND_BY_EXT.get(mp.suffix.lower(), "other"),
                    "authority_rank": mrank, "authority_label": mlabel, "evidence_status": "INFERIDO_A_VALIDAR",
                    "origin": "zip_member", **classify(member["path"]),
                })  # fmt: skip
        entries.append(entry)
    expected = [
        {"name": n, "status": "ENCONTRADO" if n in found else "NAO_INDICADO", "logical_path": found.get(n),
         "impact": None if n in found else "Fonte ausente: factos dependentes ficam NAO_INDICADO até ser fornecida."}
        for n in EXPECTED_SOURCES
    ]  # fmt: skip
    return {
        "manifest_version": 1,
        "generated_at": iso_utc(utcnow()),
        "root": root.as_posix(),
        "expected_sources": expected,
        "entries": sorted(entries, key=lambda e: e["logical_path"]),
        "summary": {
            "files": len(entries),
            "expected_found": sum(1 for e in expected if e["status"] == "ENCONTRADO"),
            "expected_missing": [e["name"] for e in expected if e["status"] != "ENCONTRADO"],
            "requires_authorization": sum(1 for e in entries if e.get("requires_explicit_authorization")),
        },
    }
