# ADR-0004 — Armazenamento de evidências S3-compatible; SeaweedFS em desenvolvimento

- **Estado:** aprovado (provisório quanto ao produto de desenvolvimento) · **Evidência:** FACTO_CONFIRMADO (indisponibilidade) + PROPOSTA_TECNICA

## Contexto
O prompt indica MinIO para desenvolvimento. Neste ambiente, a imagem `minio/minio` foi recusada pelo Docker Hub
(`pull access denied`) e `quay.io` está bloqueado pelo proxy. Facto verificado em 2026-11-26.

## Decisão
- O domínio usa apenas a porta `ObjectStorage` (`we_core/evidence/storage.py`) com a API S3 (boto3, path-style,
  SigV4).
- Em desenvolvimento usa-se **SeaweedFS 3.97** com gateway S3 e credenciais geradas pelo bootstrap.
- Chaves endereçadas por conteúdo: `tenants/<tenant>/sha256/<aa>/<sha256>`. Nunca há sobrescrita.
- O SHA-256 é calculado no servidor. A verificação relê o objeto e recalcula.

## Pendente
- **Object Lock / WORM**: o SeaweedFS não oferece object lock equivalente. Em produção, exigir S3 com Object Lock
  (modo compliance) ou MinIO com retenção. Depende da escolha do fornecedor (NAO_INDICADO).
- O versionamento do bucket é pedido no arranque, mas é suportado apenas parcialmente pelo SeaweedFS.

## Reversibilidade
Alta. Basta mudar `WE_S3_ENDPOINT` e as credenciais.
