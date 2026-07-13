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

echo "==> Перезапуск сервисов"
systemctl restart mediabot
systemctl reload nginx

echo ""
echo "Готово. mediabot -> $(systemctl is-active mediabot), nginx -> $(systemctl is-active nginx)"
