FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Worker runs as root only when needed for tap/KVM access (microVM runtimes).
# For Docker runtime, you can run as non-root if the docker socket is group-accessible.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9090"]
