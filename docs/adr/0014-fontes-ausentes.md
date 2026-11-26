# ADR-0014 — Fontes de referência ausentes: execução com NAO_INDICADO

- **Estado:** aprovado · **Evidência:** FACTO_CONFIRMADO

## Contexto
Em 2026-11-26, nem `Nova_Geracao_Manuais_Wolf_Enterprise.txt` nem `WE_Pacote_Equipa_2026-06-18.zip` estão no
repositório, na branch `main` ou no contentor.

## Decisão
- A plataforma foi construída a partir das restrições explícitas do prompt (que trata como DECISAO_APROVADA os
  achados do §5). Factos que dependam do pacote ficam `NAO_INDICADO`.
- `reference/manifests/sources.manifest.json` regista as duas fontes como `NAO_INDICADO`. O comando
  `we source-manifest` passa a calcular hashes, autoridade, alertas de sensibilidade e a extração ZIP segura logo
  que as fontes sejam colocadas em `reference/legacy-sources/` (fora do Git).
- O importador foi provado com um depósito **sintético** (`db/seeds/knowledge/`), sem reproduzir a estrutura real.

## Próxima ação
O utilizador coloca as fontes em `reference/legacy-sources/` e corre `we source-manifest`. Depois inspecionam-se
o MASTER.xlsx e o DOCX de decisão (pela ordem do §3) e reavaliam-se os ADR 0011, 0012 e o modelo canónico.
