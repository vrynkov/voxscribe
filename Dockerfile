# ---------- Step 1: build the React app ----------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Step 2: Python server that also serves the React files ----------
# Deepgram engine only: no PyTorch/pyannote, so the image is small and builds fast.
# The local engine stays available on your laptop (backend/requirements-local.txt).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Don't run as root inside the container
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 ENGINE=deepgram
WORKDIR /home/user/app

COPY --chown=user backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --user -r backend/requirements.txt

COPY --chown=user backend/app/ backend/app/
COPY --chown=user --from=web /web/dist frontend/dist

WORKDIR /home/user/app/backend
# Cloud Run tells the server which port to use in $PORT (8080 if not set).
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --no-access-log"]
