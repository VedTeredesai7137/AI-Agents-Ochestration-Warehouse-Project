# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OLLAMA_URL=http://ollama:11434/api/generate

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy runtime code only; credentials, local environments and graph data stay outside.
COPY backend/ backend/
COPY frontend/ frontend/

# The application needs no privileged operations.
RUN useradd --create-home --uid 10001 swarm && chown swarm:swarm /app
USER swarm

# Expose port 8000 for FastAPI
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=5).close()"

# Default command to run the FastAPI application
# In-memory simulation state must stay in one worker.
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
