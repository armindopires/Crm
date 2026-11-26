# Arranque e paragem

Pré-requisitos: Docker com Compose v2, `uv` ≥ 0.7, Node 22 + pnpm 10 (só para a web fora de contentores).

```bash
python scripts/dev.py bootstrap      # gera .env (segredos aleatórios) e .local/ (chaves dev); instala deps
python scripts/dev.py start          # perfil core: postgres, nats, redis, objectstore, migrate, api, worker
python scripts/dev.py start core ui  # + consola web em http://localhost:3000
python scripts/dev.py demo           # demonstração vertical (14 passos)
python scripts/dev.py stop           # pára sem apagar volumes
```

Verificação: `curl localhost:8000/health/ready` → `{"status":"ok",…}`; métricas do worker em
`localhost:9101/metrics`.

Atrás de um proxy com inspeção TLS, defina `WE_BUILD_CA_FILE=/caminho/ca.pem` no `.env` antes do `start`. A CA é
passada ao build como BuildKit secret e não fica nas imagens.

Windows: os comandos são os mesmos (`py scripts\dev.py …`). Não há dependência de bash.

`python scripts/dev.py reset` **apaga volumes locais** e pede confirmação escrita (`APAGAR-LOCAL`). Nunca usar
fora de desenvolvimento.
