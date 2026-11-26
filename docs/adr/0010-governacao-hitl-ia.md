# ADR-0010 — Decisões com human-in-the-loop e segregação de funções reforçadas na base de dados; IA sem efeitos laterais

- **Estado:** aprovado · **Evidência:** DECISAO_APROVADA (princípios constitucionais §2, §13)

## Decisão
- Máquina de estados `proposed → under_review → approved|rejected → executed → superseded`, validada na API
  **e** num trigger PostgreSQL (`governance.guard_decision_transition`). Nem SQL direto contorna:
  - aprovação só por ator `human` quando `requires_human_approval`;
  - o proponente não pode aprovar (segregação de funções);
  - `executed` só a partir de `approved`;
  - contexto e proponente são imutáveis.
- `requires_human_approval` é sempre `true` em impacto jurídico, fiscal, financeiro, laboral, reputacional ou
  externo (CHECK). Nesta fase é `true` em todos os casos.
- A execução é **`recorded_only`**: não há efeitos externos (submissões, pagamentos, comunicações).
- AI Gateway: allowlist `summarize | classify | propose_decision`, `side_effects = blocked`, redação de padrões
  pessoais antes do fornecedor e `AI_TRACE` obrigatório (provider, model, versão de template, hashes de
  input/output, tokens, políticas). As propostas de IA exigem `ai_trace_id`. O papel `ai_agent` nunca recebe
  atos `HUMAN_ONLY`.
- Fornecedor atual: `LocalHeuristicProvider` (determinístico, sem rede). Integrar um LLM real exige novo ADR,
  DPIA e acordo de tratamento de dados.
