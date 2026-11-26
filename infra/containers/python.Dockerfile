# WE core (API + worker + CLI). Imagem OCI multi-stage, não-root, sem ferramentas de build em runtime.
FROM python:3.13-slim AS build
# CA opcional de proxy corporativo/inspeção TLS: secret de build (não persiste na imagem).
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir uv==0.7.8
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca UV_NATIVE_TLS=1; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY db/migrations ./db/migrations
COPY contracts/jsonschema ./contracts/jsonschema
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca UV_NATIVE_TLS=1; fi; \
    uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime
LABEL org.opencontainers.image.title="we-core" org.opencontainers.image.description="Wolf Enterprise core"
# Atualizações de segurança do SO e remoção do pip (e dependências vendorizadas): a runtime não instala pacotes.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip setuptools wheel 2>/dev/null; rm -rf /usr/local/lib/python3.13/site-packages/pip* \
       /usr/local/lib/python3.13/site-packages/setuptools* /usr/local/bin/pip*
RUN groupadd --system --gid 10001 we && useradd --system --uid 10001 --gid we --home /app --shell /usr/sbin/nologin we
WORKDIR /app
COPY --from=build --chown=root:root /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8000 9101
CMD ["uvicorn", "we_core.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
