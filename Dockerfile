# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application source code
COPY . .

# Create necessary directories if they don't exist
RUN mkdir -p frontend/css frontend/js

# Expose port 8000 for FastAPI
EXPOSE 8000

# Set environment variable for Ollama URL (will be overridden by docker-compose)
ENV OLLAMA_BASE_URL=http://localhost:11434

# Default command to run the FastAPI application
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]