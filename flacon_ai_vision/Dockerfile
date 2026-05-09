# ============= MULTI-STAGE BUILD: Reduce image size from 27GB to ~2-3GB =============

# Stage 1: Builder - Compile heavy dependencies
FROM python:3.10-slim as builder

WORKDIR /build

# Install build tools (temporary - removed in final image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake pkg-config \
    libsm6 libxext6 libxrender-dev \
    libgomp1 libboost-all-dev liblapack-dev \
    git curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download YOLO model
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" || echo "YOLO download skipped"

# ============= Stage 2: Runtime - Minimal image with only compiled dependencies =============
FROM python:3.10-slim

WORKDIR /app

# Install ONLY runtime dependencies (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsm6 libxext6 libxrender-dev libgomp1 curl \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy compiled Python packages from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages

# Copy YOLO model cache from builder
COPY --from=builder /root/.yolov8 /root/.yolov8

# Copy application code
COPY . .

# Clean up unnecessary files to reduce size (but keep frontend dist/)
RUN rm -rf \
    vms/frontend/node_modules \
    vms/frontend/.vite \
    .git .gitignore .venv \
    tests/ *.md \
    && find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true \
    && find /app -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5003/health || exit 1

# Run application
CMD ["uvicorn", "vms.backend.main:app", "--host", "0.0.0.0", "--port", "5003"]
