# Stage 1: Build stage
FROM python:3.10-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Final runtime stage
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libpq5 \
    tesseract-ocr \
    tesseract-ocr-ind \
    tesseract-ocr-eng \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1
ENV VECLIB_MAXIMUM_THREADS=1

ARG ENABLE_EASYOCR_MODELS=0
RUN if [ "$ENABLE_EASYOCR_MODELS" = "1" ]; then python -c "import easyocr, time; code = 'success = False\nfor i in range(5):\n    try:\n        easyocr.Reader([\\'id\\', \\'en\\'], gpu=False)\n        print(\\'Download success\\')\n        success = True\n        break\n    except Exception as e:\n        print(f\\'Attempt {i+1} failed: {e}\\')\n        time.sleep(5)\nif not success:\n    print(\\'Failed to download models after 5 attempts\\')\n    raise SystemExit(1)\n'; exec(code)"; fi

# Copy application code
COPY . .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Default port, but Koyeb will override this with its own $PORT
ENV PORT=8000
ENV WS_PORT=8001
EXPOSE 8000
EXPOSE 8001

CMD ["python", "bot.py"]
