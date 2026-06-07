FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# System dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy lockfile and pyproject.toml
COPY pyproject.toml uv.lock ./

# Install dependencies (frozen to ensure lockfile is respected)
RUN uv sync --frozen --no-install-project

COPY . .

# Create log directory
RUN mkdir -p /app/logs

# Non-root user
RUN adduser --disabled-password --gecos "" agentuser
RUN chown -R agentuser:agentuser /app
USER agentuser

EXPOSE 8000
EXPOSE 8080

CMD ["uv", "run", "main.py", "start"]
