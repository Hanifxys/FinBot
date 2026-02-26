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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Pre-download EasyOCR models (id and en) with retry logic
# This makes the image larger but startup MUCH faster
RUN python -c "import easyocr; import time; \
    for i in range(5): \
        try: \
            easyocr.Reader(['id', 'en'], gpu=False); \
            print('Download success'); \
            break; \
        except Exception as e: \
            print(f'Attempt {i+1} failed: {e}'); \
            time.sleep(5); \
    else: \
        print('Failed to download models after 5 attempts'); \
        exit(1)"

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
