"""Validação de tokens OIDC (RS256/ES256): assinatura via JWKS, issuer, audience, exp/nbf.

O tenant vem exclusivamente da claim assinada; nunca de um header livre.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from jwt import PyJWK, PyJWKClient

from we_core.config import Settings
from we_core.errors import Unauthenticated

ALLOWED_ALGS = ["RS256", "ES256"]


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: PyJWKClient | None = None
        self._static: dict[str, PyJWK] = {}
        if settings.oidc_jwks_url:
            self._client = PyJWKClient(settings.oidc_jwks_url, cache_keys=True, lifespan=300)
        elif settings.oidc_jwks_path:
            path = Path(settings.oidc_jwks_path)
            if path.exists():
                for k in json.loads(path.read_text())["keys"]:
                    self._static[k["kid"]] = PyJWK(k)

    def _key(self, token: str) -> Any:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise Unauthenticated("Token malformado.", code="WE-AUTH-002") from exc
        if header.get("alg") not in ALLOWED_ALGS:
            raise Unauthenticated("Algoritmo de assinatura não permitido.", code="WE-AUTH-002")
        if self._client:
            return self._client.get_signing_key_from_jwt(token).key
        kid = header.get("kid")
        if not kid or kid not in self._static:
            raise Unauthenticated("Chave de assinatura desconhecida.", code="WE-AUTH-002")
        return self._static[kid].key

    def verify(self, token: str) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=self._key(token),
                algorithms=ALLOWED_ALGS,
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
                leeway=10,
            )
        except jwt.ExpiredSignatureError as exc:
            raise Unauthenticated("Token expirado.", code="WE-AUTH-004") from exc
        except jwt.PyJWTError as exc:
            raise Unauthenticated("Token inválido.", code="WE-AUTH-002") from exc
        return claims


@lru_cache
def get_verifier(settings: Settings) -> TokenVerifier:
    return TokenVerifier(settings)
