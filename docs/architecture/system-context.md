# Contexto do sistema (C4 nível 1)

A WE é um **Sistema Operacional Cognitivo Organizacional Contextual**. Não é um ERP, CRM, BPM ou DMS. Organiza
entidades, relações, contexto, eventos, evidências e decisões para reduzir a entropia organizacional de um
gabinete de contabilidade e dos seus clientes.

```mermaid
flowchart LR
  U[Colaboradores do gabinete<br/>operador · aprovador · auditor] -->|HTTPS + OIDC| WE[(Wolf Enterprise)]
  IA[Agentes de IA<br/>ator ai_agent] -->|propõe, nunca aprova| WE
  IDP[IdP OIDC<br/>NAO_INDICADO em produção] -->|JWT assinado| WE
  WE -->|read models apenas| FIL[Filosoft / SNC32<br/>system of record contabilístico]
  LEG[Legados: CrmContab · SIGEP32<br/>CentralGest · Gimo32 · SAF-T] -->|staging controlado, sem ligação real nesta fase| WE
  WE -.->|bloqueado nesta fase| EXT[AT · Segurança Social · bancos · email]
```

| Fronteira | Estado nesta entrega |
|---|---|
| Utilizadores humanos | API e consola web mínima (só leitura, mais a verificação de evidências) |
| IdP | Emissor de desenvolvimento local. **IdP produtivo NAO_INDICADO** (ADR-0006) |
| Filosoft | Mantém-se system of record (ADR-0012). Integração de read models PENDENTE |
| Legados | Registo de sistemas, staging, importador de conhecimento provado com dados sintéticos |
| Entidades oficiais (AT/SS) | **Sem integração**: submissões, faturação certificada e XAdES excluídas desta missão |
