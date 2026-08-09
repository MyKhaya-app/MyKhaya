FROM python:3.13.5-slim-bookworm AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY VERSION ./VERSION
COPY apps/api/pyproject.toml ./
COPY apps/api/mykhaya ./mykhaya
RUN pip install --upgrade pip && pip install .

FROM builder AS test
RUN pip install '.[dev]'
COPY apps/api/tests ./tests
CMD ["python", "-m", "pytest"]

FROM python:3.13.5-slim-bookworm AS runtime
ARG MYKHAYA_VERSION=unknown
ARG MYKHAYA_COMMIT_SHA=unknown
ARG MYKHAYA_BUILD_TIME=unknown
ARG MYKHAYA_BUILD_CHANNEL=development
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
LABEL org.opencontainers.image.title="MyKhaya API" \
	org.opencontainers.image.description="MyKhaya FastAPI application, worker and scheduler runtime" \
	org.opencontainers.image.version="$MYKHAYA_VERSION" \
	org.opencontainers.image.revision="$MYKHAYA_COMMIT_SHA" \
	org.opencontainers.image.created="$MYKHAYA_BUILD_TIME" \
	org.opencontainers.image.source="https://github.com"
RUN groupadd --system --gid 10001 mykhaya && useradd --system --uid 10001 --gid mykhaya --home-dir /app mykhaya
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=mykhaya:mykhaya VERSION /app/VERSION
COPY --chown=mykhaya:mykhaya apps/api/alembic.ini ./
COPY --chown=mykhaya:mykhaya apps/api/migrations ./migrations
# A fresh named volume mounted here inherits this directory's ownership on first
# use (only api actually writes to it — see compose.yml) — without this, Docker
# creates the volume owned by root and the non-root `mykhaya` user below can't
# write avatars to it.
RUN mkdir -p /data/avatars && chown mykhaya:mykhaya /data/avatars
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2)"
CMD ["uvicorn","mykhaya.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips","10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"]
