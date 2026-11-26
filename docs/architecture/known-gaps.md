# Lacunas conhecidas e riscos

| ID | Lacuna | Severidade | Mitigação atual | Próximo passo |
|---|---|---|---|---|
| G01 | **Fontes do pacote ausentes** (ADR-0014) | Alta | Constraints do prompt; manifesto `NAO_INDICADO` | Fornecer ficheiros; correr `we source-manifest`; rever modelo canónico |
| G02 | IdP de produção não decidido | Alta | Emissor de dev bloqueado fora de dev | Decisão do utilizador; fluxo OIDC + PKCE na web |
| G03 | Object Lock/WORM indisponível no SeaweedFS | Média | Chaves por conteúdo, sem sobrescrita, verificação | S3/MinIO com Object Lock em produção |
| G04 | Ancoragem externa das cadeias de hash | Média | Cadeias por tenant + verificação | Ancorar a cabeça periodicamente (WORM ou carimbo temporal qualificado) |
| G05 | Motor de workflow (Temporal) não ligado | Média | Schema versionado (`workflow.*`) | Adaptador Temporal + worker de workflows |
| G06 | Projeções Neo4j/OpenSearch/ClickHouse não implementadas | Baixa | Perfis compose prontos | Consumidores dedicados com replay |
| G07 | Embedding não semântico | Baixa | Explícito no nome do modelo | ADR com fornecedor e residência de dados |
| G08 | Consola web com token de serviço local | Média (dev) | Só leitura + verificação; ficheiro fora do Git | OIDC com sessão segura |
| G09 | Serialização de escritas por tenant (cadeia) | Baixa agora | Adequado ao volume de um gabinete | Cadeias por stream + âncora Merkle |
| G10 | Rate limiting em fail-open sem Redis | Média | Readiness `degraded` | Reavaliar antes de exposição pública |
| G11 | Retenção, anonimização e crypto-shredding só documentados | Média | Eventos e auditoria sem PII | Implementar classes de retenção e eliminação governada |
| G12 | Regras fiscais e contributivas reais | — (excluído) | Catálogo com `VALIDACAO_EXTERNA_PENDENTE` e CHECK | Validar em fonte oficial (DRE, AT, SS) antes de ativar |
| G13 | CI não executado neste ambiente | Média | Todos os passos corridos localmente | Primeiro push com runners GitHub |
| G14 | `libzstd1` HIGH na imagem base (correção ainda não publicada no repositório Debian usado) | Baixa | Gate de CI só bloqueia CRITICAL | Atualizar a imagem base |
| G15 | Verificação de dependências entre contextos não automatizada | Baixa | Revisão | `import-linter` com contratos por contexto |
| G16 | Backup e restore só testado manualmente | Média | Runbook com comandos | Job agendado + teste de restore no CI |
