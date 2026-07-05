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

## 4. Код бота: изменения для Local API Server + R2

### 4.1. Получаем код

Скачайте код из Emergent (кнопка «Download code» / push в GitHub) и залейте на сервер:

```bash
cd ~
git clone ВАШ_РЕПОЗИТОРИЙ app   # или scp -r локально
cd ~/app/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install boto3   # для R2, если ещё не добавлен
```

### 4.2. Указать боту Local API Server (`telegram_bot.py`)

В функции `start_bot()` создание `Bot` заменить на использование локального сервера:

```python
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

LOCAL_API = os.environ.get("TELEGRAM_LOCAL_API_URL")  # напр. http://localhost:8081

def _build_bot():
    kwargs = {"default": DefaultBotProperties(parse_mode=ParseMode.HTML)}
    if LOCAL_API:
        session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_API, is_local=True))
        kwargs["session"] = session
    return Bot(token=TOKEN, **kwargs)
```

> `is_local=True` говорит aiogram, что `getFile` вернёт локальный путь к файлу (его читаем напрямую с диска, а не качаем по URL).

### 4.3. Загрузка медиа в Cloudflare R2 вместо GridFS

Создайте `backend/storage.py`:

```python
import os, boto3
from botocore.config import Config

_s3 = None

def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT"],          # https://<accountid>.r2.cloudflarestorage.com
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _s3

def upload_file(local_path: str, key: str, content_type: str) -> str:
    # multipart автоматически включается boto3 для больших файлов
    _client().upload_file(
        local_path, os.environ["R2_BUCKET"], key,
        ExtraArgs={"ContentType": content_type},
    )
    # публичный URL через ваш public-домен R2 или R2.dev
    return f"{os.environ['R2_PUBLIC_BASE'].rstrip('/')}/{key}"
```

И в `_store_media` (`telegram_bot.py`) вместо GridFS:

```python
async def _store_media(file_id, content_type, kind):
    file = await bot.get_file(file_id)
    # при is_local=True file.file_path — это путь на диске Local API Server
    local_path = file.file_path
    import uuid
    ext = "mp4" if kind == "video" else "jpg"
    key = f"{kind}/{uuid.uuid4()}.{ext}"
    url = upload_file(local_path, key, content_type)  # вынести в executor при больших файлах
    return url   # теперь храним прямой URL, а не media_id
```

> При переходе на прямые URL обновите `telegraph_service.build_html` — используйте `b["url"]` напрямую вместо построения `/api/media/{id}`. GridFS-эндпоинт `/api/media` можно оставить для обратной совместимости или удалить.

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
