#!/usr/bin/env bash
#
# Media Post Bot — ПОЛНАЯ установка "в один клик" (Phase 1: файлы до 20 МБ, хранение в MongoDB).
#
# Запуск от root из папки проекта:
#   bash deploy_phase1.sh <BOT_TOKEN> [SERVER_IP]
#
# Пример:
#   bash deploy_phase1.sh 123456:AA-xxxxx 94.183.178.153
#
set -euo pipefail

BOT_TOKEN="${1:-}"
SERVER_IP="${2:-$(hostname -I | awk '{print $1}')}"

if [ -z "$BOT_TOKEN" ]; then
    echo "Ошибка: не указан токен бота."
    echo "Использование: bash deploy_phase1.sh <BOT_TOKEN> [SERVER_IP]"
    exit 1
fi

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "==> Проект: $APP_DIR"
echo "==> IP сервера: $SERVER_IP"

echo "==> [1/6] Системные зависимости (Python, MongoDB, Docker, Node)"
bash "$APP_DIR/setup_hostvds.sh"

echo "==> [2/6] Python-окружение бэкенда"
cd "$APP_DIR/backend"
python3 -m venv venv
./venv/bin/pip install --upgrade pip >/dev/null
./venv/bin/pip install -r requirements.txt

echo "==> [3/6] backend/.env"
if [ ! -f "$APP_DIR/backend/.env" ]; then
    JWT="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
    cat > "$APP_DIR/backend/.env" <<EOF
MONGO_URL="mongodb://localhost:27017"
DB_NAME="mediabot"
CORS_ORIGINS="*"
TELEGRAM_BOT_TOKEN="$BOT_TOKEN"
PUBLIC_BASE_URL="http://$SERVER_IP"
JWT_SECRET="$JWT"
ADMIN_EMAIL="admin@mediabot.local"
ADMIN_PASSWORD="admin123"
ENABLE_BOT_POLLING="0"
R2_ENDPOINT=""
R2_ACCESS_KEY_ID=""
R2_SECRET_ACCESS_KEY=""
R2_BUCKET=""
R2_PUBLIC_BASE=""
EOF
    echo "   Создан backend/.env — ЗАПОЛНИ R2_* значения для отображения фото!"
else
    echo "   backend/.env уже существует — оставляю как есть"
fi

echo "==> [4/6] Сборка дашборда (frontend)"
cat > "$APP_DIR/frontend/.env" <<EOF
REACT_APP_BACKEND_URL=http://$SERVER_IP
EOF
cd "$APP_DIR/frontend"
yarn install
yarn build

echo "==> [5/6] systemd-сервис бота"
sed "s|__APPDIR__|$APP_DIR|g" "$APP_DIR/deploy/mediabot.service" > /etc/systemd/system/mediabot.service
systemctl daemon-reload
systemctl enable mediabot >/dev/null 2>&1 || true
systemctl restart mediabot

echo "==> [6/6] Nginx"
sed "s|__APPDIR__|$APP_DIR|g" "$APP_DIR/deploy/nginx-mediabot.conf" > /etc/nginx/sites-available/mediabot
ln -sf /etc/nginx/sites-available/mediabot /etc/nginx/sites-enabled/mediabot
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "=================================================="
echo " ГОТОВО! (Phase 1 — файлы до 20 МБ)"
echo ""
echo "  Бот      : напишите ему /start в Telegram"
echo "  Дашборд  : http://$SERVER_IP"
echo "  Логи бота: journalctl -u mediabot -f"
echo ""
echo "  Статус:"
echo "    mongod  -> $(systemctl is-active mongod)"
echo "    mediabot-> $(systemctl is-active mediabot)"
echo "    nginx   -> $(systemctl is-active nginx)"
echo "=================================================="
