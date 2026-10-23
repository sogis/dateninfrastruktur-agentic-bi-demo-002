# Resolved and pulled during local acceptance; immutable multi-platform image.
FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.13.5
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY LICENSE /app/LICENSE
COPY evidence/semantics/SLAYER_LICENSE.txt /app/SLAYER_LICENSE.txt
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    SLAYER_USAGE_REPORTING=off DO_NOT_TRACK=1 \
    SLAYER_APP_BUNDLE_DIR=/bundle SLAYER_APP_WORK_DIR=/work SLAYER_APP_HOST=0.0.0.0
USER 10001:0
EXPOSE 8000
CMD ["python", "-m", "slayer_app.server"]
