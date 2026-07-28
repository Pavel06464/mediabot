#!/usr/bin/env bash
#
# Установка Local Bot API Server (файлы до 2 ГБ) на VPS.
# Запуск от root из папки проекта:
#   bash setup_local_bot_api.sh <API_ID> <API_HASH> <BOT_TOKEN>
#
# Где взять API_ID / API_HASH: https://my.telegram.org -> "API development tools".
# BOT_TOKEN — тот же токен от @BotFather, что и в backend/.env.
#
set -euo pipefail

API_ID="${1:-}"
API_HASH="${2:-}"
BOT_TOKEN="${3:-}"
PORT="${4:-8081}"

if [ -z "$API_ID" ] || [ -z "$API_HASH" ] || [ -z "$BOT_TOKEN" ]; then
    echo "Использование: bash setup_local_bot_api.sh <API_ID> <API_HASH> <BOT_TOKEN> [PORT]"
    echo "  API_ID / API_HASH -> https://my.telegram.org (API development tools)"
    exit 1
fi

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$APP_DIR/backend/.env"

echo "==> [1/5] Проверка Docker"
if ! command -v docker >/dev/null 2>&1; then
    echo "   Docker не найден — устанавливаю"
    curl -fsSL https://get.docker.com | sh
fi

echo "==> [2/5] logOut бота из облачного api.telegram.org"
# Токен можно использовать ЛИБО в облаке, ЛИБО на локальном сервере.
# Перед переходом на локальный сервер бот обязан выйти из облака.
LOGOUT=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/logOut" || true)
echo "   Ответ: ${LOGOUT}"
sleep 2

echo "==> [3/5] Запуск контейнера telegram-bot-api (порт ${PORT})"
docker rm -f telegram-bot-api >/dev/null 2>&1 || true
docker run -d --name telegram-bot-api \
    --restart unless-stopped \
    -p 127.0.0.1:${PORT}:8081 \
    -e TELEGRAM_API_ID="${API_ID}" \
    -e TELEGRAM_API_HASH="${API_HASH}" \
    -e TELEGRAM_LOCAL=1 \
    -e TELEGRAM_MAX_WEBHOOK_CONNECTIONS=0 \
    -v telegram-bot-api-data:/var/lib/telegram-bot-api \
    aiogram/telegram-bot-api:latest

echo "==> [4/5] Проверка"
sleep 4
docker logs telegram-bot-api --tail 15 || true
if curl -s "http://127.0.0.1:${PORT}" >/dev/null 2>&1; then
    echo "   Сервер отвечает на http://127.0.0.1:${PORT}"
else
    echo "   ВНИМАНИЕ: сервер пока не отвечает — проверьте docker logs telegram-bot-api"
fi

echo "==> [5/5] Прописываю TELEGRAM_LOCAL_API_URL в backend/.env"
LOCAL_URL="http://127.0.0.1:${PORT}"
if [ -f "$ENV_FILE" ]; then
    if grep -q '^TELEGRAM_LOCAL_API_URL=' "$ENV_FILE"; then
        sed -i "s|^TELEGRAM_LOCAL_API_URL=.*|TELEGRAM_LOCAL_API_URL=\"${LOCAL_URL}\"|" "$ENV_FILE"
    else
        printf '\nTELEGRAM_LOCAL_API_URL="%s"\n' "$LOCAL_URL" >> "$ENV_FILE"
    fi
    echo "   TELEGRAM_LOCAL_API_URL=${LOCAL_URL}"
else
    echo "   backend/.env не найден — добавьте вручную: TELEGRAM_LOCAL_API_URL=\"${LOCAL_URL}\""
fi

echo "==> Перезапуск бэкенда"
systemctl restart mediabot 2>/dev/null || echo "   (systemd mediabot не найден — перезапустите бэкенд вручную)"

echo ""
echo "=================================================="
echo " ГОТОВО! Local Bot API Server запущен."
echo "   URL      : ${LOCAL_URL}"
echo "   Лимит    : отправка ботом файлов до 2 ГБ"
echo "   Логи     : docker logs telegram-bot-api -f"
echo "   Диск     : docker exec telegram-bot-api du -sh /var/lib/telegram-bot-api"
echo "=================================================="
