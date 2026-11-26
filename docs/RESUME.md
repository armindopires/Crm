# RESUME — continuação do trabalho

Última sessão: 2026-11-26. Branch: `claude/wolf-enterprise-foundation-v2esle`.

## Estado num parágrafo
A fundação da WE está implementada e verificada localmente: o perfil core arranca, as 9 migrações correm numa
base vazia, há 51 testes (unitários, contrato e integração adversarial), a demonstração vertical passa 14/14
contra a stack contentorizada, os scans estão limpos (0 segredos, 0 vulnerabilidades conhecidas nas
dependências, 0 CRITICAL nas imagens) e o backup/restore foi provado com cadeias verificadas. **As duas fontes
do pacote WE continuam ausentes** e o IdP de produção não está decidido.

## Retomar em 5 minutos
```bash
python scripts/dev.py bootstrap && python scripts/dev.py start core ui && python scripts/dev.py verify
```

## Próxima ação exata
1. **Fornecer as fontes**: copiar `Nova_Geracao_Manuais_Wolf_Enterprise.txt` e
   `WE_Pacote_Equipa_2026-06-18.zip` para `reference/legacy-sources/` e correr `uv run we source-manifest`.
   Seguir a skill `.claude/skills/we-legacy-intake` (ordem de leitura do §3, classificação da evidência).
2. Com o MASTER.xlsx e o DOCX de decisão lidos: rever o modelo canónico (`docs/architecture/data-and-event-model.md`),
   os ADR 0011/0012 e importar os depósitos JSON reais com `we import-knowledge` num tenant interno.
3. **Decisão do utilizador** sobre o IdP de produção (ADR-0006). Depois disso: fluxo OIDC + PKCE na consola web.

## Milestone seguinte recomendada (M6 — Workflow e Matrix Engine)
Ordem oficial: Data Hub e Event Store (feito) → Knowledge Repository (base feita) → **Workflow e Matrix Engine**.
- Adaptador Temporal (perfil `orchestration`) sobre `workflow.definitions` e `workflow.instances` (versão fixada).
- Passos com CHECKPOINT → EVIDENCE → DECISION, pausa, retry, compensação, timeout e aprovação humana.
- Primeiro processo piloto: onboarding de cliente (sintético), com prova de conclusão.

## Onde está o quê
- Estado detalhado: `docs/STATUS.md` · Lacunas: `docs/architecture/known-gaps.md`
- Rastreabilidade: `docs/architecture/traceability-matrix.md` · Plano: `docs/architecture/plan.md`
