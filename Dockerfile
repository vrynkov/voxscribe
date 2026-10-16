# ---------- Step 1: build the React app ----------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Step 2: Python server that also serves the React files ----------
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces runs containers as user 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface PYTHONUNBUFFERED=1
WORKDIR /home/user/app

# CPU-only PyTorch is much smaller than the default GPU build
COPY --chown=user backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --user torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir --user -r backend/requirements.txt

COPY --chown=user backend/ backend/
COPY --chown=user --from=web /web/dist frontend/dist

WORKDIR /home/user/app/backend
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
