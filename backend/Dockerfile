# Backend Development Dockerfile
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated runtime environment for backend dependencies.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_DEFAULT_TIMEOUT="120"
ENV PIP_DISABLE_PIP_VERSION_CHECK="1"

# Set working directory
WORKDIR /app

# Copy dependency manifest first to maximize layer cache reuse.
COPY backend/requirements.txt /tmp/backend-requirements.txt

# Install backend dependencies with cache mount.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install -r /tmp/backend-requirements.txt

# Copy backend source code and deployment scripts
COPY backend ./backend
COPY scripts ./scripts

# Expose ports (gateway: 8001, langgraph: 2024)
EXPOSE 8001 2024

# Default command (can be overridden in docker-compose)
CMD ["sh", "-c", "cd backend && python -m uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001"]
