# ADR-0012 — Filosoft como system of record na Fase 1; integração legada por anti-corruption layer

- **Estado:** aprovado · **Evidência:** DECISAO_APROVADA (prompt §5, §15)

## Decisão
- A Filosoft/SNC32 continua como system of record contabilístico. A WE recebe read models (saldos, balancetes,
  estados, SAF-T validado) com chave `(entidade, exercício, período, fonte)`.
- `legacy.*`: registo de sistemas de origem, lotes, snapshots raw imutáveis, regras de mapeamento versionadas
  (`CHECK`: dados `secret` só podem ir para `__DISCARD__`), `legacy_id_map`, reconciliações e quarentena.
- Não há ligação a bases reais. Os parâmetros de lote não aceitam credenciais (só referências de cofre).
- FKs inferidas do CrmContab (218 tabelas, praticamente sem FK) só se ativam com zero órfãos ou decisão
  documentada.
- O DDL da pasta transversal do pacote corresponde ao SIGEP32 e **não** é o kernel WE. Não é executado.
- A construção de um ledger nativo fica num roadmap separado, dependente de paridade funcional, validação
  OCC/ROC e certificação.
