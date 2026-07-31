FROM node:22.17.0-alpine3.22 AS builder
RUN corepack enable && corepack prepare pnpm@10.14.0 --activate
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json .prettierignore ./
COPY packages ./packages
COPY apps/web ./apps/web
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @mykhaya/web build

FROM builder AS check
RUN pnpm --filter @mykhaya/web lint && pnpm --filter @mykhaya/web typecheck && pnpm --filter @mykhaya/web test

FROM node:22.17.0-alpine3.22 AS mobile-check
RUN corepack enable && corepack prepare pnpm@10.14.0 --activate
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json .prettierignore ./
COPY packages ./packages
COPY apps/mobile ./apps/mobile
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @mykhaya/mobile lint && pnpm --filter @mykhaya/mobile typecheck

FROM mcr.microsoft.com/playwright:v1.54.2-noble AS e2e
WORKDIR /workspace
COPY --from=builder /workspace /workspace
WORKDIR /workspace/apps/web
CMD ["./node_modules/.bin/playwright", "test"]

FROM node:22.17.0-alpine3.22 AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
RUN addgroup -S -g 10001 mykhaya && adduser -S -u 10001 -G mykhaya mykhaya
WORKDIR /app
COPY --from=builder --chown=mykhaya:mykhaya /workspace/apps/web/.next/standalone ./
COPY --from=builder --chown=mykhaya:mykhaya /workspace/apps/web/.next/static ./apps/web/.next/static
USER 10001:10001
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:3000/
CMD ["node","apps/web/server.js"]
