# Incidente: suspeita de acesso entre tenants

1. **Conter.** Revogar tokens do ator ou cliente suspeito no IdP; desativar o ator (`iam.actors.status`).
2. **Preservar.** Exportar `audit.audit_log` dos tenants envolvidos (por `correlation_id`) e os logs da API
   (JSON, com `tenant_id` e `correlation_id`).
3. **Verificar controlos.** `pytest tests/integration -k "rls or tenant"`; confirmar `relforcerowsecurity` em
   todas as tabelas de domínio:
   `SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE relkind='r' AND NOT relrowsecurity AND nspname NOT IN ('pg_catalog','information_schema','public','legacy','obligation','platform');`
   (deve devolver 0 linhas; os catálogos globais são exceção conhecida).
4. **Avaliar.** Âmbito, dados e titulares afetados. Avaliação jurídica humana da obrigação de notificação à CNPD
   e aos titulares (RGPD arts. 33.º e 34.º; prazo de 72 h para a autoridade). **Requer validação jurídica.**
5. **Corrigir e documentar.** ADR ou DECISION com a causa raiz e um teste de regressão.
