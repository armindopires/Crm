# ADR-0011 — Knowledge Repository em pgvector; embedding provisório não semântico

- **Estado:** aprovado (provisório quanto ao modelo de embedding) · **Evidência:** PROPOSTA_TECNICA

## Decisão
- Fontes com SHA-256, autoridade (1–8, segundo a hierarquia do prompt), estado de evidência, jurisdição e
  vigência (`knowledge.sources`, append-only).
- Os depósitos JSON só são importados depois de validados pelo respetivo JSON Schema. Se a validação falhar, o
  lote fica `failed`, os erros vão para a quarentena e nada é registado como fonte.
- Os nós ficam em `imported_unvalidated`: **importar não é aceitar como verdade canónica**.
- Exclusão por política: chaves de segredo são **descartadas**; chaves pessoais ficam `[EXCLUIDO:pii]` no corpo
  e fora de embeddings e índices.
- Embedding `we-featurehash-256-v1` (feature hashing, determinístico, **não semântico**). Serve como placeholder
  para provar o pipeline, o índice HNSW e o isolamento. A substituição por um modelo semântico exige ADR
  (fornecedor, residência de dados, custo).
- OpenSearch e Neo4j entram como projeções opcionais (perfil `knowledge`). Os adaptadores estão PENDENTES.
