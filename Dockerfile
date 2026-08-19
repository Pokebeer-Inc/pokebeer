FROM python:3.12-slim

# Dependencies setup (PostgreSQL driver & Node.js/npm for Tailwind)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Security: Non-root application user creation with home directory (-m)
ARG UID=1000
ARG GID=1000

RUN groupadd --gid ${GID} appuser \
    && useradd --uid ${UID} --gid ${GID} --create-home appuser

WORKDIR /app

# Cache optimization: Install dependencies before code copy
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy source code and assign ownership
COPY --chown=appuser:appuser . /app

# Switch to non-root user
USER appuser