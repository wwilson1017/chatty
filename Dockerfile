# Stage 1: Build frontend
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Install WhatsApp bridge dependencies
FROM node:22-alpine AS bridge-deps
WORKDIR /bridge
COPY backend/whatsapp-bridge/package.json backend/whatsapp-bridge/package-lock.json* ./
RUN npm ci --production

# Stage 3: Python runtime
FROM python:3.12-slim
WORKDIR /app

# Install Node.js runtime (for whatsapp-bridge sidecar)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY backend/ ./backend/
COPY --from=frontend-build /build/dist ./frontend/dist/
COPY --from=bridge-deps /bridge/node_modules ./backend/whatsapp-bridge/node_modules/

ENV PYTHONUNBUFFERED=1

WORKDIR /app/backend
EXPOSE 8000

# Start WhatsApp bridge sidecar in background (if configured) alongside the Python backend
# Sidecar PORT is pinned to 3001 to avoid conflicts with cloud platforms that set PORT
CMD ["sh", "-c", "if [ -n \"$WHATSAPP_BRIDGE_URL\" ]; then PORT=3001 node whatsapp-bridge/index.js & fi; gunicorn main:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8000} --workers 1 --timeout 120"]
