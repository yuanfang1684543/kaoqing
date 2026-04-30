"""
Telegram 考勤打卡机器人
功能：上下班打卡、查询记录、管理员面板、个人设置
支持 SQLite（本地）和 PostgreSQL（Railway 生产环境）
"""

import os
import sys
import json
import socket
import sqlite3
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

# ---------- 日志 ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- 时区处理 ----------
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Shanghai")
except ImportError:
    TZ = None
    logger.warning("zoneinfo 不可用，使用 UTC+8 固定偏移修复")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---------- 配置 ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = set(
    int(uid) for uid in os.environ.get("ADMIN_IDS", "").split(",") if uid
)
DB_TYPE = os.environ.get("DB_TYPE", "sqlite").lower()
DB_PATH = os.environ.get("DB_PATH", "attendance.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")


# ==================== 时间工具 ====================

def now_str() -> str:
    if TZ:
        return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

def today_str() -> str:
    if TZ:
        return datetime.now(TZ).strftime("%Y-%m-%d")
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")

def this_month_str() -> str:
    if TZ:
        return datetime.now(TZ).strftime("%Y-%m")
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m")


# ==================== 数据库操作 ====================

def get_conn():
    if DB_TYPE == "postgres":
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_PATH)


def _pg_qmark(sql: str) -> str:
    """将 SQLite 的 ? 占位符替换为 PostgreSQL 的 %s"""
    return sql.replace("?", "%s")


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    is_pg = DB_TYPE == "postgres"
    q = _pg_qmark if is_pg else lambda x: x

    # 考勤表
    if is_pg:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                username    TEXT,
                first_name  TEXT,
                action      TEXT NOT NULL CHECK(action IN ('in','out')),
                timestamp   TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_attendance_user_date
            ON attendance (user_id, timestamp)
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                username    TEXT,
                first_name  TEXT,
                action      TEXT NOT NULL CHECK(action IN ('in','out')),
                timestamp   TEXT NOT NULL
            )
        """)

    # 用户偏好表
    cur.execute(q("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            first_name TEXT,
            reminder   INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """))

    conn.commit()
    conn.close()
    logger.info("数据库表初始化完成（类型：%s）", DB_TYPE)


# ---------- 考勤操作 ----------

def record_action(user_id: int, username: str, first_name: str, action: str) -> str:
    ts = now_str()
    conn = get_conn()
    cur = conn.cursor()
    q = _pg_qmark if DB_TYPE == "postgres" else lambda x: x
    cur.execute(q(
        "INSERT INTO attendance (user_id, username, first_name, action, timestamp) VALUES (?, ?, ?, ?, ?)"
    ), (user_id, username, first_name, action, ts))
    conn.commit()
    conn.close()
    return ts


def get_today_record(user_id: int):
    today = today_str()
    conn = get_conn()
    cur = conn.cursor()
    q = _pg_qmark if DB_TYPE == "postgres" else lambda x: x
    cur.execute(q(
        "SELECT action, timestamp FROM attendance WHERE user_id = ? AND timestamp LIKE ? ORDER BY timestamp"
    ), (user_id, f"{today}%"))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_records(user_id: int, days: int = 7):
    from_date = (datetime.now(TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_conn()
    cur = conn.cursor()
    q = _pg_qmark if DB_TYPE == "postgres" else lambda x: x
    cur.execute(q(
        "SELECT action, timestamp FROM attendance WHERE user_id = ? AND timestamp >= ? ORDER BY timestamp DESC"
    ), (user_id, from_date))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_month_records(user_id: int):
    """查询用户本月打卡记录"""
    month = this_month_str()
    conn = get_conn()
    cur = conn.cursor()
    q = _pg_qmark if DB_TYPE == "postgres" else lambda x: x
    cur.execute(q(
        "SELECT action, timestamp FROM attendance WHERE user_id = ? AND timestamp LIKE ? ORDER BY timestamp"
    ), (user_id, f"{month}%"))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_today_records():
    today = today_str()
    conn = get_conn()
    cur = conn.cursor()
    q = _pg_qmark if DB_TYPE == "postgres" else lambda x: x
    cur.execute(q(
        "SELECT user_id, username, first_name, action, timestamp FROM attendance WHERE timestamp LIKE ? ORDER BY timestamp"
    ), (f"{today}%",))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_summary(days: int = 30):
    from_date = (datetime.now(TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_conn()
    cur = conn.cursor()
    q = _pg_qmark if DB_TYPE == "postgres" else lambda x: x
    if DB_TYPE == "postgres":
        cur.execute(q(
            "SELECT user_id, username, first_name, action, DATE(timestamp) FROM attendance WHERE timestamp >= ? ORDER BY timestamp DESC"
        ), (from_date,))
    else:
        cur.execute(q(
            "SELECT user_id, username, first_name, action, DATE(timestamp) FROM attendance WHERE timestamp >= ? ORDER BY timestamp DESC"
        ), (from_date,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------- 用户偏好 ----------

def get_user_prefs(user_id: int, username: str, first_name: str) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    q = _pg_qmark if DB_TYPE == "postgres" else lambda x: x
    cur.execute(q("SELECT * FROM user_prefs WHERE user_id = ?"), (user_id,))
    row = cur.fetchone()
    now = now_str()
    if not row:
        # 创建默认偏好
        cur.execute(q(
            "INSERT INTO user_prefs (user_id, username, first_name, reminder, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)"
        ), (user_id, username, first_name, now, now))
        conn.commit()
        cur.execute(q("SELECT * FROM user_prefs WHERE user_id = ?"), (user_id,))
        row = cur.fetchone()
    conn.close()
    if DB_TYPE == "postgres":
        return {"user_id": row[0], "username": row[1], "first_name": row[2], "reminder": row[3], "created_at": row[4], "updated_at": row[5]}
    return {"user_id": row[0], "username": row[1], "first_name": row[2], "reminder": row[3], "created_at": row[4], "updated_at": row[5]}


def toggle_reminder(user_id: int) -> bool:
    """切换提醒开关，返回新的状态"""
    conn = get_conn()
    cur = conn.cursor()
    q = _pg_qmark if DB_TYPE == "postgres" else lambda x: x
    cur.execute(q("SELECT reminder FROM user_prefs WHERE user_id = ?"), (user_id,))
    row = cur.fetchone()
    new_val = 0 if row and row[0] == 1 else 1
    now = now_str()
    cur.execute(q(
        "UPDATE user_prefs SET reminder = ?, updated_at = ? WHERE user_id = ?"
    ), (new_val, now, user_id))
    conn.commit()
    conn.close()
    return bool(new_val)


def get_user_month_stats(user_id: int):
    """获取用户本月打卡统计"""
    records = get_month_records(user_id)
    if not records:
        return None
    # 按天分组
    days = {}
    for action, ts in records:
        date = ts[:10]  # YYYY-MM-DD
        if date not in days:
            days[date] = set()
        days[date].add(action)
    total = len(days)
    normal = sum(1 for acts in days.values() if "in" in acts and "out" in acts)
    late = sum(1 for d, acts in days.items() if "in" in acts and "out" not in acts)
    return {"total": total, "normal": normal, "late": late, "days": days}


# ==================== 键盘构建 ====================

def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def main_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """主菜单"""
    kb = [
        [btn("🏢 上班打卡", "clock_in"), btn("🏠 下班打卡", "clock_out")],
        [btn("📊 今日记录", "today"), btn("📅 近7天记录", "week")],
        [btn("📆 本月统计", "month_stats")],
        [btn("⚙️ 个人设置", "settings")],
    ]
    if is_admin:
        kb.append([btn("👑 管理员面板", "admin_panel")])
    return InlineKeyboardMarkup(kb)


def back_btn(data: str = "main_menu") -> list:
    return [btn("🔙 返回主菜单", data)]


def admin_keyboard() -> InlineKeyboardMarkup:
    """管理员面板"""
    kb = [
        [btn("📋 今日全员打卡", "admin_today_all")],
        [btn("📈 近30天统计", "admin_summary")],
        back_btn(),
    ]
    return InlineKeyboardMarkup(kb)


def settings_keyboard(reminder_on: bool) -> InlineKeyboardMarkup:
    """个人设置面板"""
    reminder_label = "✅ 打卡提醒已开启" if reminder_on else "❌ 打卡提醒已关闭"
    kb = [
        [btn(reminder_label, "toggle_reminder")],
        [btn("📆 本月打卡统计", "month_stats")],
        back_btn(),
    ]
    return InlineKeyboardMarkup(kb)


# ==================== 命令处理 ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = user.id in ADMIN_IDS
    await update.message.reply_text(
        "👋 欢迎使用考勤打卡机器人！\n\n"
        "📌 点击下方按钮操作：\n"
        "🏢 上班打卡 / 🏠 下班打卡\n"
        "📊 查看打卡记录 / 本月统计\n"
        "⚙️ 个人设置\n\n"
        "📖 发送 /help 查看帮助",
        reply_markup=main_keyboard(is_admin),
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = user.id in ADMIN_IDS
    await update.message.reply_text("📌 请选择操作：", reply_markup=main_keyboard(is_admin))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 <b>考勤打卡机器人使用帮助</b>\n\n"
        "<b>基本操作：</b>\n"
        "🏢 上班打卡 — 点击按钮记录上班时间\n"
        "🏠 下班打卡 — 需先上班打卡，避免漏打卡\n"
        "📊 今日记录 — 查看今天打卡情况\n"
        "📅 近7天记录 — 查看一周打卡历史\n"
        "📆 本月统计 — 查看本月出勤天数\n\n"
        "<b>设置：</b>\n"
        "⚙️ 个人设置 — 开启/关闭打卡提醒\n\n"
        "<b>管理员命令：</b>\n"
        "/today_all — 今日全员打卡记录\n"
        "/summary — 近30天考勤统计\n\n"
        "<b>其他命令：</b>\n"
        "/start — 启动机器人\n"
        "/menu — 显示主菜单\n"
        "/help — 显示此帮助",
        parse_mode="HTML",
    )


# ==================== 按钮回调处理 ====================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    is_admin = user_id in ADMIN_IDS

    data = query.data

    # ---- 打卡 ----
    if data == "clock_in":
        now = record_action(user_id, username, first_name, "in")
        await query.message.reply_text(
            f"✅ <b>{first_name}</b>，上班打卡成功！\n"
            f"🕐 打卡时间：{now}",
            reply_markup=main_keyboard(is_admin),
            parse_mode="HTML",
        )
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "clock_out":
        records = get_today_record(user_id)
        has_in = any(r[0] == "in" for r in records)
        if not has_in:
            await query.message.reply_text(
                "⚠️ 你今天还没有上班打卡，请先上班打卡！",
                reply_markup=main_keyboard(is_admin),
            )
            await query.edit_message_reply_markup(reply_markup=None)
            return
        now = record_action(user_id, username, first_name, "out")
        await query.message.reply_text(
            f"✅ <b>{first_name}</b>，下班打卡成功！\n"
            f"🕐 打卡时间：{now}",
            reply_markup=main_keyboard(is_admin),
            parse_mode="HTML",
        )
        await query.edit_message_reply_markup(reply_markup=None)

    # ---- 查询记录 ----
    elif data == "today":
        records = get_today_record(user_id)
        if not records:
            text = f"📭 <b>{first_name}</b>，今天还没有打卡记录。"
        else:
            text = f"📊 <b>{first_name}</b> 今日打卡记录：\n\n"
            for action, ts in records:
                emoji = "🏢" if action == "in" else "🏠"
                label = "上班" if action == "in" else "下班"
                text += f"{emoji} {label}：{ts}\n"
        await query.message.reply_text(text, reply_markup=main_keyboard(is_admin), parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "week":
        records = get_user_records(user_id, days=7)
        if not records:
            text = f"📭 <b>{first_name}</b>，近7天没有打卡记录。"
        else:
            text = f"📅 <b>{first_name}</b> 近7天打卡记录：\n\n"
            for action, ts in records:
                emoji = "🏢" if action == "in" else "🏠"
                label = "上班" if action == "in" else "下班"
                text += f"{emoji} {label}：{ts}\n"
        await query.message.reply_text(text, reply_markup=main_keyboard(is_admin), parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "month_stats":
        stats = get_user_month_stats(user_id)
        if not stats:
            text = f"📭 <b>{first_name}</b>，本月还没有打卡记录。"
        else:
            text = (
                f"📆 <b>{first_name}</b> 本月打卡统计\n\n"
                f"📅 出勤天数：{stats['total']} 天\n"
                f"✅ 正常上下班：{stats['normal']} 天\n"
                f"⚠️ 未下班打卡：{stats['late']} 天\n\n"
                "<b>每日明细：</b>\n"
            )
            for date in sorted(stats["days"].keys()):
                acts = stats["days"][date]
                status = "✅" if "in" in acts and "out" in acts else "⚠️"
                text += f"{status} {date}\n"
        await query.message.reply_text(text, reply_markup=main_keyboard(is_admin), parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=None)

    # ---- 导航 ----
    elif data == "main_menu":
        await query.message.reply_text("📌 请选择操作：", reply_markup=main_keyboard(is_admin))
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "settings":
        prefs = get_user_prefs(user_id, username, first_name)
        await query.message.reply_text(
            f"⚙️ <b>{first_name}</b> 的个人设置\n\n"
            "你可以在这里管理打卡提醒等功能。",
            reply_markup=settings_keyboard(prefs["reminder"]),
            parse_mode="HTML",
        )
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "toggle_reminder":
        new_state = toggle_reminder(user_id)
        status = "开启" if new_state else "关闭"
        await query.message.reply_text(
            f"✅ 打卡提醒已{status}！\n\n{('每天上班时间将收到打卡提醒。' if new_state else '已关闭打卡提醒。')}",
            reply_markup=settings_keyboard(new_state),
        )
        await query.edit_message_reply_markup(reply_markup=None)

    # ---- 管理员面板 ----
    elif data == "admin_panel":
        if not is_admin:
            await query.message.reply_text("⛔ 你没有管理员权限！", reply_markup=main_keyboard(is_admin))
            await query.edit_message_reply_markup(reply_markup=None)
            return
        await query.message.reply_text(
            "👑 <b>管理员面板</b>",
            reply_markup=admin_keyboard(),
            parse_mode="HTML",
        )
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "admin_today_all":
        if not is_admin:
            await query.message.reply_text("⛔ 你没有管理员权限！", reply_markup=main_keyboard(is_admin))
            await query.edit_message_reply_markup(reply_markup=None)
            return
        records = get_all_today_records()
        if not records:
            await query.message.reply_text("📭 今天还没有任何人打卡。", reply_markup=admin_keyboard())
            await query.edit_message_reply_markup(reply_markup=None)
            return
        text = "📊 <b>今日全员打卡记录：</b>\n\n"
        for uid, uname, fname, action, ts in records:
            display = fname or uname or str(uid)
            emoji = "🏢" if action == "in" else "🏠"
            label = "上班" if action == "in" else "下班"
            text += f"{emoji} {display} — {label}：{ts}\n"
        await query.message.reply_text(text, reply_markup=admin_keyboard(), parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "admin_summary":
        if not is_admin:
            await query.message.reply_text("⛔ 你没有管理员权限！", reply_markup=main_keyboard(is_admin))
            await query.edit_message_reply_markup(reply_markup=None)
            return
        rows = get_summary(days=30)
        if not rows:
            await query.message.reply_text("📭 近30天没有打卡记录。", reply_markup=admin_keyboard())
            await query.edit_message_reply_markup(reply_markup=None)
            return
        stats = {}
        for uid, uname, fname, action, date in rows:
            display = fname or uname or str(uid)
            if uid not in stats:
                stats[uid] = {"name": display, "days": {}}
            if date not in stats[uid]["days"]:
                stats[uid]["days"][date] = set()
            stats[uid]["days"][date].add(action)
        text = "📊 <b>近30天考勤统计：</b>\n\n"
        for uid, data in stats.items():
            total_days = len(data["days"])
            normal_days = sum(
                1 for acts in data["days"].values()
                if "in" in acts and "out" in acts
            )
            text += (
                f"👤 <b>{data['name']}</b>\n"
                f"   出勤 {total_days} 天，正常上下班 {normal_days} 天\n\n"
            )
        await query.message.reply_text(text, reply_markup=admin_keyboard(), parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=None)

    else:
        # 未知回调 -> 回主菜单
        await query.message.reply_text("📌 请选择操作：", reply_markup=main_keyboard(is_admin))
        await query.edit_message_reply_markup(reply_markup=None)


# ==================== 管理员命令（兼容旧版）====================

async def today_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    if ADMIN_IDS and not is_admin:
        await update.message.reply_text("⛔ 你没有管理员权限！")
        return
    records = get_all_today_records()
    if not records:
        await update.message.reply_text("📭 今天还没有任何人打卡。")
        return
    text = "📊 <b>今日全员打卡记录：</b>\n\n"
    for uid, uname, fname, action, ts in records:
        display = fname or uname or str(uid)
        emoji = "🏢" if action == "in" else "🏠"
        label = "上班" if action == "in" else "下班"
        text += f"{emoji} {display} — {label}：{ts}\n"
    kb = main_keyboard(is_admin) if is_admin else None
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    if ADMIN_IDS and not is_admin:
        await update.message.reply_text("⛔ 你没有管理员权限！")
        return
    rows = get_summary(days=30)
    if not rows:
        await update.message.reply_text("📭 近30天没有打卡记录。")
        return
    stats = {}
    for uid, uname, fname, action, date in rows:
        display = fname or uname or str(uid)
        if uid not in stats:
            stats[uid] = {"name": display, "days": {}}
        if date not in stats[uid]["days"]:
            stats[uid]["days"][date] = set()
        stats[uid]["days"][date].add(action)
    text = "📊 <b>近30天考勤统计：</b>\n\n"
    for uid, data in stats.items():
        total_days = len(data["days"])
        normal_days = sum(1 for acts in data["days"].values() if "in" in acts and "out" in acts)
        text += f"👤 <b>{data['name']}</b>\n   出勤 {total_days} 天，正常上下班 {normal_days} 天\n\n"
    kb = main_keyboard(is_admin) if is_admin else None
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"更新 {update} 时发生错误：{context.error}", exc_info=True)


# ==================== Health Check Web 服务 ====================

class HealthHandler(BaseHTTPRequestHandler):
    """Railway 健康检查用，返回 200 OK"""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "attendance-bot"}).encode())
    def log_message(self, format, *args):
        logger.debug("Health: %s", format % args)


def start_health_server():
    """在后台线程启动健康检查 HTTP 服务器"""
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("健康检查 HTTP 服务器已启动，端口：%d", port)


# ==================== 主函数 ====================

def main():
    if not BOT_TOKEN:
        logger.error("未设置 BOT_TOKEN 环境变量！")
        sys.exit(1)
    if DB_TYPE == "postgres" and not DATABASE_URL:
        logger.error("使用 PostgreSQL 但未设置 DATABASE_URL 环境变量！")
        sys.exit(1)

    # 启动健康检查 HTTP 服务（Railway 需要）
    start_health_server()

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # 命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("today_all", today_all))
    app.add_handler(CommandHandler("summary", summary))

    # 按钮
    app.add_handler(CallbackQueryHandler(button_handler))

    # 错误
    app.add_error_handler(error_handler)

    logger.info("考勤机器人已启动...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
