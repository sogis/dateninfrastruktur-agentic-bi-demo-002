# Same base image as the data MCP of demo 002.
FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS build
RUN pip install --no-cache-dir uv==0.13.5
WORKDIR /app
COPY documents/pyproject.toml documents/uv.lock documents/.python-version ./
COPY documents/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# Only the built catalog; the raw stage (catalog/raw/) stays outside the image.
COPY catalog/catalog.json /app/catalog/catalog.json
# Rules (criteria, document profiles, access levels): the server reads them for the view in the chat.
COPY rules /app/rules
# Only the BGS. Government council decisions (personal data) never go into the image; they are mounted read-only
# at runtime (compose.ai-data.yml).
COPY corpus/bgs /app/corpus/bgs
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DOCUMENTS_HOST=0.0.0.0 DOCUMENTS_PORT=8000 \
    DOCUMENTS_CATALOG=/app/catalog/catalog.json DOCUMENTS_CORPUS=/app/corpus \
    DOCUMENTS_RULES=/app/rules DOCUMENTS_ACCESS=/app/access
USER 10001:0
EXPOSE 8000
CMD ["python", "-m", "documents_mcp.server"]
