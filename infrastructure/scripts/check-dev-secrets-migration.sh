#!/usr/bin/env bash
# DEV Docker Secrets migration rehearsal (CI and local), MK-SEC-001 v1.2.
#
# Runs the real DEV deployment scripts, Compose files and images through
# legacy -> F-03 -> file-backed secrets -> rollback, with synthetic credentials.
# The DEV stack has fixed project, volume and network names, so everything runs
# inside a disposable nested Docker daemon: it shares no containers, volumes or
# networks with this host, and is removed on exit.
#
# Expects the repository root as the working directory. API_IMAGE and WEB_IMAGE
# name already built images (default: this project's Compose images).
set -euo pipefail

DIND_IMAGE=docker:28.5.2-dind
API_IMAGE=${API_IMAGE:-mykhaya-api}
WEB_IMAGE=${WEB_IMAGE:-mykhaya-web}
NAME="mk-dev-secrets-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
export MSYS_NO_PATHCONV=1

cleanup() { docker rm -f -v "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

for image in "$API_IMAGE" "$WEB_IMAGE"; do
  docker image inspect "$image" >/dev/null 2>&1 || { echo "Build $image first" >&2; exit 1; }
done
for image in postgres:17.5-alpine3.22 redis:8.0.3-alpine3.21 caddy:2.10.0-alpine; do
  docker image inspect "$image" >/dev/null 2>&1 || docker pull -q "$image" >/dev/null
done
MAILPIT=$(sed -n '/^  mailpit:/,/image:/s/^ *image: *//p' compose.yml | tr -d '\r')
docker image inspect "$MAILPIT" >/dev/null 2>&1 || docker pull -q "$MAILPIT" >/dev/null

docker run -d --privileged --name "$NAME" -e DOCKER_TLS_CERTDIR= "$DIND_IMAGE" dockerd --host=unix:///var/run/docker.sock >/dev/null
for _ in $(seq 1 60); do
  docker exec "$NAME" docker info >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$NAME" docker info >/dev/null || { docker logs "$NAME" 2>&1 | tail -5; exit 1; }
docker exec "$NAME" apk add --no-cache -q bash python3 git curl sudo age coreutils findutils diffutils grep openssl

echo "== Loading images into the nested daemon"
docker save "$API_IMAGE" "$WEB_IMAGE" postgres:17.5-alpine3.22 redis:8.0.3-alpine3.21 \
  caddy:2.10.0-alpine "$MAILPIT" | docker exec -i "$NAME" docker load -q >/dev/null
for service in api worker scheduler migrate; do
  docker exec "$NAME" docker tag "$API_IMAGE" "mykhaya-$service"
done
docker exec "$NAME" docker tag "$WEB_IMAGE" mykhaya-web

# The tracked and new files as they are now, without any ignored file (.env).
git ls-files -z --cached --others --exclude-standard |
  while IFS= read -r -d '' f; do [ ! -f "$f" ] || printf '%s\0' "$f"; done |
  tar --null -T - -cf - | docker exec -i "$NAME" sh -c 'mkdir -p /srv/mykhaya && tar -xf - -C /srv/mykhaya'
docker exec "$NAME" bash /srv/mykhaya/infrastructure/tests/dev_secrets_rehearsal.sh
