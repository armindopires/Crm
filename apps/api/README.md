# apps/api

Entrypoint da API. O código vive em `src/we_core/api` (pacote único, ADR-0001):

```bash
uv run uvicorn we_core.api.app:create_app --factory --port 8000
```
Imagem: `infra/containers/python.Dockerfile` (serviço `api` no compose).
