FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Create data directory for SQLite (Railway provides persistent volume at /data)
RUN mkdir -p /data

# Copy seed script
COPY backend/scripts/seed_production_users.py ./seed_production_users.py

# Set environment variables
ENV PYTHONPATH=/app
ENV DATA_DIR=/data

# Expose port
EXPOSE 8000

# Run seed script then start the application
CMD ["sh", "-c", "python seed_production_users.py && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]