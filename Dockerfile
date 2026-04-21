FROM python:3.11-slim

# System deps for opencv and psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libpq-dev \
    gcc \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# DATA_DIR and models are mounted as volumes at runtime
RUN mkdir -p data/raw models

EXPOSE 8000

CMD ["python", "main.py", "serve"]
