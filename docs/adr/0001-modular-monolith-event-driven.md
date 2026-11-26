# ADR-0001 — Modular monolith event-driven em vez de 12 microserviços

- **Estado:** aprovado (decisão explícita do prompt mestre, §6)
- **Data:** 2026-11-26
- **Evidência:** DECISAO_APROVADA

## Contexto
A arquitetura lógica da WE tem 12 camadas (Foundation … Network and Connectors). São fronteiras conceptuais,
não unidades de deployment. Ainda não existe carga, equipa nem SLO que justifiquem a separação física.

## Decisão
Um único pacote Python `we_core` com **bounded contexts** em subpacotes (`platform`, `identity`, `kernel`,
`events`, `evidence`, `audit`, `governance`, `ai`, `intelligence`, `workflow`, `obligations`, `knowledge`,
`communications`, `connectors`, `legacy`). Há dois processos: `api` (FastAPI) e `worker` (outbox e projeções).
Os contextos comunicam por funções de serviço com contratos explícitos e por eventos versionados. Não há SQL
cruzado entre contextos, exceto em leituras agregadas de estado (`/v1/system/status`).

## Consequências
- Transações ACID locais garantem estado + evento + outbox + auditoria atómicos (ADR-0002).
- Uma só imagem OCI para API, worker e CLI.
- Risco: acoplamento acidental. Mitigação: contratos de evento fechados, revisão de imports por contexto
  (pendente: regra automática, por exemplo `import-linter`).

## Alternativas
Microserviços por camada (rejeitado: custo operacional, transações distribuídas e sagas desde o dia 1).

## Reversibilidade
Alta. Qualquer contexto pode ser extraído como serviço consumindo o EventBus, porque os contratos AsyncAPI já
existem.
