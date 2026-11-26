"""Emissor OIDC **apenas para desenvolvimento** (sem passwords).

Gera um par de chaves RS256 local (.local/, ignorado pelo Git) e emite tokens assinados para sujeitos
sintéticos. Recusa funcionar quando WE_ENV não é development/test. Em produção usa-se um IdP real
(ver ADR-0006); a API valida sempre a assinatura, issuer, audience e expiração.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from we_core.common import uuid7
from we_core.config import Settings

KID = "we-dev-key-1"


def _guard(settings: Settings) -> None:
    if settings.env not in ("development", "test"):
        raise RuntimeError("O emissor de tokens de desenvolvimento está proibido fora de development/test.")


def ensure_dev_keys(local_dir: Path) -> tuple[Path, Path]:
    local_dir.mkdir(parents=True, exist_ok=True)
    priv_path, jwks_path = local_dir / "dev-signing-key.pem", local_dir / "dev-jwks.json"
    if not priv_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        priv_path.chmod(0o600)
    loaded = serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
    if not isinstance(loaded, rsa.RSAPrivateKey):
        raise RuntimeError("Chave de desenvolvimento não é RSA.")
    jwk = json.loads(RSAAlgorithm.to_jwk(loaded.public_key()))
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    jwks_path.write_text(json.dumps({"keys": [jwk]}, indent=2))
    return priv_path, jwks_path


def mint_token(
    settings: Settings,
    subject: str,
    *,
    tenant_id: str | None = None,
    platform_roles: list[str] | None = None,
    ttl_seconds: int = 3600,
    key_path: Path = Path(".local/dev-signing-key.pem"),
    extra: dict[str, Any] | None = None,
) -> str:
    _guard(settings)
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": subject,
        "iat": now,
        "nbf": now - 5,
        "exp": now + ttl_seconds,
        "jti": str(uuid7()),
        "amr": ["dev"],
    }
    if tenant_id:
        claims[settings.oidc_tenant_claim] = tenant_id
    if platform_roles:
        claims[settings.oidc_platform_role_claim] = platform_roles
    if extra:
        claims.update(extra)
    return jwt.encode(claims, key_path.read_bytes(), algorithm="RS256", headers={"kid": KID})
