FROM node:22.17.0-alpine3.22 AS builder
ARG MYKHAYA_VERSION=unknown
ARG MYKHAYA_COMMIT_SHA=unknown
ARG MYKHAYA_BUILD_TIME=unknown
ARG MYKHAYA_BUILD_CHANNEL=development
RUN corepack enable && corepack prepare pnpm@10.14.0 --activate
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json .prettierignore ./
COPY packages ./packages
COPY apps/web ./apps/web
COPY VERSION ./VERSION
ENV MYKHAYA_VERSION=$MYKHAYA_VERSION MYKHAYA_COMMIT_SHA=$MYKHAYA_COMMIT_SHA MYKHAYA_BUILD_TIME=$MYKHAYA_BUILD_TIME MYKHAYA_BUILD_CHANNEL=$MYKHAYA_BUILD_CHANNEL
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
COPY VERSION ./VERSION
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @mykhaya/mobile lint && pnpm --filter @mykhaya/mobile typecheck

FROM mcr.microsoft.com/playwright:v1.55.1-noble AS e2e
WORKDIR /workspace
COPY --from=builder --chown=pwuser:pwuser /workspace /workspace
WORKDIR /workspace/apps/web
# pwuser is the non-root account Microsoft's Playwright image ships specifically
# for this — browser sandboxing keeps working under it (unlike an arbitrary
# non-root user, which typically needs --no-sandbox or extra capabilities).
USER pwuser
CMD ["./node_modules/.bin/playwright", "test"]

FROM node:22.17.0-alpine3.22 AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
ARG MYKHAYA_VERSION=unknown
ARG MYKHAYA_COMMIT_SHA=unknown
ARG MYKHAYA_BUILD_TIME=unknown
ARG MYKHAYA_BUILD_CHANNEL=development
LABEL org.opencontainers.image.title="MyKhaya Web" \
	org.opencontainers.image.description="MyKhaya Next.js web and control centre frontend" \
	org.opencontainers.image.version="$MYKHAYA_VERSION" \
	org.opencontainers.image.revision="$MYKHAYA_COMMIT_SHA" \
	org.opencontainers.image.created="$MYKHAYA_BUILD_TIME" \
	org.opencontainers.image.source="https://github.com"
RUN addgroup -S -g 10001 mykhaya && adduser -S -u 10001 -G mykhaya mykhaya
WORKDIR /app
COPY --from=builder --chown=mykhaya:mykhaya /workspace/apps/web/.next/standalone ./
COPY --from=builder --chown=mykhaya:mykhaya /workspace/apps/web/.next/static ./apps/web/.next/static
# Next.js standalone output does NOT include public/ automatically — without this,
# every file under apps/web/public (notably sw.js, the service worker) 404s in the
# deployed container even though it works under `next dev`, where public/ is served
# directly. This silently broke the service worker/PWA install path in every
# deployment of this image until now.
COPY --from=builder --chown=mykhaya:mykhaya /workspace/apps/web/public ./apps/web/public
COPY --from=builder --chown=mykhaya:mykhaya /workspace/VERSION /app/VERSION
ENV MYKHAYA_VERSION=$MYKHAYA_VERSION MYKHAYA_COMMIT_SHA=$MYKHAYA_COMMIT_SHA MYKHAYA_BUILD_TIME=$MYKHAYA_BUILD_TIME MYKHAYA_BUILD_CHANNEL=$MYKHAYA_BUILD_CHANNEL
USER 10001:10001
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:3000/
CMD ["node","apps/web/server.js"]
