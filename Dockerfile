# syntax=docker/dockerfile:1

FROM node:20-alpine AS console
WORKDIR /console
COPY apps/console/package.json apps/console/package-lock.json* ./
RUN npm install
COPY apps/console/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
WORKDIR /app
COPY pyproject.toml README.md CONTEXT.md BUILD_PLAN.md ./
COPY flowlens ./flowlens
COPY apps/api ./apps/api
COPY configs ./configs
COPY benchmarks ./benchmarks
COPY tests ./tests
RUN pip install --no-cache-dir -e ".[dev]"
COPY --from=console /console/dist ./apps/console/dist
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=25s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
