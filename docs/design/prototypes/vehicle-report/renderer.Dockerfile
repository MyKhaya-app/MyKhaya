# QA-only renderer for the Vehicle Report prototype. Same base as the API runtime.
FROM python:3.13.5-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 poppler-utils \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "weasyprint==70.0" "jinja2==3.1.6"
RUN useradd --uid 10001 --create-home render
USER 10001
WORKDIR /work
