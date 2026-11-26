# ADR-0013 — Payloads de eventos fechados e sem PII

- **Estado:** aprovado · **Evidência:** DECISAO_APROVADA (§12: proibição de segredos e PII desnecessária)

## Decisão
- Todos os schemas de payload têm `additionalProperties: false` (há teste), pelo que um campo pessoal não se
  infiltra no Event Store nem no NATS.
- Os eventos registam **factos de alteração**: tipo, classificação, nomes de campos alterados, versões e hashes.
  Não registam valores pessoais (por exemplo `changed_fields: ["attributes.regime_iva"]`).
- A auditoria guarda pseudónimos HMAC do sujeito e da origem (`WE_AUDIT_PSEUDONYM_KEY`).
- Evolução de schemas: uma versão nova só pode **acrescentar campos opcionais** (há teste). Escreve-se sempre a
  última versão e lêem-se todas.

## Consequência
Eliminar dados pessoais (RGPD art. 17.º) atua sobre as tabelas de estado sem quebrar as cadeias de hash.
Os dados imutáveis contêm apenas referências.
