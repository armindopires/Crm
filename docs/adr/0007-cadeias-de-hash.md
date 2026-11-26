# ADR-0007 — Cadeias de hash por tenant para eventos e auditoria

- **Estado:** aprovado · **Evidência:** PROPOSTA_TECNICA

## Decisão
- `event_hash = SHA-256(previous_hash | JSON canónico(campos do envelope))`, com génese `0…0`. O mesmo vale para
  `audit.audit_log.record_hash`.
- A cadeia é **por tenant** e está serializada por `platform.chain_heads … FOR UPDATE`. A cabeça é verificada
  contra o último registo, o que deteta truncagem.
- A verificação (`we verify-chains`, `GET /v1/events/verify`, `GET /v1/audit/verify`) deteta alteração de
  conteúdo, quebra de ligação, lacunas e cabeça inconsistente (há testes de adulteração com privilégios de DBA).
- JSON canónico: chaves ordenadas, UTF-8, decimais como string e datas `…Z` com microssegundos.

## Limites conhecidos
- **Serialização das escritas por tenant**: suficiente para a carga de um gabinete, mas é um gargalo potencial.
  Evolução possível: cadeias por stream com âncora periódica (Merkle root) por tenant.
- Um atacante com controlo total da base pode recalcular a cadeia inteira. Mitigação planeada: **ancoragem
  externa** periódica da cabeça (por exemplo em armazenamento WORM ou num serviço de timestamping qualificado,
  eIDAS). Fica PENDENTE.
