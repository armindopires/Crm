# Verificação de integridade

```bash
uv run we verify-chains --tenant <uuid>    # eventos + auditoria; exit 1 se inválido
uv run we verify-evidence --tenant <uuid>  # recalcula SHA-256 de todos os objetos
```
API: `GET /v1/events/verify`, `GET /v1/audit/verify`, `POST /v1/evidence/{id}/verify`.

Problemas reportados: `content` (registo alterado), `link`/`gap` (remoção ou reordenação), `head` (truncagem).

**Se a verificação falhar:** tratar como incidente de segurança. (1) Congelar escritas desse tenant;
(2) preservar dump e logs (cadeia de custódia); (3) comparar com o último backup verificado; (4) registar uma
DECISION de incidente; (5) não "corrigir" a cadeia reescrevendo hashes.
