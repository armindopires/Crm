#!/usr/bin/env python3
"""Executor de tarefas de desenvolvimento da WE (multiplataforma: Linux, macOS, Windows).

Uso: python scripts/dev.py <comando>
  bootstrap         gera .env e chaves locais, instala dependências (uv, pnpm)
  start [perfis]    arranca perfis docker compose (por omissão: core)
  start-full        arranca todos os perfis
  stop              pára os contentores (mantém volumes)
  migrate           aplica migrações PostgreSQL
  seed              cria dados sintéticos de demonstração
  lint | typecheck  ruff / mypy (+ tsc no web)
  test-unit | test-integration | test-contract
  contracts         regenera OpenAPI e SDK TypeScript
  demo              demonstração vertical E2E
  verify            lint + typecheck + todos os testes + contratos + demo
  reset             APAGA volumes locais (pede confirmação explícita)
"""

from __future__ import annotations

import contextlib
import functools
import json
import operator
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "-f",
    str(ROOT / "infra/compose/compose.yaml"),
    "--env-file",
    str(ROOT / ".env"),
]
ALL_PROFILES = ["core", "ui", "identity", "orchestration", "knowledge", "observability", "analytics"]


def _profiles(profiles: list[str]) -> list[str]:
    return [arg for p in profiles for arg in ("--profile", p)]


def run(cmd: list[str], check: bool = True, env: dict[str, str] | None = None) -> int:
    print("$", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=ROOT, env={**os.environ, **(env or {})})
    if check and rc != 0:
        sys.exit(rc)
    return rc


def uv(*args: str) -> list[str]:
    return ["uv", "run", "--frozen", *args]


def bootstrap() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        lines = []
        for line in (ROOT / ".env.example").read_text().splitlines():
            if "__GERADO_PELO_BOOTSTRAP__" in line:
                k = line.split("=", 1)[0]
                line = f"{k}={secrets.token_urlsafe(32)}"
            lines.append(line)
        env_path.write_text("\n".join(lines) + "\n")
        with contextlib.suppress(OSError):
            env_path.chmod(0o600)
        print("· .env gerado com segredos aleatórios locais")
    env = dict(
        line.split("=", 1) for line in env_path.read_text().splitlines() if line and not line.startswith("#")
    )
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    s3 = local / "seaweed-s3.json"
    identity = {
        "name": "we",
        "actions": ["Admin", "Read", "Write", "List", "Tagging"],
        "credentials": [{"accessKey": env["WE_S3_ACCESS_KEY"], "secretKey": env["WE_S3_SECRET_KEY"]}],
    }
    s3.write_text(json.dumps({"identities": [identity]}))
    run(["uv", "sync", "--frozen"])
    run(
        uv(
            "python",
            "-c",
            "from pathlib import Path; from we_core.identity.devissuer import ensure_dev_keys; "
            "ensure_dev_keys(Path('.local'))",
        )
    )
    if shutil.which("pnpm"):
        run(["pnpm", "install", "--frozen-lockfile"], check=False)
    print("· bootstrap concluído")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "bootstrap":
        bootstrap()
    elif cmd == "start":
        profiles = args or ["core"]
        run(
            [
                *COMPOSE,
                *functools.reduce(operator.iadd, (["--profile", p] for p in profiles), []),
                "up",
                "-d",
                "--build",
                "--wait",
            ]
        )
    elif cmd == "start-full":
        run(
            [
                *COMPOSE,
                *functools.reduce(operator.iadd, (["--profile", p] for p in ALL_PROFILES), []),
                "up",
                "-d",
                "--build",
            ]
        )
    elif cmd == "stop":
        run(
            [*COMPOSE, *functools.reduce(operator.iadd, (["--profile", p] for p in ALL_PROFILES), []), "down"]
        )
    elif cmd == "migrate":
        run(uv("we", "migrate"))
    elif cmd == "seed":
        run(uv("we", "seed-demo"))
    elif cmd == "lint":
        run(uv("ruff", "check", "src", "tests", "scripts"))
        run(uv("ruff", "format", "--check", "src", "tests", "scripts"))
    elif cmd == "typecheck":
        run(uv("mypy"))
        run(["pnpm", "-r", "typecheck"])
    elif cmd == "test-unit":
        run(uv("pytest", "tests/unit", "-q"))
    elif cmd == "test-integration":
        run(uv("pytest", "tests/integration", "-q", "-m", "integration"))
    elif cmd == "test-contract":
        run(uv("pytest", "tests/contract", "-q"))
        run(["node", "scripts/validate-asyncapi.mjs"])
    elif cmd == "contracts":
        run(uv("python", "scripts/export_openapi.py"))
        run(["pnpm", "--filter", "@we/sdk", "generate"])
    elif cmd == "demo":
        run(uv("python", "scripts/demo_vertical.py", *args))
    elif cmd == "verify":
        for c in ("lint", "typecheck", "test-unit", "test-contract", "test-integration", "demo"):
            run([sys.executable, __file__, c])
        run(["pnpm", "--filter", "@we/web", "build"])
        print("· verify: todos os gates passaram")
    elif cmd == "reset":
        answer = input("Isto APAGA todos os volumes locais da WE. Escreva 'APAGAR-LOCAL' para confirmar: ")
        if answer.strip() != "APAGAR-LOCAL":
            print("Cancelado.")
            return
        run(
            [
                *COMPOSE,
                *functools.reduce(operator.iadd, (["--profile", p] for p in ALL_PROFILES), []),
                "down",
                "-v",
            ]
        )
    else:
        print(f"Comando desconhecido: {cmd}\n{__doc__}")
        sys.exit(2)


if __name__ == "__main__":
    main()
