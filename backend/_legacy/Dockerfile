# OILTRACE-AI backend image — CPU-only inference + FastAPI service.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OILTRACE_USE_SQLITE=1 \
    OILTRACE_MODELS_DIR=/app/models

WORKDIR /app

# PyTorch (CPU wheel, ~200 MB) installed first so the resolver never pulls CUDA builds.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Application code + trained model artifacts (kept out of the layer above).
COPY backend/app ./backend/app
COPY models ./models
COPY backend/db ./backend/db

WORKDIR /app/backend
EXPOSE 8000
# Bind 0.0.0.0 and honour the platform-injected $PORT (Render/Railway/Fly.io).
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import os,urllib.request; p=os.getenv('PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/api/v1/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]