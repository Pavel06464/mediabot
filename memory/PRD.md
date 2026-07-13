# PRD — Media Post Bot (Telegraph)

## Problem Statement
Инструмент для создания постов Telegraph со вложенными медиа и публикации ссылки в Telegram-канале с предпросмотром. Понятный визуальный интерфейс, память ссылок на каждый пост. Эволюционировал из Telegram-бота в веб-дашборд (dashboard-only).

## User Choices (актуальные)
- Создание постов — через веб-дашборд (не через бота).
- Вход в дашборд — логин + пароль (JWT).
- Публикация в канал и настройка канала — из дашборда (бот-токен через httpx).
- Обложка/предпросмотр — пользователь отмечает любое фото (идёт первой в статье).
- Хранилище — Cloudflare R2 (https-ссылки → фото отображаются; файлы до 2 ГБ). Fallback: GridFS.

## Architecture
- Backend: FastAPI (порт 8001). JWT-auth (auth.py, bcrypt+PyJWT, seed admin из .env). 
- Хранилище: storage.py — R2 (boto3) если заданы R2_*, иначе MongoDB GridFS (`/api/media/{id}`, public).
- Telegraph: telegraph_service.py (async, аккаунт-токен в app_config), build_html использует прямые url блоков; обложка ставится первой.
- Telegram: telegram_api.py (httpx) — getChat (настройка канала) + sendMessage (публикация с предпросмотром). Bot polling (aiogram) отключён (ENABLE_BOT_POLLING=0), код сохранён.
- MongoDB: users, posts, app_config (channel + telegraph token), GridFS.
- Frontend: React + react-router. AuthContext (Bearer token в localStorage), Login, Dashboard (stats, таблица, публикация, удаление, настройка канала), PostEditor (блоки текст/фото/видео, порядок, обложка, загрузка).
- Deploy (HostVDS VPS): deploy_phase1.sh (полная установка), update.sh (обновление после git pull), deploy/ (systemd + nginx), setup_hostvds.sh (системные зависимости + swap).

## Implemented
- 2026-07-05: MVP Telegram-бот (aiogram) + Telegraph + GridFS + дашборд (открытый). Тесты iteration_1 (11/11 + frontend).
- 2026-07-05..13: Перенос на VPS HostVDS (скрипты, инструкция DEPLOYMENT_HOSTVDS.md). Поддержка Local Bot API Server + R2 в коде. Удалены внутренние пакеты (emergentintegrations, litellm) из requirements.
- 2026-07-13: Dashboard-only переработка — JWT-авторизация, редактор постов в дашборде (текст/фото/видео/порядок/обложка), загрузка медиа (R2/GridFS), публикация в канал + настройка канала из дашборда. Тесты iteration_2 (backend 28/28, frontend 100%).
- 2026-07-13: Редактор переработан в секции (Обложка/Описание/Фотографии/Видео) + drag-and-drop загрузка файлов из папки. Тесты iteration_3 (backend 29/29, frontend 100%). R2 на VPS проверен (токен + ключи + публичный доступ работают).
- 2026-07-13: Водяной знак на фото (Pillow, текст/логотип, позиция/размер/прозрачность, живое превью), шрифт DejaVu встроен в repo. Тесты iteration_4.
- 2026-07-13: Фикс большого предпросмотра в канале — publish шлёт обложку через sendPhoto (prefer_large_media не работает для telegra.ph). Пост хранит cover_url. Тесты iteration_5 (backend 44/44).
- 2026-06 (fork): Асинхронное создание постов. POST /api/posts/draft создаёт черновик-оболочку (status uploading/processing), возвращает {id, slots}. POST /api/posts/{id}/media/{idx} грузит слоты по одному (media_done/media_total), при заполнении атомарно (findOneAndUpdate) запускается _finalize_post → создаёт Telegraph-статью (cover_url+telegraph_url, status ready) и авто-публикует если publish_after+канал. Фронтенд: UploadContext.startJob (черновик→фоновая загрузка с onUploadProgress), Dashboard рендерит панель прогресса (upload-jobs) и поллит /posts каждые 2.5с. Фикс: Dashboard падал на telegraph_url.replace(null) для черновиков — теперь показывает «создаётся…», кнопка публикации задизейблена до готовности; статусы через STATUS_META. send_photo валидирует content-type (image/*) и размер (<10 МБ). Тесты iteration_6 (backend 50/50, frontend E2E 100%).
- 2026-06 (fork): Две отдельные Telegraph-статьи. _finalize_post/_do_publish разделяют медиа: одна статья со всеми фото (+текст, обложка первой), вторая со всеми видео. В канал уходит сообщение с двумя ссылками («📷 Фото: …», «🎬 Видео: …») через _publish_caption — показываются только те ссылки, для которых есть медиа; обложка/превью от фото-статьи. Пост хранит photos_url/photos_path/videos_url/videos_path; telegraph_url = основная (photos или videos). В таблице дашборда — одна основная ссылка. edit_post перерендерит обе статьи на месте. Легаси-посты (POST /posts) публикуются одной ссылкой (fallback). Проверено curl (фото+видео, только фото, только видео, правка) + pytest 69/69.
- 2026-06 (fork): Пакет доработок. (1) Фаза «Оформляю статью…» в панели прогресса — UploadContext ставит job.status=processing и поллит /posts/{id} до ready/failed. (2) Очистка объектов R2 при удалении поста — блоки хранят r2_key, пост хранит r2_keys[], delete_post вызывает storage.delete_file. (3) Файлы до 2 ГБ — видео стримятся в temp-файл (_stream_to_temp, чанки по 1 МБ) и грузятся в R2 (multipart boto3) без загрузки в RAM; nginx client_max_body_size=2100M + proxy_request_buffering off. (4) Редактирование постов — GET /posts/{id}/edit + PUT /posts/{id} (edit_page на месте, тот же URL), фронтенд EditPost.jsx на /edit/:id (заголовок/описание/подписи/выбор обложки), кнопка edit-{id} в Dashboard. (5) Валидация слотов — несовпадение типа файла и слота → 400, фото >25 МБ → 400 (вместо 500). (6) Форматирование текста — md_to_html (# H3, ## H4, > цитата, **жирный**, *курсив*, [текст](url)), MarkdownToolbar над описанием в редакторе и при правке. Тесты iteration_7 (backend 69/69, frontend E2E 100%).

## Deployment status (user VPS 94.183.178.153)
- Phase 1 (файлы до 20 МБ, GridFS) развёрнут и работал. 
- Требуется: новый токен BotFather (старый отозван), R2 Secret Access Key, обновление .env + update.sh для новой dashboard-only версии.

## Backlog / Next
- P1: Развернуть новую версию на VPS с R2 (ждём Secret Access Key + новый токен BotFather) — проверить реальную авто-публикацию с большим предпросмотром.
- P2: Стриминг фото в temp тоже (сейчас фото читается в RAM до проверки 25 МБ); проверка Content-Length до чтения.
- P2: Удаление/добавление медиа при редактировании поста (сейчас правятся только подписи/обложка/текст/заголовок).
- P2: Лог ошибок публикации, миграция on_event → lifespan, домен + HTTPS (certbot).
