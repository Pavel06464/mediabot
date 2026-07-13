#!/usr/bin/env bash
#
# Обновление приложения на сервере (после git pull).
# НЕ трогает backend/.env. Запуск от root из папки проекта:
#   bash update.sh
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "==> Обновление зависимостей бэкенда"
cd "$APP_DIR/backend"
./venv/bin/pip install -q -r requirements.txt

echo "==> Пересборка дашборда"
cd "$APP_DIR/frontend"
yarn install
yarn build

echo "==> Обновление конфига nginx (лимиты загрузки/таймауты)"
sed "s|__APPDIR__|$APP_DIR|g" "$APP_DIR/deploy/nginx-mediabot.conf" > /etc/nginx/sites-available/mediabot
ln -sf /etc/nginx/sites-available/mediabot /etc/nginx/sites-enabled/mediabot
nginx -t

echo "==> Перезапуск сервисов"
systemctl restart mediabot
systemctl reload nginx

echo ""
echo "Готово. mediabot -> $(systemctl is-active mediabot), nginx -> $(systemctl is-active nginx)"
