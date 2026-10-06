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

# Run seed script then start the application.
# ";" (not "&&"): o bootstrap de utilizadores de demonstração é uma
# convenience. Se falhar, a aplicação DEVE arrancar na mesma — caso
# contrário um seed quebrado deixa o serviço em crash-loop.
# "--forwarded-allow-ips='*'": O edge do Railway faz strip+rebuild do
# X-Forwarded-For (leftmost = IP real do cliente, staff Railway confirmado) e o
# contentor so e alcancavel pelo edge. Sem isto o uvicorn so confia em XFF de
# 127.0.0.1, vê o pool 100.64.0.x rotativo como "cliente" e o rate limit por IP
# (slowapi/get_remote_address) nunca dispara em producao.
CMD ["sh", "-c", "python seed_production_users.py; uvicorn backend.main:app --host 0.0.0.0 --port 8000 --forwarded-allow-ips='*'"]