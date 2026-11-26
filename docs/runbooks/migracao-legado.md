# Migração e integração com legados — regras operacionais

**Nenhuma ligação a bases reais nem migração total sem autorização específica e por escrito.**

1. Autorização: uma DECISION aprovada por humano que identifique a origem, a finalidade, a base legal, o
   responsável e o ambiente.
2. Cópia controlada dos dados **legitimamente detidos**, num ambiente isolado. Hash SHA-256 à receção e registo
   em `legacy.raw_snapshots`.
3. **Utilitários de desencriptação DBISAM**: só com autorização explícita, sobre a cópia, em ambiente isolado
   sem rede, com cadeia de custódia (EVIDENCE com custody events). Nunca em postos de trabalho.
4. **Credenciais legadas** (Firebird em texto simples, password histórica predefinida): registar apenas que
   existem e onde (localização lógica). Nunca copiar valores. Mapear para `__DISCARD__` (`CHECK` em
   `legacy.mapping_rules`). Recomendar a rotação na origem.
5. Tipos, precisão, escala, nulabilidade e codificação confirmados **na fonte autoritativa** antes de qualquer
   transformação (`mapping_rules.source_type_confirmed`).
6. FKs inferidas (CrmContab) só se ativam com zero órfãos (reconciliação `orphans`) ou uma decisão documentada.
7. Filosoft/SNC32: apenas read models (saldos, balancetes, SAF-T validado). O ledger certificado não é substituído.
8. SAF-T: estrutura e versão do XSD validadas em fonte oficial da AT antes de qualquer uso
   (`VALIDACAO_EXTERNA_PENDENTE`).
