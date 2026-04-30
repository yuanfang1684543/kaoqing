"""
Telegram 考勤打卡机器人
功能：上班打卡、下班打卡、查询打卡记录
支持 SQLite（本地）和 PostgreSQL（Railway 生产环境）
"""

import os
import sys
import sqlite3
import logging
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
    # Python < 3.9 回退：用 UTC+8 固定偏移
    TZ = None
    logger.warning("zoneinfo 不可用，使用 UTC+8 固定偏移")

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
# 数据库类型：sqlite / postgres
DB_TYPE = os.environ.get("DB_TYPE", "sqlite").lower()
DB_PATH = os.environ.get("DB_PATH", "attendance.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")


# ==================== 时间工具 ====================

def now_str() -> str:
    """获取当前时间字符串（中国时区）"""
    if TZ:
        return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    """获取今天的日期字符串"""
    if TZ:
        return datetime.now(TZ).strftime("%Y-%m-%d")
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")


# ==================== 数据库操作 ====================

def get_conn():
    """获取数据库连接"""
    if DB_TYPE == "postgres":
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    # SQLite
    return sqlite3.connect(DB_PATH)


def init_db():
    """初始化数据库表结构"""
    if DB_TYPE == "postgres":
        _init_pg()
    else:
        _init_sqlite()


def _init_sqlite():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            username    TEXT,
            first_name  TEXT,
            action      TEXT NOT NULL CHECK(action IN ('in', 'out')),
            timestamp   TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _init_pg():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id          SERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL,
            username    TEXT,
            first_name  TEXT,
            action      TEXT NOT NULL CHECK(action IN ('in', 'out')),
            timestamp   TEXT NOT NULL
        )
    """)
    # 创建索引加快查询
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_user_date
        ON attendance (user_id, timestamp)
    """)
    conn.commit()
    conn.close()


def record_action(user_id: int, username: str, first_name: str, action: str) -> str:
    """记录打卡动作"""
    ts = now_str()
    conn = get_conn()
    cur = conn.cursor()
    if DB_TYPE == "postgres":
        cur.execute(
            "INSERT INTO attendance (user_id, username, first_name, action, timestamp) VALUES (%s, %s, %s, %s, %s)",
            (user_id, username, first_name, action, ts),
        )
    else:
        cur.execute(
            "INSERT INTO attendance (user_id, username, first_name, action, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, first_name, action, ts),
        )
    conn.commit()
    conn.close()
    return ts


def get_today_record(user_id: int):
    """查询某用户今日打卡记录"""
    today = today_str()
    conn = get_conn()
    cur = conn.cursor()
    if DB_TYPE == "postgres":
        cur.execute(
            "SELECT action, timestamp FROM attendance WHERE user_id = %s AND timestamp LIKE %s ORDER BY timestamp",
            (user_id, f"{today}%"),
        )
    else:
        cur.execute(
            "SELECT action, timestamp FROM attendance WHERE user_id = ? AND timestamp LIKE ? ORDER BY timestamp",
            (user_id, f"{today}%"),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_records(user_id: int, days: int = 7):
    """查询某用户最近 N 天的打卡记录"""
    from_date = (datetime.now(TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_conn()
    cur = conn.cursor()
    if DB_TYPE == "postgres":
        cur.execute(
            "SELECT action, timestamp FROM attendance WHERE user_id = %s AND timestamp >= %s ORDER BY timestamp DESC",
            (user_id, from_date),
        )
    else:
        cur.execute(
            "SELECT action, timestamp FROM attendance WHERE user_id = ? AND timestamp >= ? ORDER BY timestamp DESC",
            (user_id, from_date),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_today_records():
    """管理员：查询今日所有人的打卡记录"""
    today = today_str()
    conn = get_conn()
    cur = conn.cursor()
    if DB_TYPE == "postgres":
        cur.execute(
            "SELECT user_id, username, first_name, action, timestamp FROM attendance WHERE timestamp LIKE %s ORDER BY timestamp",
            (f"{today}%",),
        )
    else:
        cur.execute(
            "SELECT user_id, username, first_name, action, timestamp FROM attendance WHERE timestamp LIKE ? ORDER BY timestamp",
            (f"{today}%",),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_summary(days: int = 30):
    """管理员：统计最近 N 天的考勤摘要"""
    from_date = (datetime.now(TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_conn()
    cur = conn.cursor()
    if DB_TYPE == "postgres":
        cur.execute(
            "SELECT user_id, username, first_name, action, DATE(timestamp) FROM attendance WHERE timestamp >= %s ORDER BY timestamp DESC",
            (from_date,),
        )
    else:
        cur.execute(
            "SELECT user_id, username, first_name, action, DATE(timestamp) FROM attendance WHERE timestamp >= ? ORDER BY timestamp DESC",
            (from_date,),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


# ==================== 按钮/菜单 ====================

def build_main_keyboard():
    """构建主菜单键盘"""
    keyboard = [
        [InlineKeyboardButton("🏢 上班打卡", callback_data="clock_in")],
        [InlineKeyboardButton("🏠 下班打卡", callback_data="clock_out")],
        [InlineKeyboardButton("📊 今日记录", callback_data="today")],
        [InlineKeyboardButton("📅 近7天记录", callback_data="week")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ==================== 命令处理 ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 命令"""
    await update.message.reply_text(
        "👋 欢迎使用考勤打卡机器人！\n\n"
        "使用下方按钮进行上下班打卡：\n"
        "🏢 上班打卡 — 记录上班时间\n"
        "🏠 下班打卡 — 记录下班时间\n"
        "📊 查看今日打卡记录\n"
        "📅 查看近7天记录\n\n"
        "管理员命令：\n"
        "/today_all — 今日全员记录\n"
        "/summary — 近30天统计\n\n"
        "其他命令：\n"
        "/menu — 显示主菜单\n"
        "/help — 查看帮助",
        reply_markup=build_main_keyboard(),
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示主菜单"""
    await update.message.reply_text("请选择操作：", reply_markup=build_main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示帮助信息"""
    await update.message.reply_text(
        "📖 <b>考勤打卡机器人使用帮助</b>\n\n"
        "<b>普通命令：</b>\n"
        "/start — 启动机器人\n"
        "/menu — 显示操作菜单\n"
        "/help — 显示此帮助\n\n"
        "<b>按钮操作：</b>\n"
        "🏢 上班打卡 — 点击记录上班时间\n"
        "🏠 下班打卡 — 点击记录下班时间（需先上班打卡）\n"
        "📊 今日记录 — 查看今天的打卡情况\n"
        "📅 近7天记录 — 查看最近一周打卡记录\n\n"
        "<b>管理员命令：</b>\n"
        "/today_all — 查看今日全员打卡情况\n"
        "/summary — 查看近30天考勤统计摘要\n\n"
        "💡 提示：首次使用请发送 /start 开始。\n"
        "📞 遇到了问题？请联系管理员。",
        parse_mode="HTML",
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理所有按钮回调"""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""

    if query.data == "clock_in":
        now = record_action(user_id, username, first_name, "in")
        await query.message.reply_text(
            f"✅ <b>{first_name}</b>，上班打卡成功！\n"
            f"🕐 打卡时间：{now}",
            reply_markup=build_main_keyboard(),
            parse_mode="HTML",
        )
        await query.edit_message_reply_markup(reply_markup=None)

    elif query.data == "clock_out":
        records = get_today_record(user_id)
        has_in = any(r[0] == "in" for r in records)
        if not has_in:
            await query.message.reply_text(
                "⚠️ 你今天还没有上班打卡，请先上班打卡！",
                reply_markup=build_main_keyboard(),
            )
            await query.edit_message_reply_markup(reply_markup=None)
            return

        now = record_action(user_id, username, first_name, "out")
        await query.message.reply_text(
            f"✅ <b>{first_name}</b>，下班打卡成功！\n"
            f"🕐 打卡时间：{now}",
            reply_markup=build_main_keyboard(),
            parse_mode="HTML",
        )
        await query.edit_message_reply_markup(reply_markup=None)

    elif query.data == "today":
        records = get_today_record(user_id)
        if not records:
            text = f"📭 <b>{first_name}</b>，今天还没有打卡记录。"
        else:
            text = f"📊 <b>{first_name}</b> 今日打卡记录：\n\n"
            for action, ts in records:
                emoji = "🏢" if action == "in" else "🏠"
                label = "上班" if action == "in" else "下班"
                text += f"{emoji} {label}：{ts}\n"
        await query.message.reply_text(
            text, reply_markup=build_main_keyboard(), parse_mode="HTML"
        )
        await query.edit_message_reply_markup(reply_markup=None)

    elif query.data == "week":
        records = get_user_records(user_id, days=7)
        if not records:
            text = f"📭 <b>{first_name}</b>，近7天没有打卡记录。"
        else:
            text = f"📅 <b>{first_name}</b> 近7天打卡记录：\n\n"
            for action, ts in records:
                emoji = "🏢" if action == "in" else "🏠"
                label = "上班" if action == "in" else "下班"
                text += f"{emoji} {label}：{ts}\n"
        await query.message.reply_text(
            text, reply_markup=build_main_keyboard(), parse_mode="HTML"
        )
        await query.edit_message_reply_markup(reply_markup=None)


async def today_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理员命令：查看今日全员打卡记录"""
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
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

    if len(text) > 4096:
        # 按聊天消息长度限制拆分
        for i in range(0, len(text), 4096):
            await update.message.reply_text(text[i:i+4096], parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理员命令：查看近30天考勤统计"""
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ 你没有管理员权限！")
        return

    rows = get_summary(days=30)
    if not rows:
        await update.message.reply_text("📭 近30天没有打卡记录。")
        return

    # 按用户统计
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
            1 for actions in data["days"].values()
            if "in" in actions and "out" in actions
        )
        text += (
            f"👤 <b>{data['name']}</b>\n"
            f"   出勤 {total_days} 天，正常上下班 {normal_days} 天\n\n"
        )

    if len(text) > 4096:
        for i in range(0, len(text), 4096):
            await update.message.reply_text(text[i:i+4096], parse_mode="HTML")
    else:
        await update.message.reply_text(text, parse_mode="HTML")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """错误处理"""
    logger.error(f"更新 {update} 时发生错误：{context.error}", exc_info=True)


# ==================== 主函数 ====================

def main():
    """启动机器人"""
    if not BOT_TOKEN:
        logger.error("未设置 BOT_TOKEN 环境变量！")
        sys.exit(1)

    if DB_TYPE == "postgres" and not DATABASE_URL:
        logger.error("使用 PostgreSQL 但未设置 DATABASE_URL 环境变量！")
        sys.exit(1)

    init_db()
    logger.info("数据库初始化完成（类型：%s）", DB_TYPE)

    app = Application.builder().token(BOT_TOKEN).build()

    # 注册命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("today_all", today_all))
    app.add_handler(CommandHandler("summary", summary))

    # 注册按钮回调
    app.add_handler(CallbackQueryHandler(button_handler))

    # 错误处理
    app.add_error_handler(error_handler)

    logger.info("考勤机器人已启动...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
