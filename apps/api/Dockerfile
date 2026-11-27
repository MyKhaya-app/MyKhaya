FROM python:3.13.18-slim-bookworm AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
# Vehicle Report PDFs (WeasyPrint): Pango/HarfBuzz text layout only. No system
# fonts are installed on purpose; reports embed the brand fonts below. The test
# stage builds on this one, so its PDF tests render exactly as the runtime does.
# These four exact Debian Security pins remediate CVE-2025-6020 without
# upgrading unrelated OS packages. When Debian supersedes this version, update
# both stage pins deliberately; a missing version then fails the build closed.
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		libpam-modules=1.5.2-6+deb12u3 \
		libpam-modules-bin=1.5.2-6+deb12u3 \
		libpam-runtime=1.5.2-6+deb12u3 \
		libpam0g=1.5.2-6+deb12u3 \
		libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
	&& rm -rf /var/lib/apt/lists/*
# Brand fonts and logo for reports, copied (never fetched) from the web app.
COPY apps/web/public/fonts/marketing/ /opt/mykhaya/report-assets/fonts/marketing/
COPY apps/web/public/images/marketing/mykhaya-logo-256.png /opt/mykhaya/report-assets/images/marketing/
# Reproducible PDFs: fontTools otherwise stamps the current time into every
# embedded font subset, so identical reports would differ byte for byte.
ENV SOURCE_DATE_EPOCH=0
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY apps/api/pyproject.toml ./
COPY apps/api/mykhaya ./mykhaya
RUN pip install --upgrade pip && pip install .

FROM builder AS test
RUN pip install '.[dev]'
COPY apps/api/tests ./tests
# Read-only, for test_migration_integrity.py: without this, the Alembic
# revision graph is invisible to the test image and that check silently
# passes over zero migrations instead of validating the real graph — see
# the 0029_home_calendar_colour orphaned-revision incident this test exists
# to catch.
COPY apps/api/migrations ./migrations
# Read-only, for test_colour_palette_consistency.py: it parses the TS/CSS palette
# source directly to prove mykhaya.colour_palette never silently drifts from
# packages/design-tokens, rather than trusting a hand-maintained comment.
COPY packages/design-tokens ./packages/design-tokens
RUN groupadd --system --gid 10001 mykhaya \
	&& useradd --system --uid 10001 --gid mykhaya --home-dir /build mykhaya \
	&& chown -R mykhaya:mykhaya /build
USER 10001:10001
CMD ["python", "-m", "pytest"]

FROM python:3.13.18-slim-bookworm AS runtime
ARG MYKHAYA_VERSION=unknown
ARG MYKHAYA_COMMIT_SHA=unknown
ARG MYKHAYA_BUILD_TIME=unknown
ARG MYKHAYA_BUILD_CHANNEL=development
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
	MYKHAYA_VERSION=$MYKHAYA_VERSION MYKHAYA_COMMIT_SHA=$MYKHAYA_COMMIT_SHA \
	MYKHAYA_BUILD_TIME=$MYKHAYA_BUILD_TIME MYKHAYA_BUILD_CHANNEL=$MYKHAYA_BUILD_CHANNEL
LABEL org.opencontainers.image.title="MyKhaya API" \
	org.opencontainers.image.description="MyKhaya FastAPI application, worker and scheduler runtime" \
	org.opencontainers.image.version="$MYKHAYA_VERSION" \
	org.opencontainers.image.revision="$MYKHAYA_COMMIT_SHA" \
	org.opencontainers.image.created="$MYKHAYA_BUILD_TIME" \
	org.opencontainers.image.source="https://github.com"
RUN groupadd --system --gid 10001 mykhaya && useradd --system --uid 10001 --gid mykhaya --home-dir /app mykhaya
# Vehicle Report PDF rendering (see the builder stage). The runtime starts from
# the base image independently, so the security pins are repeated here.
RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		libpam-modules=1.5.2-6+deb12u3 \
		libpam-modules-bin=1.5.2-6+deb12u3 \
		libpam-runtime=1.5.2-6+deb12u3 \
		libpam0g=1.5.2-6+deb12u3 \
		libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
	&& rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/mykhaya/report-assets /opt/mykhaya/report-assets
# The root filesystem is read-only in every environment (compose.yml); the
# fontconfig cache WeasyPrint uses lives on the /tmp tmpfs instead.
ENV SOURCE_DATE_EPOCH=0 XDG_CACHE_HOME=/tmp/.cache
COPY --from=builder /opt/venv /opt/venv
# Nothing installs packages at runtime, so the shipped image carries no pip
# (neither the base image's nor the venv's): its vendored libraries were the
# only remaining fixable findings in the image scan. Builder/test keep pip.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
	/usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
	/opt/venv/lib/python3.13/site-packages/pip /opt/venv/lib/python3.13/site-packages/pip-*.dist-info \
	/opt/venv/bin/pip /opt/venv/bin/pip3 /opt/venv/bin/pip3.13
WORKDIR /app
COPY --chown=mykhaya:mykhaya apps/api/alembic.ini ./
COPY --chown=mykhaya:mykhaya apps/api/migrations ./migrations
# Repository documentation for the BookStack sync (mykhaya.docs_sync). Built
# from the deployed branch, so DEV carries dev's docs and PROD carries main's.
# Root-owned and read-only to the app user; never served over HTTP.
COPY docs ./docs
# A fresh named volume mounted here inherits this directory's ownership on first
# use (only api actually writes to it — see compose.yml) — without this, Docker
# creates the volume owned by root and the non-root `mykhaya` user below can't
# write avatars to it. support-attachments mirrors the same need for its own
# dedicated volume (mykhaya.attachments.storage).
RUN mkdir -p /data/avatars /data/support-attachments /data/vehicle-photos /data/meal-images /data/home-migrations /data/legal-evidence \
	&& chown mykhaya:mykhaya /data/avatars /data/support-attachments /data/vehicle-photos /data/meal-images /data/home-migrations /data/legal-evidence
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2)"
CMD ["uvicorn","mykhaya.main:app","--host","0.0.0.0","--port","8000"]
