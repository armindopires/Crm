# WE web (Next.js standalone). Multi-stage, não-root.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/sdk-typescript/package.json packages/sdk-typescript/
COPY apps/web/package.json apps/web/
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm install -g pnpm@10.11.0 && pnpm install --frozen-lockfile --filter @we/web...
COPY packages/sdk-typescript packages/sdk-typescript
COPY apps/web apps/web
RUN npm install -g pnpm@10.11.0 >/dev/null 2>&1; pnpm --filter @we/web build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /src/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /src/apps/web/.next/static ./apps/web/.next/static
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
