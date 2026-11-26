---
name: we-legacy-intake
description: Receber e inventariar fontes legadas ou o pacote WE (ZIP, XLSX, DOCX, JSON, SQL) com hash, autoridade e proteção de dados, sem executar utilitários nem migrar credenciais. Usar quando forem fornecidos ficheiros de referência ou depósitos de sistemas legados (CrmContab, SIGEP32, Filosoft/SNC32, SAF-T, CentralGest, Gimo32).
---

# Intake de fontes legadas e do pacote WE

1. Copiar os originais para `reference/legacy-sources/` (ignorado pelo Git). **Nunca editar originais.**
2. `uv run we source-manifest`: SHA-256, autoridade 1–8, extração ZIP segura, alertas
   `requires_explicit_authorization`.
3. Ordem de leitura do pacote: `00_LEIA-ME.md` → `00_TRANSVERSAL_WE/WE_Base_Conhecimento_MASTER.xlsx` →
   `Decisao_Senior_Migracao_WE.docx` → depósitos JSON + schemas → SQL, mapeamentos, ER, ETL → manuais → protótipos.
   Ler XLSX e DOCX programaticamente (`openpyxl`, `python-docx`, grupo `dev`) e resumir por domínio, com
   ficheiro, folha ou secção e hash. Não despejar o conteúdo integral.
4. Classificar cada conclusão: FACTO_CONFIRMADO · DECISAO_APROVADA · INFERIDO_A_VALIDAR · PROPOSTA_TECNICA ·
   DESATUALIZADO_OU_CONFLITUANTE · NAO_INDICADO.
5. Depósitos JSON: `uv run we import-knowledge --tenant <uuid> --actor-subject <sub> --deposit X.json --schema X.schema.json --source-system CRMCONTAB`.
   Um depósito inválido vai para a quarentena e não é importado.
6. **Credenciais encontradas**: registar só a existência e a localização lógica. Nunca mostrar valores.
7. **Utilitários DBISAM/desencriptação**: não executar sem autorização explícita (ver
   `docs/runbooks/migracao-legado.md`).
8. O DDL transversal pode ser SIGEP32: não o executar como kernel WE.
9. Regras fiscais e contributivas: validar em fonte oficial atual (DRE, AT, SS, CNC, OCC, OROC) com data, URL e
   hash. Sem acesso, marcar `VALIDACAO_EXTERNA_PENDENTE`.
10. Atualizar `docs/architecture/source-inventory.md`, a matriz de rastreabilidade e os ADR afetados.
