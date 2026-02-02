#!/usr/bin/env bash
set -euo pipefail

# ===========================================
# LeadGen API — DigitalOcean Droplet Deploy
# Run this script on a fresh Ubuntu 24.04 Droplet
# ===========================================

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="docker-compose.prod.yml"

echo "=========================================="
echo " LeadGen API — Production Deployment"
echo "=========================================="

# -------------------------------------------
# 1. Install Docker if not present
# -------------------------------------------
if ! command -v docker &> /dev/null; then
    echo "[1/6] Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "[1/6] Docker installed."
else
    echo "[1/6] Docker already installed, skipping."
fi

# -------------------------------------------
# 2. Set up firewall
# -------------------------------------------
echo "[2/6] Configuring firewall..."
if command -v ufw &> /dev/null; then
    ufw --force enable
    ufw allow ssh
    ufw allow 80/tcp    # API
    ufw allow 5555/tcp  # Flower monitoring
    echo "[2/6] Firewall configured (SSH, HTTP:80, Flower:5555)."
else
    echo "[2/6] ufw not found, skipping firewall setup."
fi

# -------------------------------------------
# 3. Set up .env file
# -------------------------------------------
cd "$REPO_DIR"

if [ ! -f .env ]; then
    echo "[3/6] Creating .env from .env.production..."
    cp .env.production .env

    # Auto-generate SECRET_KEY if still placeholder
    if grep -q "CHANGE_ME_generate_a_secret_key" .env; then
        SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || openssl rand -base64 48)
        sed -i "s|CHANGE_ME_generate_a_secret_key|${SECRET}|g" .env
    fi

    # Auto-generate API_KEY_SALT if still placeholder
    if grep -q "CHANGE_ME_generate_a_salt" .env; then
        SALT=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32)
        sed -i "s|CHANGE_ME_generate_a_salt|${SALT}|g" .env
    fi

    # Auto-generate DB password if still placeholder
    if grep -q "CHANGE_ME_strong_db_password" .env; then
        DB_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))" 2>/dev/null || openssl rand -base64 24)
        sed -i "s|CHANGE_ME_strong_db_password|${DB_PASS}|g" .env
    fi

    # Auto-generate Flower password if still placeholder
    if grep -q "CHANGE_ME_flower_password" .env; then
        FL_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))" 2>/dev/null || openssl rand -base64 16)
        sed -i "s|CHANGE_ME_flower_password|${FL_PASS}|g" .env
    fi

    echo "[3/6] .env created with auto-generated secrets."
    echo "       Review it: nano $REPO_DIR/.env"
else
    echo "[3/6] .env already exists, skipping."
fi

# -------------------------------------------
# 4. Build and start services
# -------------------------------------------
echo "[4/6] Building and starting services..."
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d
echo "[4/6] Services started."

# -------------------------------------------
# 5. Run database migrations
# -------------------------------------------
echo "[5/6] Waiting for database to be ready..."
sleep 5

# Wait for DB health check
for i in $(seq 1 30); do
    if docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U leadgen -d leadgen &> /dev/null; then
        break
    fi
    echo "       Waiting for database... ($i/30)"
    sleep 2
done

echo "[5/6] Running database migrations..."
docker compose -f "$COMPOSE_FILE" exec -T api python -m alembic upgrade head
echo "[5/6] Migrations complete."

# -------------------------------------------
# 6. Verify deployment
# -------------------------------------------
echo "[6/6] Verifying deployment..."
sleep 3

if curl -sf http://localhost/health > /dev/null 2>&1; then
    echo ""
    echo "=========================================="
    echo " Deployment successful!"
    echo "=========================================="
    echo ""
    echo " API:     http://$(curl -sf ifconfig.me 2>/dev/null || echo '<your-droplet-ip>')/health"
    echo " Flower:  http://$(curl -sf ifconfig.me 2>/dev/null || echo '<your-droplet-ip>'):5555"
    echo ""
    echo " Flower credentials are in .env (FLOWER_USER / FLOWER_PASSWORD)"
    echo ""
    echo " To add API keys later, edit .env and restart:"
    echo "   nano $REPO_DIR/.env"
    echo "   docker compose -f $COMPOSE_FILE restart api worker"
    echo ""
else
    echo ""
    echo "[!] Health check failed. Check logs:"
    echo "    docker compose -f $COMPOSE_FILE logs api"
    echo ""
    exit 1
fi
