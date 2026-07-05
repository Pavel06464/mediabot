# 🚀 Развёртывание Media Post Bot на HostVDS

Полная инструкция по переносу бота (aiogram + FastAPI + MongoDB), включая **Local Bot API Server** для файлов до 2 ГБ и хранилище **Cloudflare R2**.

---

## 0. Что понадобится заранее

| Что | Где взять |
|-----|-----------|
| VPS на HostVDS | Рекомендую **≥ 4 ГБ RAM / ≥ 80 ГБ NVMe**, ОС **Ubuntu 24.04 LTS** |
| Bot Token | @BotFather (уже есть) |
| **api_id + api_hash** | https://my.telegram.org → «API development tools» (⚠️ обязательно для Local Bot API Server) |
| Cloudflare R2 | Account ID, Access Key ID, Secret Access Key, имя бакета |
| Домен (опционально) | для дашборда/публичных ссылок |

> ⚠️ Важно: чтобы бот принимал файлы **до 2 ГБ**, нужен собственный Local Bot API Server. Ему нужны `api_id` и `api_hash` (не только токен бота).

---

## 1. Первичная настройка сервера

Подключитесь по SSH (данные придут от HostVDS после создания VPS):

```bash
ssh root@ВАШ_IP
```

Обновите систему и создайте пользователя:

```bash
apt update && apt upgrade -y
adduser deploy
usermod -aG sudo deploy
# дальше работаем под deploy
su - deploy
```

### Swap (важно для сборки/буфера больших файлов)

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Файрвол

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

---

## 2. Установка зависимостей

```bash
sudo apt install -y python3-venv python3-pip git nginx curl gnupg
```

### MongoDB (локально)

```bash
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt update
sudo apt install -y mongodb-org
sudo systemctl enable --now mongod
```

### Docker (для Local Bot API Server)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
newgrp docker   # применить группу без релогина
```

---

## 3. Local Bot API Server (файлы до 2 ГБ)

Запускаем официальный сервер в Docker (образ `aiogram/telegram-bot-api`):

```bash
docker run -d --name telegram-bot-api \
  --restart unless-stopped \
  -p 8081:8081 \
  -e TELEGRAM_API_ID=ВАШ_API_ID \
  -e TELEGRAM_API_HASH=ВАШ_API_HASH \
  -e TELEGRAM_LOCAL=1 \
  -v telegram-bot-api-data:/var/lib/telegram-bot-api \
  aiogram/telegram-bot-api:latest
```

Проверка:

```bash
docker logs telegram-bot-api --tail 20
curl http://localhost:8081   # должен отвечать
```

> `TELEGRAM_LOCAL=1` включает режим `--local`: снимает лимит скачивания 20 МБ → до 2 ГБ, а `getFile` возвращает путь к файлу на диске сервера.

---

## 4. Код бота: поддержка Local API + R2 уже встроена ✅

> Ничего вручную редактировать в `.py` НЕ нужно — поддержка Local Bot API Server и Cloudflare R2 уже реализована в коде (`storage.py`, `telegram_bot.py`, `telegraph_service.py`). Всё включается через переменные окружения в `backend/.env` (шаг 6):
> - если заданы `R2_*` — медиа грузится в R2;
> - если заданы `R2_*` не полностью — медиа хранится в MongoDB GridFS (fallback);
> - если задан `TELEGRAM_LOCAL_API_URL` — бот работает через Local Bot API Server (файлы до 2 ГБ).

### Установка окружения бота

```bash
cd ~/app/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> ⚠️ Блоки Python-кода в этом файле — это описание того, ЧТО уже сделано в репозитории. Их НЕ нужно вставлять в терминал.

---

## 5. Настройка Cloudflare R2

1. Cloudflare Dashboard → **R2** → Create bucket (напр. `mediabot`).
2. **Manage R2 API Tokens** → Create → получите **Access Key ID** и **Secret Access Key**.
3. Endpoint: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`
4. Публичный доступ: в настройках бакета включите **Public Development URL** (`https://pub-xxxx.r2.dev`) или подключите свой домен (**Custom Domain**) — этот адрес пойдёт в `R2_PUBLIC_BASE`.

---

## 6. Переменные окружения

`~/app/backend/.env`:

```
MONGO_URL="mongodb://localhost:27017"
DB_NAME="mediabot"
CORS_ORIGINS="*"
TELEGRAM_BOT_TOKEN="ВАШ_ТОКЕН"
TELEGRAM_LOCAL_API_URL="http://localhost:8081"
PUBLIC_BASE_URL="https://ваш-домен.ru"

R2_ENDPOINT="https://<ACCOUNT_ID>.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID="..."
R2_SECRET_ACCESS_KEY="..."
R2_BUCKET="mediabot"
R2_PUBLIC_BASE="https://pub-xxxx.r2.dev"
```

---

## 7. Автозапуск бэкенда (systemd)

`sudo nano /etc/systemd/system/mediabot.service`:

```ini
[Unit]
Description=Media Post Bot (FastAPI + aiogram)
After=network.target mongod.service docker.service

[Service]
User=deploy
WorkingDirectory=/home/deploy/app/backend
ExecStart=/home/deploy/app/backend/venv/bin/uvicorn server:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mediabot
sudo systemctl status mediabot        # проверка
journalctl -u mediabot -f             # логи в реальном времени
```

---

## 8. Фронтенд (дашборд)

```bash
# установка Node.js LTS + yarn
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g yarn

cd ~/app/frontend
# в .env указать боевой backend URL:
#   REACT_APP_BACKEND_URL=https://ваш-домен.ru
yarn install
yarn build      # соберёт статику в build/
```

---

## 9. Nginx (домен + HTTPS)

`sudo nano /etc/nginx/sites-available/mediabot`:

```nginx
server {
    server_name ваш-домен.ru;

    # API → FastAPI
    location /api/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 2100M;    # если оставляете загрузку через backend
    }

    # Дашборд (статика React)
    location / {
        root /home/deploy/app/frontend/build;
        try_files $uri /index.html;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/mediabot /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# бесплатный SSL
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d ваш-домен.ru
```

---

## 10. Проверка

1. `journalctl -u mediabot -f` — видно `Telegram bot polling started`.
2. Напишите боту `/start` → пройдите сценарий создания поста.
3. Отправьте большое видео (до 2 ГБ) — должно загрузиться (спасибо Local API Server).
4. Откройте `https://ваш-домен.ru` — дашборд с историей постов.
5. Проверьте, что файл открывается по R2-ссылке.

---

## 11. Обслуживание

**Бэкап MongoDB (cron, ежедневно):**
```bash
mongodump --db mediabot --out ~/backups/$(date +\%F)
```

**Обновление кода:**
```bash
cd ~/app && git pull
cd backend && source venv/bin/activate && pip install -r requirements.txt
sudo systemctl restart mediabot
cd ../frontend && yarn install && yarn build
```

**Мониторинг места (важно — буфер больших файлов):**
```bash
df -h
docker exec telegram-bot-api du -sh /var/lib/telegram-bot-api
```
Local API Server чистит кэш файлов сам (обычно ~1–25 ч), но при активной работе следите за диском.

---

## ⚠️ Частые проблемы

| Симптом | Причина / решение |
|---------|-------------------|
| `file is too big` | Не подключён Local API Server или `TELEGRAM_LOCAL_API_URL` не задан |
| `Unauthorized` у Local API | Неверные `api_id` / `api_hash` |
| Файл не читается по `file_path` | При `is_local=True` это путь на диске Docker-контейнера — читайте через тот же volume, либо запускайте бот и API-сервер с общим томом |
| R2 `AccessDenied` | Проверьте ключи и endpoint, регион `auto` |
| Картинки в статье не грузятся | `R2_PUBLIC_BASE` не публичный — включите Public URL / Custom Domain у бакета |

---

## 💡 Про общий диск с Local API Server

Так как `getFile` возвращает путь **внутри контейнера** telegram-bot-api, для чтения файла ботом смонтируйте тот же volume и в окружение бота, либо запускайте оба сервиса в docker-compose с общим `volumes`. Альтернатива — раздать `/var/lib/telegram-bot-api` по http внутри localhost и качать оттуда. Простейший путь: **docker-compose**, где бот и API-сервер делят том `telegram-bot-api-data`.

Готов подготовить `docker-compose.yml` для варианта «бот + Local API Server в одном стеке с общим томом», если выберете такой путь — так проще всего с доступом к файлам.
