#!/usr/bin/env python3
# coding: utf-8

import os
import logging
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Union

from aiogram import Bot, Dispatcher, executor, types

# ================== НАСТРОЙКИ ==================

BOT_TOKEN = os.getenv("BOT_TOKEN", "123:ABC-DEF123456")         # !!! ЗАМЕНИ !!!
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "abc123@ABC123")         # !!! ЗАМЕНИ !!!
DB_PATH = os.getenv("DB_PATH", "projects.db")
FILES_CHANNEL_ID = int(os.getenv("FILES_CHANNEL_ID", "-123123123"))        # ID закрытого канала или 0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)

# Кто сейчас в админке
admin_sessions: set[int] = set()
# Состояния админов
admin_states: Dict[int, Dict[str, Any]] = {}


# ================== БАЗА ДАННЫХ ==================


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    con = get_db()
    cur = con.cursor()

    # категории
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # подкатегории
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subcategories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE,
            UNIQUE(category_id, name)
        )
    """)

    # проекты
    cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subcategory_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            media TEXT,
            link TEXT,
            is_published INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(subcategory_id) REFERENCES subcategories(id) ON DELETE CASCADE
        )
    """)

    # файлы проекта
    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            file_name TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)

    # лог действий
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT,
            details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.commit()
    con.close()


def log_action(user_id: int, username: str, action: str, details: str = ""):
    try:
        con = get_db()
        cur = con.cursor()
        cur.execute(
            "INSERT INTO audit_log(user_id, username, action, details) VALUES (?, ?, ?, ?)",
            (user_id, username, action, details),
        )
        con.commit()
    except Exception as e:
        logger.error(f"Error logging action: {e}")
    finally:
        con.close()


# ---------- категории ----------

def add_category(name: str) -> int:
    con = get_db()
    cur = con.cursor()
    cur.execute("INSERT INTO categories(name) VALUES (?)", (name.strip(),))
    con.commit()
    cid = cur.lastrowid
    con.close()
    return cid


def get_categories() -> List[Tuple[int, str]]:
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id, name FROM categories ORDER BY LOWER(name)")
    rows = cur.fetchall()
    con.close()
    return rows


def get_category(cid: int) -> Optional[Tuple[int, str]]:
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT id, name FROM categories WHERE id=?", (cid,))
    row = cur.fetchone()
    con.close()
    return row


def rename_category(cid: int, new_name: str):
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE categories SET name=? WHERE id=?", (new_name.strip(), cid))
    con.commit()
    con.close()


def delete_category(cid: int) -> bool:
    """
    Удаляем категорию только если нет подкатегорий.
    Возвращаем True, если удалено; False, если есть подкатегории.
    """
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM subcategories WHERE category_id=?", (cid,))
    count = cur.fetchone()[0]
    if count > 0:
        con.close()
        return False
    cur.execute("DELETE FROM categories WHERE id=?", (cid,))
    con.commit()
    con.close()
    return True


# ---------- подкатегории ----------

def add_subcategory(category_id: int, name: str) -> int:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO subcategories(category_id, name) VALUES (?, ?)",
        (category_id, name.strip()),
    )
    con.commit()
    sid = cur.lastrowid
    con.close()
    return sid


def get_subcategories_by_category(category_id: int) -> List[Tuple[int, str]]:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, name FROM subcategories WHERE category_id=? ORDER BY LOWER(name)",
        (category_id,),
    )
    rows = cur.fetchall()
    con.close()
    return rows


def get_subcategory(sid: int) -> Optional[Tuple[int, int, str]]:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, category_id, name FROM subcategories WHERE id=?",
        (sid,),
    )
    row = cur.fetchone()
    con.close()
    return row


def rename_subcategory(sid: int, new_name: str):
    con = get_db()
    cur = con.cursor()
    cur.execute("UPDATE subcategories SET name=? WHERE id=?", (new_name.strip(), sid))
    con.commit()
    con.close()


def delete_subcategory(sid: int) -> bool:
    """
    Удаляем подкатегорию только если в ней нет проектов.
    """
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM projects WHERE subcategory_id=?", (sid,))
    count = cur.fetchone()[0]
    if count > 0:
        con.close()
        return False
    cur.execute("DELETE FROM subcategories WHERE id=?", (sid,))
    con.commit()
    con.close()
    return True


# ---------- проекты ----------

def add_project(subcategory_id: int, title: str, description: str, media: str, link: str) -> int:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO projects(subcategory_id, title, description, media, link)
        VALUES (?, ?, ?, ?, ?)
        """,
        (subcategory_id, title.strip(), description or "", media or "", link or ""),
    )
    con.commit()
    pid = cur.lastrowid
    con.close()
    return pid


def get_project(pid: int) -> Optional[Tuple]:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, subcategory_id, title, description, media, link, is_published
        FROM projects
        WHERE id=?
        """,
        (pid,),
    )
    row = cur.fetchone()
    con.close()
    return row


def get_projects_by_subcategory(subcategory_id: int, published_only: bool = True) -> List[Tuple]:
    con = get_db()
    cur = con.cursor()
    if published_only:
        cur.execute(
            """
            SELECT id, title, description, media, link
            FROM projects
            WHERE subcategory_id=? AND is_published=1
            ORDER BY created_at DESC
            """,
            (subcategory_id,),
        )
    else:
        cur.execute(
            """
            SELECT id, title, description, media, link, is_published
            FROM projects
            WHERE subcategory_id=?
            ORDER BY created_at DESC
            """,
            (subcategory_id,),
        )
    rows = cur.fetchall()
    con.close()
    return rows


def update_project(pid: int, title: str, description: str, media: str, link: str):
    con = get_db()
    cur = con.cursor()
    cur.execute(
        """
        UPDATE projects
        SET title=?, description=?, media=?, link=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (title.strip(), description or "", media or "", link or "", pid),
    )
    con.commit()
    con.close()


def toggle_project_visibility(pid: int) -> int:
    con = get_db()
    cur = con.cursor()
    cur.execute("SELECT is_published FROM projects WHERE id=?", (pid,))
    row = cur.fetchone()
    if not row:
        con.close()
        raise ValueError("Project not found")
    new_val = 0 if row[0] else 1
    cur.execute(
        "UPDATE projects SET is_published=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (new_val, pid),
    )
    con.commit()
    con.close()
    return new_val


def delete_project(pid: int):
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM projects WHERE id=?", (pid,))
    con.commit()
    con.close()


# ---------- файлы проектов ----------

def add_project_file(project_id: int, file_id: str, file_name: str = "") -> int:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO project_files(project_id, file_id, file_name) VALUES (?, ?, ?)",
        (project_id, file_id, file_name),
    )
    con.commit()
    fid = cur.lastrowid
    con.close()
    return fid


def get_project_files(project_id: int) -> List[Tuple]:
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT id, file_id, file_name, created_at FROM project_files WHERE project_id=? ORDER BY created_at DESC",
        (project_id,),
    )
    rows = cur.fetchall()
    con.close()
    return rows


def delete_project_file(row_id: int):
    con = get_db()
    cur = con.cursor()
    cur.execute("DELETE FROM project_files WHERE id=?", (row_id,))
    con.commit()
    con.close()


# ---------- статистика ----------

def get_statistics():
    con = get_db()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM projects")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM projects WHERE is_published=1")
    published = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM audit_log WHERE date(created_at)=date('now')")
    today_actions = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT user_id) FROM audit_log WHERE date(created_at)=date('now')")
    unique_today = cur.fetchone()[0]

    con.close()
    return {
        "total_projects": total,
        "published_projects": published,
        "today_actions": today_actions,
        "unique_users_today": unique_today,
    }


# ================== КЛАВИАТУРЫ ==================


def main_menu_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📁 Мои проекты")
    kb.add("ℹ️ Обо мне", "✉️ Контакты")
    return kb


def admin_main_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📂 Категории", callback_data="admin_cats"),
        types.InlineKeyboardButton("🗂 Подкатегории", callback_data="admin_subcats"),
    )
    kb.add(
        types.InlineKeyboardButton("🧩 Проекты", callback_data="admin_projects"),
        types.InlineKeyboardButton("➕ Добавить проект", callback_data="admin_add_project"),
    )
    kb.add(
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        types.InlineKeyboardButton("📝 Логи", callback_data="admin_logs"),
    )
    kb.add(types.InlineKeyboardButton("🚪 Выход", callback_data="admin_exit"))
    return kb


def admin_back_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
    return kb


# ================== ПОЛЬЗОВАТЕЛЬСКАЯ ЧАСТЬ ==================


@dp.message_handler(commands=["start", "help"])
async def cmd_start(message: types.Message):
    init_db()
    username = message.from_user.username or str(message.from_user.id)
    log_action(message.from_user.id, username, "start")
    text = (
        "Привет! Это мой бот-портфолио.\n\n"
        "Здесь можно посмотреть мои проекты: Telegram-боты, игровые моды, плагины и многое другое.\n\n"
        "Выберите раздел в меню ниже 👇"
    )
    await message.answer(text, reply_markup=main_menu_kb())


@dp.message_handler(lambda m: m.text == "ℹ️ Обо мне")
async def about_me(message: types.Message):
    text = (
        "👋 <b>Привет!</b>\n\n"
        "Я независимый разработчик.\n"
        "Делаю Telegram-ботов, игровые плагины и моды (CS 1.6 / CS2 / HNS), "
        "настраиваю Linux/VDS и игровые серверы.\n\n"
        "<b>Навыки:</b>\n"
        "– Telegram-боты (Python, aiogram)\n"
        "– CS 1.6 / CS2 — плагины, моды, системы магазинов, прыжков, ножей с атрибутами\n"
        "– Настройка серверов (HLDS/SRCDS, Linux, VDS)\n"
        "– Веб-проекты и базы данных\n\n"
        "Примеры работ в разделе <b>Мои проекты</b>."
    )
    await message.answer(text)


@dp.message_handler(lambda m: m.text == "✉️ Контакты")
async def contacts(message: types.Message):
    text = (
        "<b>Контакты:</b>\n\n"
        "Telegram: @cultura19\n"
        "Email: sharlay1337@gmail.com\n"
        "Сайт: offline\n"
    )
    await message.answer(text)


@dp.message_handler(lambda m: m.text == "📁 Мои проекты")
async def my_projects(message: types.Message):
    # Список категорий, в которых есть опубликованные проекты
    con = get_db()
    cur = con.cursor()
    cur.execute("""
        SELECT DISTINCT c.id, c.name
        FROM categories c
        JOIN subcategories s ON s.category_id = c.id
        JOIN projects p ON p.subcategory_id = s.id
        WHERE p.is_published=1
        ORDER BY LOWER(c.name)
    """)
    cats = cur.fetchall()
    con.close()

    if not cats:
        await message.answer("Пока нет опубликованных проектов.")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for cid, name in cats:
        title = name
        kb.add(types.InlineKeyboardButton(f"📂 {title}", callback_data=f"user_cat:{cid}"))

    text = "📁 <b>Мои проекты</b>\n\nВыберите категорию:"
    await message.answer(text, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("user_cat:"))
async def user_cat(call: types.CallbackQuery):
    from aiogram.utils.exceptions import BadRequest

    cid = int(call.data.split(":", 1)[1])
    cat = get_category(cid)
    if not cat:
        await call.answer("Категория не найдена.", show_alert=True)
        return

    _, cat_name = cat

    subcats = get_subcategories_by_category(cid)
    if not subcats:
        await call.answer("В этой категории пока нет подкатегорий.", show_alert=True)
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for sid, sname in subcats:
        kb.add(types.InlineKeyboardButton(f"🗂 {sname}", callback_data=f"user_subcat:{sid}"))

    kb.add(types.InlineKeyboardButton("⬅️ Назад к категориям", callback_data="user_back_cats"))

    text = f"📂 <b>{cat_name}</b>\n\nВыберите подкатегорию:"

    # edit_text/edit_caption
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except BadRequest:
        await call.message.edit_caption(caption=text, reply_markup=kb)

    await call.answer()



@dp.callback_query_handler(lambda c: c.data == "user_back_cats")
async def user_back_cats(call: types.CallbackQuery):
    from aiogram.utils.exceptions import BadRequest

    con = get_db()
    cur = con.cursor()
    cur.execute("""
        SELECT DISTINCT c.id, c.name
        FROM categories c
        JOIN subcategories s ON s.category_id = c.id
        JOIN projects p ON p.subcategory_id = s.id
        WHERE p.is_published=1
        ORDER BY LOWER(c.name)
    """)
    cats = cur.fetchall()
    con.close()

    if not cats:
        try:
            await call.message.edit_text("Пока нет опубликованных проектов.")
        except BadRequest:
            await call.message.edit_caption("Пока нет опубликованных проектов.")
        await call.answer()
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for cid, name in cats:
        kb.add(types.InlineKeyboardButton(f"📂 {name}", callback_data=f"user_cat:{cid}"))

    text = "📁 <b>Мои проекты</b>\n\nВыберите категорию:"

    try:
        await call.message.edit_text(text, reply_markup=kb)
    except BadRequest:
        await call.message.edit_caption(caption=text, reply_markup=kb)

    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("user_subcat:"))
async def user_subcat(call: types.CallbackQuery):
    from aiogram.utils.exceptions import BadRequest

    sid = int(call.data.split(":", 1)[1])
    subcat = get_subcategory(sid)
    if not subcat:
        await call.answer("Подкатегория не найдена.", show_alert=True)
        return
    _, cid, sname = subcat
    cat = get_category(cid)
    cat_name = cat[1] if cat else "?"

    projects = get_projects_by_subcategory(sid, published_only=True)
    if not projects:
        await call.answer("В этой подкатегории пока нет проектов.", show_alert=True)
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for pid, title, description, media, link in projects:
        short = (description or "").strip().replace("\n", " ")
        if len(short) > 40:
            short = short[:37] + "..."
        text_btn = title if not short else f"{title} — {short}"
        kb.add(types.InlineKeyboardButton(f"🧩 {text_btn}", callback_data=f"user_proj:{pid}"))

    kb.add(types.InlineKeyboardButton("⬅️ Назад к подкатегориям", callback_data=f"user_cat:{cid}"))

    text = f"📂 <b>{cat_name}</b> → 🗂 <b>{sname}</b>\n\nВыберите проект:"

    # --- ВАЖНО: универсальная обработка edit_text/edit_caption ---
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except BadRequest:
        await call.message.edit_caption(caption=text, reply_markup=kb)

    await call.answer()



async def send_project_card(chat_id: int, pid: int):
    project = get_project(pid)
    if not project:
        await bot.send_message(chat_id, "Проект не найден.")
        return

    pid, subcat_id, title, description, media, link, is_published = project
    subcat = get_subcategory(subcat_id)
    if subcat:
        _, cid, sub_name = subcat
        cat = get_category(cid)
        cat_name = cat[1] if cat else "?"
        cat_line = f"{cat_name} → {sub_name}"
    else:
        cat_line = "—"

    files = get_project_files(pid)

    kb = types.InlineKeyboardMarkup(row_width=2)
    if files:
        kb.add(types.InlineKeyboardButton("📁 Файлы проекта", callback_data=f"proj_files:{pid}"))
    if link:
        kb.add(types.InlineKeyboardButton("🌐 Ссылка", url=link))
    kb.add(types.InlineKeyboardButton("⬅️ В проекты", callback_data=f"user_subcat:{subcat_id}"))

    text = (
        f"🧩 <b>{title}</b>\n"
        f"📂 <i>{cat_line}</i>\n\n"
        f"📄 <b>Описание:</b>\n{description or 'Описание пока не добавлено.'}"
    )

    try:
        if media:
            await bot.send_photo(chat_id, media, caption=text, reply_markup=kb)
        else:
            await bot.send_message(chat_id, text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error sending project card: {e}")
        await bot.send_message(chat_id, text, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("user_proj:"))
async def user_proj(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    try:
        await call.message.delete()
    except Exception:
        pass
    await send_project_card(call.message.chat.id, pid)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("proj_files:"))
async def user_proj_files(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    files = get_project_files(pid)
    if not files:
        await call.answer("Файлы для этого проекта не найдены.", show_alert=True)
        return
    await call.answer()
    for row_id, file_id, file_name, created_at in files:
        try:
            await bot.send_document(
                call.message.chat.id,
                file_id,
                caption=file_name or "Файл проекта",
            )
        except Exception as e:
            logger.error(f"Error sending file {row_id}: {e}")


# ================== АДМИНКА ==================


@dp.message_handler(commands=["admin"])
async def cmd_admin(message: types.Message):
    args = message.get_args()
    if not args:
        await message.answer("Для входа в админку используйте: <code>/admin &lt;пароль&gt;</code>")
        return

    if args.strip() != ADMIN_PASSWORD:
        username = message.from_user.username or str(message.from_user.id)
        log_action(message.from_user.id, username, "admin_login_failed")
        await message.answer("❌ Неверный пароль.")
        return

    admin_sessions.add(message.from_user.id)
    username = message.from_user.username or str(message.from_user.id)
    log_action(message.from_user.id, username, "admin_login_success")

    await show_admin_main_menu(message)


async def show_admin_main_menu(message_or_call: Union[types.Message, types.CallbackQuery]):
    stats = get_statistics()
    text = (
        "👑 <b>Панель администратора</b>\n\n"
        f"📁 Проектов: {stats['total_projects']} (опубликовано: {stats['published_projects']})\n"
        f"📝 Действий сегодня: {stats['today_actions']}\n"
        f"👥 Уникальных пользователей сегодня: {stats['unique_users_today']}\n\n"
        "Выберите действие:"
    )
    kb = admin_main_menu_kb()
    if isinstance(message_or_call, types.Message):
        await message_or_call.answer(text, reply_markup=kb)
    else:
        await message_or_call.message.edit_text(text, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "admin_back")
async def admin_back(call: types.CallbackQuery):
    # сбросить состояния (кроме add_file, если захочешь оставить — можно усложнить)
    state = admin_states.get(call.from_user.id)
    if state and state.get("mode") not in ("add_file",):
        admin_states.pop(call.from_user.id, None)
    await show_admin_main_menu(call)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data == "admin_exit")
async def admin_exit(call: types.CallbackQuery):
    admin_sessions.discard(call.from_user.id)
    admin_states.pop(call.from_user.id, None)
    username = call.from_user.username or str(call.from_user.id)
    log_action(call.from_user.id, username, "admin_logout")
    await call.message.edit_text("✅ Вы вышли из админки.")
    await call.answer()


# ---------- категории в админке ----------


@dp.callback_query_handler(lambda c: c.data == "admin_cats")
async def admin_cats(call: types.CallbackQuery):
    cats = get_categories()
    text_lines = ["📂 <b>Категории:</b>\n"]
    kb = types.InlineKeyboardMarkup(row_width=2)
    for cid, name in cats:
        text_lines.append(f"• <code>{cid}</code> — {name}")
        kb.add(
            types.InlineKeyboardButton(f"✏ {name}", callback_data=f"admin_cat_edit:{cid}")
        )
    kb.add(types.InlineKeyboardButton("➕ Добавить категорию", callback_data="admin_cat_add"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))

    if not cats:
        text_lines.append("<i>Категорий пока нет.</i>")

    await call.message.edit_text("\n".join(text_lines), reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data == "admin_cat_add")
async def admin_cat_add(call: types.CallbackQuery):
    admin_states[call.from_user.id] = {
        "mode": "cat_add",
    }
    await call.message.edit_text(
        "📂 Отправьте <b>название новой категории</b>:",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_cat_edit:"))
async def admin_cat_edit(call: types.CallbackQuery):
    cid = int(call.data.split(":", 1)[1])
    cat = get_category(cid)
    if not cat:
        await call.answer("Категория не найдена.", show_alert=True)
        return

    _, name = cat
    text = (
        f"📂 <b>Категория #{cid}</b>\n"
        f"Название: <b>{name}</b>\n\n"
        "Выберите действие:"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✏ Переименовать", callback_data=f"admin_cat_rename:{cid}"),
        types.InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_cat_delete:{cid}"),
    )
    kb.add(
        types.InlineKeyboardButton("🗂 Подкатегории", callback_data=f"admin_subcats_cat:{cid}"),
    )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_cats"))

    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_cat_rename:"))
async def admin_cat_rename(call: types.CallbackQuery):
    cid = int(call.data.split(":", 1)[1])
    if not get_category(cid):
        await call.answer("Категория не найдена.", show_alert=True)
        return
    admin_states[call.from_user.id] = {"mode": "cat_rename", "category_id": cid}
    await call.message.edit_text(
        "✏ Отправьте <b>новое название</b> категории:",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_cat_delete:"))
async def admin_cat_delete(call: types.CallbackQuery):
    cid = int(call.data.split(":", 1)[1])
    cat = get_category(cid)
    if not cat:
        await call.answer("Категория не найдена.", show_alert=True)
        return
    _, name = cat
    if not delete_category(cid):
        await call.answer("Нельзя удалить категорию, в которой есть подкатегории.", show_alert=True)
        return
    username = call.from_user.username or str(call.from_user.id)
    log_action(call.from_user.id, username, "category_delete", f"{cid}")
    await call.message.edit_text(
        f"✅ Категория <b>{name}</b> удалена.",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


# ---------- подкатегории в админке ----------


@dp.callback_query_handler(lambda c: c.data == "admin_subcats")
async def admin_subcats(call: types.CallbackQuery):
    cats = get_categories()
    if not cats:
        await call.message.edit_text("Сначала добавьте хотя бы одну категорию.", reply_markup=admin_back_kb())
        await call.answer()
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for cid, name in cats:
        kb.add(
            types.InlineKeyboardButton(f"📂 {name}", callback_data=f"admin_subcats_cat:{cid}")
        )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
    await call.message.edit_text("Выберите категорию для работы с подкатегориями:", reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_subcats_cat:"))
async def admin_subcats_cat(call: types.CallbackQuery):
    cid = int(call.data.split(":", 1)[1])
    cat = get_category(cid)
    if not cat:
        await call.answer("Категория не найдена.", show_alert=True)
        return

    _, cat_name = cat
    subs = get_subcategories_by_category(cid)
    text_lines = [f"🗂 <b>Подкатегории категории</b> {cat_name}:\n"]
    kb = types.InlineKeyboardMarkup(row_width=1)

    if not subs:
        text_lines.append("<i>Подкатегорий пока нет.</i>")
    else:
        for sid, name in subs:
            text_lines.append(f"• <code>{sid}</code> — {name}")
            kb.add(
                types.InlineKeyboardButton(
                    f"✏ {name}", callback_data=f"admin_subcat_edit:{sid}"
                )
            )

    kb.add(
        types.InlineKeyboardButton(
            "➕ Добавить подкатегорию", callback_data=f"admin_subcat_add:{cid}"
        )
    )
    kb.add(types.InlineKeyboardButton("🔙 Назад к категориям", callback_data="admin_subcats"))

    await call.message.edit_text("\n".join(text_lines), reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_subcat_add:"))
async def admin_subcat_add(call: types.CallbackQuery):
    cid = int(call.data.split(":", 1)[1])
    if not get_category(cid):
        await call.answer("Категория не найдена.", show_alert=True)
        return
    admin_states[call.from_user.id] = {"mode": "subcat_add", "category_id": cid}
    await call.message.edit_text(
        "🗂 Отправьте <b>название новой подкатегории</b>:",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_subcat_edit:"))
async def admin_subcat_edit(call: types.CallbackQuery):
    sid = int(call.data.split(":", 1)[1])
    sub = get_subcategory(sid)
    if not sub:
        await call.answer("Подкатегория не найдена.", show_alert=True)
        return
    _, cid, name = sub
    cat = get_category(cid)
    cat_name = cat[1] if cat else "?"

    text = (
        f"🗂 <b>Подкатегория #{sid}</b>\n"
        f"Категория: <b>{cat_name}</b>\n"
        f"Название: <b>{name}</b>\n\n"
        "Выберите действие:"
    )
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✏ Переименовать", callback_data=f"admin_subcat_rename:{sid}"),
        types.InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_subcat_delete:{sid}"),
    )
    kb.add(
        types.InlineKeyboardButton("🧩 Проекты", callback_data=f"admin_projects_sub:{sid}"),
    )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"admin_subcats_cat:{cid}"))

    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_subcat_rename:"))
async def admin_subcat_rename(call: types.CallbackQuery):
    sid = int(call.data.split(":", 1)[1])
    if not get_subcategory(sid):
        await call.answer("Подкатегория не найдена.", show_alert=True)
        return
    admin_states[call.from_user.id] = {"mode": "subcat_rename", "subcategory_id": sid}
    await call.message.edit_text(
        "✏ Отправьте <b>новое название</b> подкатегории:",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


@dp.callback_query_handler(lambda c: c.data.startswith("admin_subcat_delete:"))
async def admin_subcat_delete(call: types.CallbackQuery):
    sid = int(call.data.split(":", 1)[1])
    sub = get_subcategory(sid)
    if not sub:
        await call.answer("Подкатегория не найдена.", show_alert=True)
        return
    _, cid, name = sub
    if not delete_subcategory(sid):
        await call.answer("Нельзя удалить подкатегорию, в которой есть проекты.", show_alert=True)
        return
    username = call.from_user.username or str(call.from_user.id)
    log_action(call.from_user.id, username, "subcategory_delete", f"{sid}")
    await call.message.edit_text(
        f"✅ Подкатегория <b>{name}</b> удалена.",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


# ---------- проекты в админке ----------


@dp.callback_query_handler(lambda c: c.data == "admin_projects")
async def admin_projects(call: types.CallbackQuery):
    con = get_db()
    cur = con.cursor()
    cur.execute("""
        SELECT p.id, p.title, p.is_published, s.name, c.name
        FROM projects p
        JOIN subcategories s ON p.subcategory_id = s.id
        JOIN categories c ON s.category_id = c.id
        ORDER BY p.created_at DESC
    """)
    rows = cur.fetchall()
    con.close()

    if not rows:
        await call.message.edit_text(
            "Проектов пока нет.",
            reply_markup=admin_back_kb(),
        )
        await call.answer()
        return

    text_lines = ["🧩 <b>Список проектов:</b>\n"]
    kb = types.InlineKeyboardMarkup(row_width=1)
    for pid, title, is_published, sname, cname in rows:
        status = "✅" if is_published else "❌"
        text_lines.append(f"{status} <code>{pid}</code> — {title} ({cname} / {sname})")
        kb.add(
            types.InlineKeyboardButton(
                f"{status} {title}", callback_data=f"admin_project:{pid}"
            )
        )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
    await call.message.edit_text("\n".join(text_lines), reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_projects_sub:"))
async def admin_projects_sub(call: types.CallbackQuery):
    sid = int(call.data.split(":", 1)[1])
    sub = get_subcategory(sid)
    if not sub:
        await call.answer("Подкатегория не найдена.", show_alert=True)
        return
    _, cid, sname = sub
    cat = get_category(cid)
    cname = cat[1] if cat else "?"

    projects = get_projects_by_subcategory(sid, published_only=False)
    text_lines = [f"🧩 <b>Проекты в</b> {cname} / {sname}:\n"]
    kb = types.InlineKeyboardMarkup(row_width=1)

    if not projects:
        text_lines.append("<i>Проектов пока нет.</i>")
    else:
        for row in projects:
            pid, title, desc, media, link, is_published = row
            status = "✅" if is_published else "❌"
            text_lines.append(f"{status} <code>{pid}</code> — {title}")
            kb.add(
                types.InlineKeyboardButton(
                    f"{status} {title}", callback_data=f"admin_project:{pid}"
                )
            )

    kb.add(
        types.InlineKeyboardButton(
            "➕ Добавить проект", callback_data=f"admin_add_project_sub:{sid}"
        )
    )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"admin_subcat_edit:{sid}"))

    await call.message.edit_text("\n".join(text_lines), reply_markup=kb)
    await call.answer()


def project_actions_kb(pid: int, is_published: int):
    kb = types.InlineKeyboardMarkup(row_width=2)
    status_btn = "👁️ Скрыть" if is_published else "👁️ Показать"
    kb.add(
        types.InlineKeyboardButton("✏ Название", callback_data=f"admin_edit_title:{pid}"),
        types.InlineKeyboardButton("📝 Описание", callback_data=f"admin_edit_desc:{pid}"),
    )
    kb.add(
        types.InlineKeyboardButton("🖼 Медиа", callback_data=f"admin_edit_media:{pid}"),
        types.InlineKeyboardButton("🔗 Ссылка", callback_data=f"admin_edit_link:{pid}"),
    )
    kb.add(
        types.InlineKeyboardButton("📁 Файлы", callback_data=f"admin_files:{pid}"),
        types.InlineKeyboardButton(status_btn, callback_data=f"admin_toggle:{pid}"),
    )
    kb.add(
        types.InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_delete:{pid}"),
        types.InlineKeyboardButton("👁 Предпросмотр", callback_data=f"admin_preview:{pid}"),
    )
    kb.add(types.InlineKeyboardButton("🔙 Назад к проектам", callback_data="admin_projects"))
    return kb


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_project:"))
async def admin_project(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    project = get_project(pid)
    if not project:
        await call.answer("Проект не найден.", show_alert=True)
        return

    pid, subcat_id, title, desc, media, link, is_published = project
    sub = get_subcategory(subcat_id)
    if sub:
        _, cid, sname = sub
        cat = get_category(cid)
        cname = cat[1] if cat else "?"
        path = f"{cname} / {sname}"
    else:
        path = "-"

    status = "✅ Опубликован" if is_published else "❌ Скрыт"
    text = (
        f"🧩 <b>Проект #{pid}</b>\n\n"
        f"<b>Название:</b> {title}\n"
        f"<b>Категория / подкатегория:</b> {path}\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Ссылка:</b> {link or 'не указана'}\n\n"
        f"<b>Описание:</b>\n{desc or '_Нет описания_'}"
    )

    await call.message.edit_text(text, reply_markup=project_actions_kb(pid, is_published))
    await call.answer()


@dp.callback_query_handler(lambda c: c.data == "admin_add_project")
async def admin_add_project(call: types.CallbackQuery):
    cats = get_categories()
    if not cats:
        await call.message.edit_text("Сначала создайте категорию в разделе 📂 Категории.", reply_markup=admin_back_kb())
        await call.answer()
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for cid, name in cats:
        kb.add(
            types.InlineKeyboardButton(
                f"📂 {name}", callback_data=f"admin_add_project_cat:{cid}"
            )
        )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))

    await call.message.edit_text("Выберите категорию для нового проекта:", reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_add_project_cat:"))
async def admin_add_project_cat(call: types.CallbackQuery):
    cid = int(call.data.split(":", 1)[1])
    subs = get_subcategories_by_category(cid)
    if not subs:
        await call.answer("Сначала создайте подкатегорию для этой категории.", show_alert=True)
        return

    cat = get_category(cid)
    cname = cat[1] if cat else "?"

    kb = types.InlineKeyboardMarkup(row_width=1)
    for sid, sname in subs:
        kb.add(
            types.InlineKeyboardButton(
                f"🗂 {sname}", callback_data=f"admin_add_project_sub:{sid}"
            )
        )
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_add_project"))

    await call.message.edit_text(
        f"Категория: <b>{cname}</b>\nВыберите подкатегорию для нового проекта:",
        reply_markup=kb,
    )
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_add_project_sub:"))
async def admin_add_project_sub(call: types.CallbackQuery):
    sid = int(call.data.split(":", 1)[1])
    sub = get_subcategory(sid)
    if not sub:
        await call.answer("Подкатегория не найдена.", show_alert=True)
        return
    _, cid, sname = sub
    cat = get_category(cid)
    cname = cat[1] if cat else "?"

    # ВАЖНО: инициализируем поля None, чтобы отличать "ещё не задавали" от "пустое/пропущено"
    admin_states[call.from_user.id] = {
        "mode": "project_add",
        "subcategory_id": sid,
        "temp": {
            "title": None,
            "description": None,
            "media": None,
            "link": None,
        },
    }

    text = (
        "🧩 <b>Добавление проекта</b>\n\n"
        f"Категория: <b>{cname}</b>\n"
        f"Подкатегория: <b>{sname}</b>\n\n"
        "Отправьте <b>название проекта</b>:"
    )
    await call.message.edit_text(text, reply_markup=admin_back_kb())
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_toggle:"))
async def admin_toggle(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    try:
        new_status = toggle_project_visibility(pid)
        status_text = "опубликован" if new_status else "скрыт"
        username = call.from_user.username or str(call.from_user.id)
        log_action(call.from_user.id, username, "project_toggle", f"{pid} -> {status_text}")
        await call.answer(f"Статус: {status_text}")

        project = get_project(pid)
        if project:
            pid, subcat_id, title, desc, media, link, is_published = project
            sub = get_subcategory(subcat_id)
            if sub:
                _, cid, sname = sub
                cat = get_category(cid)
                cname = cat[1] if cat else "?"
                path = f"{cname} / {sname}"
            else:
                path = "-"
            status = "✅ Опубликован" if is_published else "❌ Скрыт"
            text = (
                f"🧩 <b>Проект #{pid}</b>\n\n"
                f"<b>Название:</b> {title}\n"
                f"<b>Категория / подкатегория:</b> {path}\n"
                f"<b>Статус:</b> {status}\n"
                f"<b>Ссылка:</b> {link or 'не указана'}\n\n"
                f"<b>Описание:</b>\n{desc or '_Нет описания_'}"
            )
            await call.message.edit_text(text, reply_markup=project_actions_kb(pid, is_published))
    except Exception as e:
        logger.error(f"Error toggle project: {e}")
        await call.answer("Ошибка.")


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_delete:"))
async def admin_delete(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    project = get_project(pid)
    if not project:
        await call.answer("Проект не найден.", show_alert=True)
        return
    pid, subcat_id, title, *_ = project

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"admin_delete_confirm:{pid}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data=f"admin_project:{pid}"),
    )
    text = (
        f"❗ Вы уверены, что хотите удалить проект #{pid}:\n"
        f"<b>{title}</b>\n\n"
        "Это действие нельзя отменить."
    )
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_delete_confirm:"))
async def admin_delete_confirm(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    project = get_project(pid)
    if not project:
        await call.answer("Проект не найден.", show_alert=True)
        return
    delete_project(pid)
    username = call.from_user.username or str(call.from_user.id)
    log_action(call.from_user.id, username, "project_delete", f"{pid}")
    await call.message.edit_text(f"✅ Проект #{pid} удалён.", reply_markup=admin_back_kb())
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_preview:"))
async def admin_preview(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    await call.answer()
    await send_project_card(call.message.chat.id, pid)


# ---------- редактирование полей проекта ----------


def start_field_edit(user_id: int, pid: int, field: str):
    admin_states[user_id] = {
        "mode": "project_edit_field",
        "project_id": pid,
        "field": field,
    }


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_edit_title:"))
async def admin_edit_title(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    if not get_project(pid):
        await call.answer("Проект не найден.", show_alert=True)
        return
    start_field_edit(call.from_user.id, pid, "title")
    await call.message.edit_text("✏ Отправьте <b>новое название</b> проекта:", reply_markup=admin_back_kb())
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_edit_desc:"))
async def admin_edit_desc(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    if not get_project(pid):
        await call.answer("Проект не найден.", show_alert=True)
        return
    start_field_edit(call.from_user.id, pid, "description")
    await call.message.edit_text("📝 Отправьте <b>новое описание</b> проекта:", reply_markup=admin_back_kb())
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_edit_media:"))
async def admin_edit_media(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    if not get_project(pid):
        await call.answer("Проект не найден.", show_alert=True)
        return
    start_field_edit(call.from_user.id, pid, "media")
    await call.message.edit_text(
        "🖼 Отправьте <b>новое фото</b> проекта или URL картинки.\n"
        "Или отправьте /clear, чтобы убрать медиа.",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_edit_link:"))
async def admin_edit_link(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    if not get_project(pid):
        await call.answer("Проект не найден.", show_alert=True)
        return
    start_field_edit(call.from_user.id, pid, "link")
    await call.message.edit_text(
        "🔗 Отправьте <b>новую ссылку</b> (GitHub, сайт, видео).\n"
        "Или отправьте /clear, чтобы убрать ссылку.",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


# ---------- файлы проекта в админке ----------


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_files:"))
async def admin_files(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    project = get_project(pid)
    if not project:
        await call.answer("Проект не найден.", show_alert=True)
        return

    files = get_project_files(pid)
    _, _, title, *_ = project
    text_lines = [f"📁 <b>Файлы проекта</b> <code>{title}</code>:\n"]
    if not files:
        text_lines.append("<i>Файлов пока нет.</i>")
    else:
        for i, (row_id, file_id, file_name, created_at) in enumerate(files, start=1):
            dt = created_at or ""
            text_lines.append(f"{i}. <code>{file_name or 'без имени'}</code> (ID: {row_id}, {dt})")

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("➕ Добавить файл", callback_data=f"admin_add_file:{pid}"))
    if files:
        kb.add(types.InlineKeyboardButton("🗑 Удалить файл", callback_data=f"admin_del_file_menu:{pid}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад к проекту", callback_data=f"admin_project:{pid}"))

    await call.message.edit_text("\n".join(text_lines), reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_add_file:"))
async def admin_add_file(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    if not get_project(pid):
        await call.answer("Проект не найден.", show_alert=True)
        return
    admin_states[call.from_user.id] = {
        "mode": "add_file",
        "project_id": pid,
    }
    await call.message.edit_text(
        "📁 Отправьте <b>документ</b> (файл .zip/.sma/.sp/.cfg и т.п.), который нужно привязать к проекту.",
        reply_markup=admin_back_kb(),
    )
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_del_file_menu:"))
async def admin_del_file_menu(call: types.CallbackQuery):
    pid = int(call.data.split(":", 1)[1])
    files = get_project_files(pid)
    if not files:
        await call.answer("Файлов нет.", show_alert=True)
        return

    kb = types.InlineKeyboardMarkup()
    for row_id, file_id, file_name, created_at in files:
        caption = file_name or f"ID {row_id}"
        kb.add(types.InlineKeyboardButton(caption, callback_data=f"admin_del_file:{row_id}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"admin_files:{pid}"))

    await call.message.edit_text("Выберите файл для удаления:", reply_markup=kb)
    await call.answer()


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_del_file:"))
async def admin_del_file(call: types.CallbackQuery):
    row_id = int(call.data.split(":", 1)[1])
    delete_project_file(row_id)
    await call.answer("Файл удалён.")
    await call.message.edit_text("✅ Файл удалён. Вернитесь к проекту и обновите список.")


# ---------- статистика и логи ----------


@dp.callback_query_handler(lambda c: c.data == "admin_stats")
async def admin_stats(call: types.CallbackQuery):
    stats = get_statistics()
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"Всего проектов: {stats['total_projects']}\n"
        f"Опубликовано: {stats['published_projects']}\n"
        f"Действий сегодня: {stats['today_actions']}\n"
        f"Уникальных пользователей сегодня: {stats['unique_users_today']}\n"
    )
    await call.message.edit_text(text, reply_markup=admin_back_kb())
    await call.answer()


@dp.callback_query_handler(lambda c: c.data == "admin_logs")
async def admin_logs(call: types.CallbackQuery):
    con = get_db()
    cur = con.cursor()
    cur.execute(
        "SELECT username, action, details, created_at FROM audit_log ORDER BY created_at DESC LIMIT 10"
    )
    logs = cur.fetchall()
    con.close()

    if not logs:
        text = "Логов пока нет."
    else:
        lines = ["📝 <b>Последние действия:</b>\n"]
        for username, action, details, created_at in logs:
            name = username or "unknown"
            time_str = created_at or ""
            line = f"– <code>{time_str}</code> — <b>{name}</b>: <code>{action}</code>"
            if details:
                line += f" ({details})"
            lines.append(line)
        text = "\n".join(lines)

    await call.message.edit_text(text, reply_markup=admin_back_kb())
    await call.answer()


# ================== ОБЩИЙ ХЕНДЛЕР СОСТОЯНИЙ АДМИНА ==================


@dp.message_handler(content_types=types.ContentTypes.ANY)
async def admin_state_handler(message: types.Message):
    user_id = message.from_user.id

    if user_id in admin_states:
        state = admin_states[user_id]
        mode = state.get("mode")

        # --- добавление категории ---
        if mode == "cat_add":
            if not message.text:
                await message.answer("Название категории должно быть текстом.")
                return
            name = message.text.strip()
            if not name:
                await message.answer("Название не может быть пустым.")
                return
            cid = add_category(name)
            username = message.from_user.username or str(message.from_user.id)
            log_action(user_id, username, "category_add", f"{cid}")
            admin_states.pop(user_id, None)
            await message.answer(f"✅ Категория <b>{name}</b> создана.", reply_markup=admin_back_kb())
            return

        # --- переименование категории ---
        if mode == "cat_rename":
            cid = state["category_id"]
            if not message.text:
                await message.answer("Название должно быть текстом.")
                return
            new_name = message.text.strip()
            if not new_name:
                await message.answer("Название не может быть пустым.")
                return
            rename_category(cid, new_name)
            username = message.from_user.username or str(message.from_user.id)
            log_action(user_id, username, "category_rename", f"{cid}")
            admin_states.pop(user_id, None)
            await message.answer("✅ Категория переименована.", reply_markup=admin_back_kb())
            return

        # --- добавление подкатегории ---
        if mode == "subcat_add":
            cid = state["category_id"]
            if not message.text:
                await message.answer("Название подкатегории должно быть текстом.")
                return
            name = message.text.strip()
            if not name:
                await message.answer("Название не может быть пустым.")
                return
            sid = add_subcategory(cid, name)
            username = message.from_user.username or str(message.from_user.id)
            log_action(user_id, username, "subcategory_add", f"{sid}")
            admin_states.pop(user_id, None)
            await message.answer("✅ Подкатегория создана.", reply_markup=admin_back_kb())
            return

        # --- переименование подкатегории ---
        if mode == "subcat_rename":
            sid = state["subcategory_id"]
            if not message.text:
                await message.answer("Название должно быть текстом.")
                return
            new_name = message.text.strip()
            if not new_name:
                await message.answer("Название не может быть пустым.")
                return
            rename_subcategory(sid, new_name)
            username = message.from_user.username or str(message.from_user.id)
            log_action(user_id, username, "subcategory_rename", f"{sid}")
            admin_states.pop(user_id, None)
            await message.answer("✅ Подкатегория переименована.", reply_markup=admin_back_kb())
            return

        # --- добавление проекта (простая последовательная форма) ---
        if mode == "project_add":
            temp = state["temp"]
            sid = state["subcategory_id"]

            # 1) Название
            if temp["title"] is None:
                if not message.text:
                    await message.answer("Название должно быть текстом.")
                    return
                temp["title"] = message.text.strip()
                if not temp["title"]:
                    await message.answer("Название не может быть пустым.")
                    return
                await message.answer("📄 Отправьте <b>описание</b> проекта:")
                return

            # 2) Описание
            if temp["description"] is None:
                if not message.text:
                    await message.answer("Описание должно быть текстом.")
                    return
                temp["description"] = message.text
                await message.answer(
                    "🖼 Отправьте <b>фото</b> проекта или URL, либо отправьте /skip, чтобы пропустить медиа."
                )
                return

            # 3) Медиа
            if temp["media"] is None:
                # Пропуск медиа
                if message.text and message.text.strip().lower() == "/skip":
                    temp["media"] = ""
                    await message.answer(
                        "🔗 Отправьте <b>ссылку</b> (GitHub, сайт, видео) или /skip, чтобы пропустить."
                    )
                    return

                # Фото
                if message.photo:
                    temp["media"] = message.photo[-1].file_id
                    await message.answer(
                        "🔗 Отправьте <b>ссылку</b> (GitHub, сайт, видео) или /skip, чтобы пропустить."
                    )
                    return

                # URL-строка
                if message.text and message.text.startswith("http"):
                    temp["media"] = message.text.strip()
                    await message.answer(
                        "🔗 Отправьте <b>ссылку</b> (GitHub, сайт, видео) или /skip, чтобы пропустить."
                    )
                    return

                await message.answer("Отправьте фото или URL, либо /skip.")
                return

            # 4) Ссылка
            if temp["link"] is None:
                # Пропуск ссылки
                if message.text and message.text.strip().lower() == "/skip":
                    temp["link"] = ""
                else:
                    if not message.text:
                        await message.answer("Ссылка должна быть текстом или отправьте /skip.")
                        return
                    temp["link"] = message.text.strip()

                # Сохраняем проект
                pid = add_project(
                    sid,
                    temp["title"],
                    temp["description"],
                    temp["media"],
                    temp["link"],
                )
                username = message.from_user.username or str(message.from_user.id)
                log_action(user_id, username, "project_add", f"{pid}")
                admin_states.pop(user_id, None)
                await message.answer(f"✅ Проект добавлен (ID {pid}).", reply_markup=admin_back_kb())
                return

        # --- редактирование одного поля проекта ---
        if mode == "project_edit_field":
            pid = state["project_id"]
            field = state["field"]
            project = get_project(pid)
            if not project:
                await message.answer("Проект не найден.")
                admin_states.pop(user_id, None)
                return

            pid, subcat_id, title, desc, media, link, is_published = project

            if field == "title":
                if not message.text:
                    await message.answer("Название должно быть текстом.")
                    return
                new_title = message.text.strip()
                update_project(pid, new_title, desc or "", media or "", link or "")
                admin_states.pop(user_id, None)
                await message.answer("✅ Название обновлено.", reply_markup=admin_back_kb())
                return

            if field == "description":
                if not message.text:
                    await message.answer("Описание должно быть текстом.")
                    return
                new_desc = message.text
                update_project(pid, title, new_desc, media or "", link or "")
                admin_states.pop(user_id, None)
                await message.answer("✅ Описание обновлено.", reply_markup=admin_back_kb())
                return

            if field == "media":
                if message.text and message.text.strip().lower() == "/clear":
                    update_project(pid, title, desc or "", "", link or "")
                    admin_states.pop(user_id, None)
                    await message.answer("✅ Медиа очищено.", reply_markup=admin_back_kb())
                    return

                if message.photo:
                    new_media = message.photo[-1].file_id
                    update_project(pid, title, desc or "", new_media, link or "")
                    admin_states.pop(user_id, None)
                    await message.answer("✅ Фото обновлено.", reply_markup=admin_back_kb())
                    return

                if message.text and message.text.startswith("http"):
                    new_media = message.text.strip()
                    update_project(pid, title, desc or "", new_media, link or "")
                    admin_states.pop(user_id, None)
                    await message.answer("✅ Медиа URL обновлён.", reply_markup=admin_back_kb())
                    return

                await message.answer("Отправьте фото или URL, либо /clear.")
                return

            if field == "link":
                if message.text and message.text.strip().lower() == "/clear":
                    update_project(pid, title, desc or "", media or "", "")
                    admin_states.pop(user_id, None)
                    await message.answer("✅ Ссылка очищена.", reply_markup=admin_back_kb())
                    return

                if not message.text:
                    await message.answer("Ссылка должна быть текстом.")
                    return

                new_link = message.text.strip()
                update_project(pid, title, desc or "", media or "", new_link)
                admin_states.pop(user_id, None)
                await message.answer("✅ Ссылка обновлена.", reply_markup=admin_back_kb())
                return

        # --- добавление файла к проекту ---
        if mode == "add_file":
            pid = state["project_id"]
            if not message.document:
                await message.answer("Нужно отправить <b>документ</b> (файл). Попробуйте ещё раз.")
                return

            doc = message.document
            try:
                stored_file_id = doc.file_id
                if FILES_CHANNEL_ID:
                    sent = await bot.send_document(
                        chat_id=FILES_CHANNEL_ID,
                        document=doc.file_id,
                        caption=f"Файл для проекта {pid}: {doc.file_name}",
                    )
                    stored_file_id = sent.document.file_id

                add_project_file(pid, stored_file_id, doc.file_name or "")
                username = message.from_user.username or str(message.from_user.id)
                log_action(user_id, username, "project_file_add", f"{pid}")
                admin_states.pop(user_id, None)
                await message.answer("✅ Файл добавлен к проекту.", reply_markup=admin_back_kb())
            except Exception as e:
                logger.error(f"Error adding file to project {pid}: {e}")
                await message.answer("Ошибка при добавлении файла.")
            return

    # Если нет состояния, но это админ — подсказываем
    if message.from_user.id in admin_sessions:
        await message.answer(
            "Вы в режиме админа. Используйте кнопки админки или /admin для отображения панели.",
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer("Выберите действие в меню.", reply_markup=main_menu_kb())


# ================== ЗАПУСК ==================


if __name__ == "__main__":
    init_db()
    logger.info("Starting portfolio bot with categories/subcategories...")
    executor.start_polling(dp, skip_updates=True)
