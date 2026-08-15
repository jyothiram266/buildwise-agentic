#!/bin/bash
set -e

# Log output to user-data.log for troubleshooting
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "[BuildWise EC2 Provisioner] Starting bootstrap on t3.small..."

# 1. Enable 2GB Swap space to optimize t3.small RAM performance
if [ ! -f /swapfile ]; then
    echo "[BuildWise] Creating 2GB swap space..."
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "[BuildWise] Swap created successfully."
fi

# 2. Install System Dependencies & Docker
echo "[BuildWise] Installing Docker & Git..."
apt-get update -y
apt-get install -y docker.io docker-compose-v2 git curl ca-certificates

systemctl enable --now docker
usermod -aG docker ubuntu || true

# 3. Clone Repository
APP_DIR="/home/ubuntu/buildwise-agentic"
if [ ! -d "$APP_DIR" ]; then
    echo "[BuildWise] Cloning repository from ${github_repo}..."
    git clone "${github_repo}" "$APP_DIR"
    chown -R ubuntu:ubuntu "$APP_DIR"
fi

cd "$APP_DIR"

# 4. Generate Production .env File
echo "[BuildWise] Generating .env configuration..."
cat <<EOF > .env
APP_ENV=prod
LOG_LEVEL=INFO
API_PORT=8000

DATABASE_URL=postgresql://buildwise:buildwise@postgres:5432/buildwise
REDIS_URL=redis://redis:6379/0
MOCK_CONNECTOR_URL=http://mock-connectors:8100

SECURITY_USER=${security_user}
SECURITY_PASSWORD=${security_password}

LLM_PROVIDER=${llm_provider}
OPENAI_API_KEY=${openai_api_key}

CLASSIFICATION_CONFIDENCE_THRESHOLD=0.70
AGENT_CONFIDENCE_THRESHOLD=0.70
SLIPPAGE_FLAG_DAYS=14
EOF

chown ubuntu:ubuntu .env

# 5. Start Container Stack with Docker Compose
echo "[BuildWise] Building & launching Docker containers..."
docker compose up -d --build

# 6. Wait for DB and execute Schema Migration, Seed Migration & Retrieval Ingest
echo "[BuildWise] Waiting for API container to initialize..."
sleep 20
docker compose exec -T api python scripts/migrate.py || true
docker compose exec -T api python -m db.seed.load_all || true
docker compose exec -T api python -m retrieval.ingest --all || true


echo "[BuildWise] Bootstrap Complete! OS Console active at http://$(curl -s http://checkip.amazonaws.com)/"
