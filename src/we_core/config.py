"""Configuração da WE. Segredos chegam apenas por variáveis de ambiente (dev) ou referências de cofre (prod)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WE_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "staging", "production"] = "development"
    service_name: str = "we-api"

    # PostgreSQL — fonte de verdade
    pg_host: str = "localhost"
    pg_port: int = 55432
    pg_db: str = "we"
    pg_admin_user: str = "we_admin"
    pg_admin_password: SecretStr = SecretStr("")
    pg_app_password: SecretStr = SecretStr("")
    pg_worker_password: SecretStr = SecretStr("")
    pg_pool_min: int = 1
    pg_pool_max: int = 10

    # Mensageria (EventBus)
    nats_url: str = "nats://localhost:4222"
    nats_stream: str = "WE_EVENTS"

    # Redis — rate limiting / locks efémeros
    redis_url: str = "redis://localhost:6379/0"
    redis_password: SecretStr = SecretStr("")
    rate_limit_per_minute: int = 600

    # Armazenamento S3-compatible (evidências)
    s3_endpoint: str = "http://localhost:8333"
    s3_region: str = "eu-west-1"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_bucket: str = "we-evidence"
    evidence_max_bytes: int = 20 * 1024 * 1024

    # Identidade OIDC — tokens assinados; tenant vem das claims, nunca de header livre
    oidc_issuer: str = "https://dev-idp.we.local"
    oidc_audience: str = "we-api"
    oidc_jwks_url: str | None = None
    oidc_jwks_path: str | None = ".local/dev-jwks.json"
    oidc_tenant_claim: str = "we_tenant_id"
    oidc_platform_role_claim: str = "we_platform_roles"

    # Auditoria — chave de pseudonimização (HMAC)
    audit_pseudonym_key: SecretStr = SecretStr("")

    # Observabilidade
    otel_exporter_otlp_endpoint: str | None = Field(default=None)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.env in ("staging", "production"):
            if self.oidc_jwks_path and not self.oidc_jwks_url:
                raise ValueError("Em staging/produção o JWKS tem de vir de um IdP (WE_OIDC_JWKS_URL).")
            if len(self.audit_pseudonym_key.get_secret_value()) < 32:
                raise ValueError("WE_AUDIT_PSEUDONYM_KEY tem de ter pelo menos 32 caracteres.")
        return self

    def dsn(self, role: Literal["admin", "app", "worker"]) -> str:
        user, pw = {
            "admin": (self.pg_admin_user, self.pg_admin_password),
            "app": ("we_app", self.pg_app_password),
            "worker": ("we_worker", self.pg_worker_password),
        }[role]
        from urllib.parse import quote

        return (
            f"postgresql://{quote(user)}:{quote(pw.get_secret_value())}@{self.pg_host}:{self.pg_port}/{self.pg_db}"
            f"?application_name={self.service_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
