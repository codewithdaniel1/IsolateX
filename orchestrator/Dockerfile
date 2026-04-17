FROM python:3.12-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . orchestrator/

RUN useradd -r -u 1001 -g root isolatex
USER isolatex

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
