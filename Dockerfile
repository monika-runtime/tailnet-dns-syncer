FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN groupadd --system app && useradd --system --gid app --no-create-home app

# Install dependencies
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ .

# Healthcheck — touches a pidfile on startup, verify it exists
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "from pathlib import Path; import os; exit(0 if Path('/var/run/tailnet-dns-syncer.pid').exists() else 1)" \
    || exit 1

USER app

CMD ["python3", "main.py"]
