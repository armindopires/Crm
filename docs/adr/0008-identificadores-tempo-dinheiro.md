# ADR-0008 — UUIDv7, tempo em UTC, valores monetários exatos e identificadores como texto

- **Estado:** aprovado · **Evidência:** DECISAO_APROVADA (§10) + PROPOSTA_TECNICA (variante UUID)

## Decisão
- **UUIDv7** (RFC 9562), gerado na aplicação (`we_core.common.uuid7`): ordenável no tempo e bom para índices.
  O PostgreSQL 16 não o gera nativamente.
- Tempo em `timestamptz`, armazenado em UTC e apresentado em `Europe/Lisbon` (interface com `Intl` `pt-PT`).
- Dinheiro em `numeric(18,2)` + `char(3)` ISO 4217. Na API e nos eventos, valores decimais circulam como texto.
- NIF, NISS, IBAN, códigos postais e contas são **texto**, em `kernel.entity_identifiers` (classificação
  `restricted`). Nunca são numéricos.
