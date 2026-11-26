# Rotação de segredos

| Segredo | Onde vive (dev) | Rotação |
|---|---|---|
| Passwords `we_app`/`we_worker` | `.env` | Alterar no `.env`, `uv run we migrate` (reaplica `ALTER ROLE … PASSWORD`), reiniciar api/worker |
| Password `we_admin` | `.env` / volume | `ALTER ROLE we_admin PASSWORD …` e atualizar o `.env` |
| Credenciais S3 | `.env` + `.local/seaweed-s3.json` | Alterar o `.env`, `python scripts/dev.py bootstrap` (regenera o JSON), reiniciar o objectstore |
| Password Redis | `.env` | Alterar e reiniciar redis + api |
| Chave de assinatura dev | `.local/dev-signing-key.pem` | Apagar `.local/dev-*`, `bootstrap`, reiniciar a api. Tokens antigos ficam inválidos |
| `WE_AUDIT_PSEUDONYM_KEY` | `.env` | Rotação quebra a correlação de pseudónimos: registar a data numa decisão (DECISION) e guardar a chave antiga em cofre durante o período de retenção |

Produção: todos os segredos por referência a cofre (Vault/KMS, fornecedor NAO_INDICADO), com rotação automática
e credenciais dinâmicas para a base de dados. **Nunca** em variáveis versionadas, payloads de eventos ou logs.
