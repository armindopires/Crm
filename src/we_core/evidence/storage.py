"""Porta de armazenamento de objetos (S3-compatible) e adaptadores.

Chaves endereçadas por conteúdo: tenants/<tenant>/sha256/<hash>. Nunca há sobrescrita: se o objeto já
existe com o mesmo hash, reutiliza-se; se existisse com conteúdo diferente, seria adulteração.
"""

from __future__ import annotations

import contextlib
import io
from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from we_core.config import Settings


class ObjectStorage(Protocol):
    bucket: str

    def ensure_bucket(self) -> None: ...
    def exists(self, key: str) -> bool: ...
    def put(self, key: str, data: bytes, media_type: str, sha256: str) -> str | None: ...
    def get(self, key: str) -> bytes | None: ...
    def ping(self) -> bool: ...


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value() or None,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value() or None,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          retries={"max_attempts": 3}, connect_timeout=3, read_timeout=10),
        )  # fmt: skip

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)
        # versionamento quando suportado pelo backend (MinIO/S3 sim; SeaweedFS parcial)
        with contextlib.suppress(ClientError):
            self.client.put_bucket_versioning(
                Bucket=self.bucket, VersioningConfiguration={"Status": "Enabled"}
            )

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def put(self, key: str, data: bytes, media_type: str, sha256: str) -> str | None:
        resp = self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=media_type,
            Metadata={"we-sha256": sha256},
        )  # fmt: skip
        return resp.get("VersionId")

    def get(self, key: str) -> bytes | None:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return None
        return bytes(obj["Body"].read())

    def ping(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:  # noqa: BLE001 - qualquer falha = dependência indisponível
            return False


class MemoryStorage:
    """Adaptador em memória para testes unitários."""

    def __init__(self) -> None:
        self.bucket = "memory"
        self.objects: dict[str, bytes] = {}

    def ensure_bucket(self) -> None:
        return None

    def exists(self, key: str) -> bool:
        return key in self.objects

    def put(self, key: str, data: bytes, media_type: str, sha256: str) -> str | None:
        self.objects[key] = io.BytesIO(data).getvalue()
        return None

    def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def ping(self) -> bool:
        return True
