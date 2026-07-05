import os
import uuid
import asyncio
import tempfile
import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LinkPreviewOptions,
)

from database import db, get_gridfs
from telegraph_service import create_post_page
import storage

logger = logging.getLogger("telegram_bot")

BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
LOCAL_API = os.environ.get("TELEGRAM_LOCAL_API_URL")  # напр. http://localhost:8081

bot: Bot | None = None
router = Router()


def _build_bot() -> Bot:
    kwargs = {"default": DefaultBotProperties(parse_mode=ParseMode.HTML)}
    if LOCAL_API:
        session = AiohttpSession(api=TelegramAPIServer.from_base(LOCAL_API, is_local=True))
        kwargs["session"] = session
        logger.info("Using Local Bot API Server at %s", LOCAL_API)
    return Bot(token=TOKEN, **kwargs)


class PostFSM(StatesGroup):
    title = State()
    content = State()


class ChannelFSM(StatesGroup):
    waiting = State()


# ---------- Keyboards ----------
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Создать пост", callback_data="menu:create")],
            [InlineKeyboardButton(text="📚 Мои посты", callback_data="menu:posts")],
            [InlineKeyboardButton(text="⚙️ Настройки канала", callback_data="menu:settings")],
            [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="menu:help")],
        ]
    )


def content_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готово — создать статью", callback_data="post:done")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="post:cancel")],
        ]
    )


def result_kb(post_id: str, has_channel: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_channel:
        rows.append([InlineKeyboardButton(text="📢 Опубликовать в канал", callback_data=f"publish:{post_id}")])
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb(has_channel: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔗 Указать / изменить канал", callback_data="set:channel")]]
    if has_channel:
        rows.append([InlineKeyboardButton(text="🗑 Удалить канал", callback_data="set:remove")])
    rows.append([InlineKeyboardButton(text="🏠 В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="menu:home")]]
    )


# ---------- Helpers ----------
async def _store_media(file_id: str, content_type: str, kind: str) -> dict:
    """Возвращает dict с 'url' (публичная ссылка на медиа) и опц. 'media_id' (для GridFS)."""
    file = await bot.get_file(file_id)

    if storage.r2_enabled():
        ext = "mp4" if kind == "video" else "jpg"
        key = f"{kind}/{uuid.uuid4()}.{ext}"
        if LOCAL_API:
            # при is_local=True file.file_path — путь к файлу на диске (общий том с API-сервером)
            url = await asyncio.to_thread(storage.upload_file, file.file_path, key, content_type)
        else:
            buf = await bot.download_file(file.file_path)
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.write(buf.read())
            tmp.close()
            try:
                url = await asyncio.to_thread(storage.upload_file, tmp.name, key, content_type)
            finally:
                os.unlink(tmp.name)
        return {"url": url}

    # Fallback: хранение в MongoDB GridFS, отдача через /api/media/{id}
    buf = await bot.download_file(file.file_path)
    data = buf.read()
    bucket = get_gridfs()
    oid = await bucket.upload_from_stream(
        f"{kind}_{file_id}", data, metadata={"content_type": content_type}
    )
    return {"media_id": str(oid), "url": f"{BASE_URL}/api/media/{oid}"}


async def get_user_channel(user_id: int):
    return await db.settings.find_one({"_id": user_id})


async def send_main_menu(target, text="Главное меню. Выберите действие:"):
    if isinstance(target, Message):
        await target.answer(text, reply_markup=main_menu_kb())
    else:
        await target.message.edit_text(text, reply_markup=main_menu_kb())


# ---------- Handlers ----------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Media Post Bot</b>\n\n"
        "Я собираю ваши текст, фото и видео в красивую статью Telegraph "
        "и выдаю ссылку с предпросмотром для публикации в канале.\n\n"
        "Выберите действие:",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    await send_main_menu(message)


@router.callback_query(F.data == "menu:home")
async def cb_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await send_main_menu(cb)
    await cb.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(cb: CallbackQuery):
    await cb.message.edit_text(
        "ℹ️ <b>Как это работает</b>\n\n"
        "1️⃣ «Создать пост» → введите заголовок.\n"
        "2️⃣ Присылайте текст, фото и видео в любом порядке — всё попадёт в статью.\n"
        "3️⃣ Нажмите «Готово» — бот создаст статью Telegraph и выдаст ссылку.\n"
        "4️⃣ Опубликуйте ссылку сами или дайте боту запостить её в ваш канал.\n\n"
        "⚙️ В «Настройках» укажите канал (бот должен быть его администратором).",
        reply_markup=back_menu_kb(),
    )
    await cb.answer()


# ----- Create post flow -----
@router.callback_query(F.data == "menu:create")
async def cb_create(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(PostFSM.title)
    await cb.message.edit_text(
        "📝 <b>Новый пост</b>\n\nВведите заголовок статьи одним сообщением:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="post:cancel")]]
        ),
    )
    await cb.answer()


@router.message(PostFSM.title, F.text)
async def fsm_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip(), blocks=[])
    await state.set_state(PostFSM.content)
    await message.answer(
        f"✅ Заголовок: <b>{message.text.strip()}</b>\n\n"
        "Теперь присылайте содержимое статьи:\n"
        "• 📝 текст\n• 🖼 фото\n• 🎬 видео\n\n"
        "Можно отправлять несколько сообщений подряд. "
        "Когда закончите — нажмите «Готово».",
        reply_markup=content_kb(),
    )


@router.message(PostFSM.content, F.photo)
async def fsm_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    blocks = data.get("blocks", [])
    media_id = await _store_media(message.photo[-1].file_id, "image/jpeg", "photo")
    blocks.append({"type": "photo", "caption": message.caption or "", **media_id})
    await state.update_data(blocks=blocks)
    await message.answer(f"🖼 Фото добавлено. Элементов: {len(blocks)}", reply_markup=content_kb())


@router.message(PostFSM.content, F.video)
async def fsm_video(message: Message, state: FSMContext):
    data = await state.get_data()
    blocks = data.get("blocks", [])
    media_id = await _store_media(message.video.file_id, message.video.mime_type or "video/mp4", "video")
    blocks.append({"type": "video", "caption": message.caption or "", **media_id})
    await state.update_data(blocks=blocks)
    await message.answer(f"🎬 Видео добавлено. Элементов: {len(blocks)}", reply_markup=content_kb())


@router.message(PostFSM.content, F.document)
async def fsm_document(message: Message, state: FSMContext):
    doc = message.document
    mime = doc.mime_type or ""
    if mime.startswith("image/") or mime.startswith("video/"):
        data = await state.get_data()
        blocks = data.get("blocks", [])
        kind = "photo" if mime.startswith("image/") else "video"
        media_id = await _store_media(doc.file_id, mime, kind)
        blocks.append({"type": kind, "caption": message.caption or "", **media_id})
        await state.update_data(blocks=blocks)
        await message.answer(f"📎 Медиа добавлено. Элементов: {len(blocks)}", reply_markup=content_kb())
    else:
        await message.answer("⚠️ Этот тип файла не поддерживается. Пришлите фото, видео или текст.")


@router.message(PostFSM.content, F.text)
async def fsm_text(message: Message, state: FSMContext):
    data = await state.get_data()
    blocks = data.get("blocks", [])
    blocks.append({"type": "text", "value": message.text})
    await state.update_data(blocks=blocks)
    await message.answer(f"📝 Текст добавлен. Элементов: {len(blocks)}", reply_markup=content_kb())


@router.callback_query(F.data == "post:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("❌ Создание поста отменено.", reply_markup=main_menu_kb())
    await cb.answer()


@router.callback_query(F.data == "post:done")
async def cb_done(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    title = data.get("title", "Без названия")
    blocks = data.get("blocks", [])
    if not blocks:
        await cb.answer("Добавьте хотя бы один элемент.", show_alert=True)
        return

    await cb.message.edit_text("⏳ Создаю статью Telegraph...")
    try:
        url, path = await create_post_page(title, blocks, BASE_URL)
    except Exception as e:
        logger.exception("Telegraph create failed")
        await cb.message.edit_text(f"❌ Ошибка при создании статьи: {e}", reply_markup=main_menu_kb())
        await state.clear()
        return

    media_ids = [b["media_id"] for b in blocks if b.get("media_id")]
    preview = next((b["value"] for b in blocks if b.get("type") == "text"), "")
    post_id = str(uuid.uuid4())
    doc = {
        "id": post_id,
        "user_id": cb.from_user.id,
        "user_name": cb.from_user.full_name,
        "title": title,
        "telegraph_url": url,
        "telegraph_path": path,
        "media_count": len(media_ids),
        "media_ids": media_ids,
        "block_count": len(blocks),
        "preview": preview[:200],
        "published": False,
        "channel_title": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.posts.insert_one(doc)
    await state.clear()

    channel = await get_user_channel(cb.from_user.id)
    await cb.message.edit_text(
        f"✅ <b>Статья создана!</b>\n\n"
        f"<b>{title}</b>\n"
        f"🔗 {url}\n\n"
        f"Скопируйте ссылку для публикации или нажмите кнопку ниже, "
        f"чтобы бот сам запостил её в канал с предпросмотром.",
        reply_markup=result_kb(post_id, bool(channel)),
        link_preview_options=LinkPreviewOptions(is_disabled=False, url=url, prefer_large_media=True),
    )
    await cb.answer("Готово!")


# ----- Publish -----
@router.callback_query(F.data.startswith("publish:"))
async def cb_publish(cb: CallbackQuery):
    post_id = cb.data.split(":", 1)[1]
    post = await db.posts.find_one({"id": post_id})
    if not post:
        await cb.answer("Пост не найден.", show_alert=True)
        return
    channel = await get_user_channel(cb.from_user.id)
    if not channel:
        await cb.answer("Сначала укажите канал в настройках.", show_alert=True)
        return
    try:
        await bot.send_message(
            chat_id=channel["channel_id"],
            text=f"<b>{post['title']}</b>\n\n{post['telegraph_url']}",
            link_preview_options=LinkPreviewOptions(
                is_disabled=False, url=post["telegraph_url"], prefer_large_media=True
            ),
        )
    except Exception as e:
        logger.exception("Publish failed")
        await cb.answer(f"Ошибка публикации: {e}", show_alert=True)
        return

    await db.posts.update_one(
        {"id": post_id},
        {"$set": {"published": True, "channel_title": channel.get("channel_title")}},
    )
    await cb.message.edit_text(
        f"📢 Опубликовано в «{channel.get('channel_title')}»!\n\n"
        f"<b>{post['title']}</b>\n🔗 {post['telegraph_url']}",
        reply_markup=main_menu_kb(),
    )
    await cb.answer("Опубликовано ✅")


# ----- My posts -----
@router.callback_query(F.data == "menu:posts")
async def cb_posts(cb: CallbackQuery):
    posts = (
        await db.posts.find({"user_id": cb.from_user.id})
        .sort("created_at", -1)
        .to_list(10)
    )
    if not posts:
        await cb.message.edit_text("📭 У вас пока нет созданных постов.", reply_markup=back_menu_kb())
        await cb.answer()
        return
    lines = ["📚 <b>Ваши последние посты:</b>\n"]
    for p in posts:
        status = "📢" if p.get("published") else "📝"
        lines.append(f"{status} <a href=\"{p['telegraph_url']}\">{p['title']}</a>")
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=back_menu_kb(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await cb.answer()


# ----- Settings / channel -----
@router.callback_query(F.data == "menu:settings")
async def cb_settings(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    channel = await get_user_channel(cb.from_user.id)
    if channel:
        text = (
            f"⚙️ <b>Настройки канала</b>\n\n"
            f"Текущий канал: <b>{channel.get('channel_title')}</b>\n"
            f"ID: <code>{channel.get('channel_id')}</code>"
        )
    else:
        text = (
            "⚙️ <b>Настройки канала</b>\n\n"
            "Канал не указан. Добавьте бота администратором в канал "
            "(с правом публикации), затем укажите его здесь."
        )
    await cb.message.edit_text(text, reply_markup=settings_kb(bool(channel)))
    await cb.answer()


@router.callback_query(F.data == "set:remove")
async def cb_remove_channel(cb: CallbackQuery):
    await db.settings.delete_one({"_id": cb.from_user.id})
    await cb.message.edit_text("🗑 Канал удалён.", reply_markup=main_menu_kb())
    await cb.answer()


@router.callback_query(F.data == "set:channel")
async def cb_set_channel(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ChannelFSM.waiting)
    await cb.message.edit_text(
        "🔗 Пришлите <b>@username</b> канала, его ID (вида <code>-100...</code>) "
        "или просто перешлите любое сообщение из канала.\n\n"
        "⚠️ Бот должен быть администратором канала.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🏠 В меню", callback_data="menu:home")]]
        ),
    )
    await cb.answer()


@router.message(ChannelFSM.waiting)
async def fsm_channel(message: Message, state: FSMContext):
    identifier = None
    if message.forward_from_chat:
        identifier = message.forward_from_chat.id
    elif message.text:
        identifier = message.text.strip()

    if not identifier:
        await message.answer("Не удалось распознать канал. Пришлите @username, ID или пересланное сообщение.")
        return

    try:
        chat = await bot.get_chat(identifier)
    except Exception as e:
        await message.answer(
            f"❌ Не удалось получить канал: {e}\n"
            "Проверьте, что бот добавлен администратором."
        )
        return

    await db.settings.update_one(
        {"_id": message.from_user.id},
        {"$set": {"channel_id": chat.id, "channel_title": chat.title or chat.full_name or str(chat.id)}},
        upsert=True,
    )
    await state.clear()
    await message.answer(
        f"✅ Канал сохранён: <b>{chat.title}</b>", reply_markup=main_menu_kb()
    )


async def start_bot():
    global bot
    if not TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set, bot not started")
        return
    bot = _build_bot()
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Telegram bot polling started")
        await dp.start_polling(bot)
    except Exception:
        logger.exception("Bot polling crashed")
