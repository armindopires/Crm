# Inventário de fontes

**Estado em 2026-11-26: as duas fontes obrigatórias estão AUSENTES.** Ver ADR-0014.

| Fonte esperada | Estado | Impacto |
|---|---|---|
| `Nova_Geracao_Manuais_Wolf_Enterprise.txt` | **NAO_INDICADO** (não está no repositório, na branch `main` nem no contentor) | Princípios constitucionais tomados do prompt mestre; terminologia fina e manuais por validar |
| `WE_Pacote_Equipa_2026-06-18.zip` | **NAO_INDICADO** | MASTER.xlsx, Decisão Sénior DOCX, depósitos JSON, DDL, ETL e manuais não inspecionados. O modelo canónico segue apenas o §10 do prompt |

Manifesto versionado: `reference/manifests/sources.manifest.json` (gerado por `uv run we source-manifest`).

## O que acontece quando as fontes forem colocadas em `reference/legacy-sources/`
1. SHA-256 de cada ficheiro e de cada membro do ZIP. Extração para `reference/extracted/<hash>/` (fora do Git),
   com proteção contra zip-slip e limites de tamanho.
2. Autoridade 1–8 segundo a hierarquia do §4, e estado de evidência inicial `INFERIDO_A_VALIDAR`.
3. Alertas de sensibilidade: utilitários de desencriptação, `.fdb`/`.gdb`, chaves e certificados ficam marcados
   `requires_explicit_authorization` e **nunca são executados**.
4. Os depósitos JSON importam-se com `we import-knowledge --deposit … --schema …`, só depois de validados.

## Restrições do §5 tratadas como DECISAO_APROVADA, sem verificação na fonte
CrmContab com 218 tabelas, 217 PK e praticamente sem FK; Firebird com credenciais em texto simples; utilitários
DBISAM; DDL transversal que é SIGEP32; SQLite como protótipo; Filosoft como system of record. Estão refletidas
em `legacy.source_systems` (migração 0007) e nos ADR 0012/0014.
