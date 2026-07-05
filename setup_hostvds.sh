#!/usr/bin/env bash
#
# Media Post Bot — подготовка сервера HostVDS (Ubuntu 24.04)
# Запуск от root:  bash setup_hostvds.sh
# Скрипт идемпотентный — можно запускать повторно.
#
set -euo pipefail

echo "==> [1/5] Обновление системы и базовые пакеты"
export DEBIAN_FRONTEND=noninteractive
apt update
apt install -y python3-venv python3-pip git nginx curl gnupg ca-certificates

echo "==> [2/5] Пользователь deploy"
if ! id deploy >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" deploy
fi
usermod -aG sudo deploy

echo "==> [3/5] MongoDB 7.0"
if ! command -v mongod >/dev/null 2>&1; then
    curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc -o /tmp/mongo.asc
    gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor --yes /tmp/mongo.asc
    echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
        | tee /etc/apt/sources.list.d/mongodb-org-7.0.list >/dev/null
    apt update
    apt install -y mongodb-org
fi
systemctl enable --now mongod

echo "==> [4/5] Docker (для Local Bot API Server)"
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh
fi
usermod -aG docker deploy || true

echo "==> [5/5] Node.js 20 + yarn (для сборки дашборда)"
if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_20.x -o /tmp/node.sh
    bash /tmp/node.sh
    apt install -y nodejs
fi
npm install -g yarn >/dev/null 2>&1 || true

echo ""
echo "======================================================"
echo " Готово. Проверка:"
echo "   mongod   -> $(systemctl is-active mongod)"
echo "   docker   -> $(command -v docker >/dev/null && echo ok || echo MISSING)"
echo "   node     -> $(node -v 2>/dev/null || echo MISSING)"
echo ""
echo " Дальше:"
echo "   1) Запустить Local Bot API Server (см. DEPLOYMENT_HOSTVDS.md, шаг 3)"
echo "   2) Настроить backend/.env (токен, R2, MONGO_URL)"
echo "   3) systemd-сервис mediabot (шаг 7)"
echo "======================================================"
