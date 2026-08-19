FROM python:3.12-slim

# Dependencies setup (PostgreSQL driver & Node.js/npm for Tailwind)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Security: Non-root application user creation with home directory (-m)
RUN groupadd -r appuser && useradd -r -m -g appuser appuser

WORKDIR /app

# Cache optimization: Install dependencies before code copy
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy source code and assign ownership
COPY --chown=appuser:appuser . /app

# Switch to non-root user
USER appuser