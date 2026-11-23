FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --include=dev
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements-central.txt /app/backend/requirements-central.txt
RUN python -m pip install --no-cache-dir -r backend/requirements-central.txt
COPY backend/ /app/backend/
COPY --from=frontend /build/frontend/dist /app/frontend/dist
RUN python -m uvicorn --version
CMD ["sh", "-c", "exec python -m uvicorn central:create_app --factory --app-dir backend --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
