import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from we_core.config import Settings
from we_core.errors import Unauthenticated
from we_core.identity.devissuer import ensure_dev_keys, mint_token
from we_core.identity.oidc import TokenVerifier


@pytest.fixture
def keys(tmp_path: Path):
    priv, jwks = ensure_dev_keys(tmp_path)
    s = Settings(env="test", oidc_jwks_path=str(jwks), oidc_jwks_url=None)
    return s, priv


def test_valid_token_roundtrip(keys):
    s, priv = keys
    tok = mint_token(s, "u@x.invalid", tenant_id="00000000-0000-4000-8000-000000000001", key_path=priv)
    claims = TokenVerifier(s).verify(tok)
    assert claims["sub"] == "u@x.invalid" and claims["we_tenant_id"].endswith("1")


def test_rejects_wrong_audience_expired_alg_none_and_foreign_key(keys):
    s, priv = keys
    v = TokenVerifier(s)
    with pytest.raises(Unauthenticated):
        v.verify(mint_token(s, "u", key_path=priv, extra={"aud": "outra-api"}))
    with pytest.raises(Unauthenticated):
        v.verify(mint_token(s, "u", key_path=priv, ttl_seconds=-120))
    none_tok = jwt.encode(
        {
            "sub": "u",
            "iss": s.oidc_issuer,
            "aud": s.oidc_audience,
            "exp": time.time() + 60,
            "iat": time.time(),
        },
        key=None,
        algorithm="none",
    )
    with pytest.raises(Unauthenticated):
        v.verify(none_tok)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {
            "sub": "u",
            "iss": s.oidc_issuer,
            "aud": s.oidc_audience,
            "exp": int(time.time()) + 60,
            "iat": int(time.time()),
        },
        other,
        algorithm="RS256",
        headers={"kid": "we-dev-key-1"},
    )
    with pytest.raises(Unauthenticated):
        v.verify(forged)


def test_dev_issuer_refuses_production(keys):
    _, priv = keys
    s = Settings(env="development")
    object.__setattr__(s, "env", "production")
    with pytest.raises(RuntimeError):
        mint_token(s, "u", key_path=priv)


def test_production_requires_idp_jwks_url():
    with pytest.raises(ValueError):
        Settings(env="production", oidc_jwks_path="x.json", oidc_jwks_url=None)
