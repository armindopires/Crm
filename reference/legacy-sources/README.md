# Fontes de referência (não versionadas)

Coloque aqui, **sem alterar**, as fontes originais:

- `Nova_Geracao_Manuais_Wolf_Enterprise.txt`
- `WE_Pacote_Equipa_2026-06-18.zip`

O conteúdo desta pasta é ignorado pelo Git (pode conter dados de clientes, credenciais legadas e utilitários
de desencriptação). Só o manifesto é versionado:

```bash
uv run we source-manifest            # gera reference/manifests/sources.manifest.json
```

O ZIP é extraído para `reference/extracted/<sha256>/` (também ignorado), com proteção contra zip-slip.
Utilitários de desencriptação DBISAM e bases Firebird ficam marcados `requires_explicit_authorization`
e **não são executados** (ver `docs/security/threat-model.md` e `docs/runbooks/migracao-legado.md`).
