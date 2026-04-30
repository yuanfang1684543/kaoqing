"""
Telegram 考勤打卡机器人
功能：上下班打卡、日报/周报/月报、管理员面板、个人设置
支持 SQLite（本地）和 PostgreSQL（Railway 生产环境）
"""

import os
import sys
import json
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

# ---------- 时区 ----------
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Shanghai")
except ImportError:
    TZ = None
    logger.warning("zoneinfo 不可用，使用 UTC+8 固定偏移")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ---------- 配置 ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = set(int(uid) for uid in os.environ.get("ADMIN_IDS", "").split(",") if uid)
DB_TYPE = os.environ.get("DB_TYPE", "sqlite").lower()
DB_PATH = os.environ.get("DB_PATH", "attendance.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")


# ==================== 时间工具 ====================

def now_str() -> str:
    if TZ: return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

def today_str() -> str:
    if TZ: return datetime.now(TZ).strftime("%Y-%m-%d")
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")

def week_range_str() -> tuple:
    """返回本周一的日期字符串和今天"""
    if TZ: today = datetime.now(TZ)
    else: today = datetime.utcnow() + timedelta(hours=8)
    monday = today - timedelta(days=today.weekday())
    return monday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")

def month_str() -> str:
    if TZ: return datetime.now(TZ).strftime("%Y-%m")
    return (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m")

CN_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


# ==================== 数据库操作 ====================

def get_conn():
    if DB_TYPE == "postgres":
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_PATH)

def _q(sql: str) -> str:
    return sql.replace("?", "%s") if DB_TYPE == "postgres" else sql

def _pg_date(sql: str) -> str:
    """PostgreSQL 的 DATE() 兼容"""
    if DB_TYPE == "postgres":
        return sql.replace("DATE(", "DATE(")
    return sql

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    q = _q
    if DB_TYPE == "postgres":
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_attendance_user_date ON attendance (user_id, timestamp)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id    BIGINT PRIMARY KEY,
                username   TEXT,
                first_name TEXT,
                reminder   INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id    INTEGER PRIMARY KEY,
                username   TEXT,
                first_name TEXT,
                reminder   INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
    conn.commit()
    conn.close()
    logger.info("数据库初始化完成（类型：%s）", DB_TYPE)


# ---------- 考勤 CRUD ----------

def record_action(user_id: int, username: str, first_name: str, action: str) -> str:
    ts = now_str()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(_q("INSERT INTO attendance (user_id, username, first_name, action, timestamp) VALUES (?, ?, ?, ?, ?)"),
                (user_id, username, first_name, action, ts))
    conn.commit()
    conn.close()
    return ts


def get_records(user_id: int, from_date: str = None, to_date: str = None):
    """通用查询，可指定日期范围"""
    conn = get_conn()
    cur = conn.cursor()
    if from_date and to_date:
        cur.execute(_q("SELECT action, timestamp FROM attendance WHERE user_id = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp"),
                    (user_id, from_date, to_date + " 23:59:59"))
    elif from_date:
        cur.execute(_q("SELECT action, timestamp FROM attendance WHERE user_id = ? AND timestamp >= ? ORDER BY timestamp DESC"),
                    (user_id, from_date))
    else:
        today = today_str()
        cur.execute(_q("SELECT action, timestamp FROM attendance WHERE user_id = ? AND timestamp LIKE ? ORDER BY timestamp"),
                    (user_id, f"{today}%"))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_users_records(from_date: str, to_date: str = None):
    """管理员：查询所有用户在日期范围内的记录"""
    conn = get_conn()
    cur = conn.cursor()
    if to_date:
        cur.execute(_q("SELECT user_id, username, first_name, action, timestamp FROM attendance WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp"),
                    (from_date, to_date + " 23:59:59"))
    else:
        cur.execute(_q("SELECT user_id, username, first_name, action, timestamp FROM attendance WHERE timestamp LIKE ? ORDER BY timestamp"),
                    (f"{from_date}%",))
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------- 用户偏好 ----------

def get_user_prefs(user_id: int, username: str, first_name: str) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(_q("SELECT * FROM user_prefs WHERE user_id = ?"), (user_id,))
    row = cur.fetchone()
    now = now_str()
    if not row:
        cur.execute(_q("INSERT INTO user_prefs (user_id, username, first_name, reminder, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)"),
                    (user_id, username, first_name, now, now))
        conn.commit()
        cur.execute(_q("SELECT * FROM user_prefs WHERE user_id = ?"), (user_id,))
        row = cur.fetchone()
    conn.close()
    cols = ["user_id", "username", "first_name", "reminder", "created_at", "updated_at"]
    return dict(zip(cols, row))


def toggle_reminder(user_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(_q("SELECT reminder FROM user_prefs WHERE user_id = ?"), (user_id,))
    row = cur.fetchone()
    new_val = 0 if row and row[0] == 1 else 1
    cur.execute(_q("UPDATE user_prefs SET reminder = ?, updated_at = ? WHERE user_id = ?"), (new_val, now_str(), user_id))
    conn.commit()
    conn.close()
    return bool(new_val)


# ==================== 报表生成 ====================

def format_records_table(records, title: str) -> str:
    """将打卡记录格式化为美观表格"""
    if not records:
        return f"📭 {title}\n\n暂无打卡记录。"
    lines = [f"📋 <b>{title}</b>\n", "━" * 30]
    for action, ts in records:
        date_part = ts[:10]
        time_part = ts[11:19]
        emoji = "🏢" if action == "in" else "🏠"
        label = "上班" if action == "in" else "下班"
        lines.append(f"{emoji} {date_part}  {label}  {time_part}")
    lines.append("━" * 30)
    return "\n".join(lines)


def build_daily_report(user_id: int, first_name: str) -> str:
    """生成个人日报"""
    records = get_records(user_id, today_str())
    title = f"{first_name} · 今日考勤日报"
    return format_records_table(records, title)


def build_weekly_report(user_id: int, first_name: str) -> str:
    """生成个人周报（本周一到今天）"""
    mon, today = week_range_str()
    records = get_records(user_id, mon)
    if not records:
        return f"📭 <b>{first_name}</b> · 本周考勤周报\n\n本周暂无打卡记录。"
    title = f"{first_name} · 本周考勤周报（{mon} ~ {today}）"
    # 按天分组
    days = {}
    for action, ts in records:
        d = ts[:10]
        if d not in days:
            days[d] = {}
        days[d][action] = ts[11:19]
    lines = [f"📋 <b>{title}</b>\n", "━" * 30]
    for d in sorted(days.keys(), reverse=True):
        acts = days[d]
        wd = datetime.strptime(d, "%Y-%m-%d").weekday()
        cw = CN_WEEKDAYS[wd]
        clock_in = acts.get("in", "—")
        clock_out = acts.get("out", "—")
        if clock_in != "—" and clock_out != "—":
            status = "✅"
        elif clock_in != "—":
            status = "⚠️"
        else:
            status = "❌"
        lines.append(f"{status} {d} {cw}")
        lines.append(f"   🏢 上班 {clock_in}  🏠 下班 {clock_out}")
    lines.append("━" * 30)
    # 统计
    total = len(days)
    normal = sum(1 for a in days.values() if "in" in a and "out" in a)
    late = sum(1 for a in days.values() if "in" in a and "out" not in a)
    lines.append(f"📊 出勤 {total} 天 | 正常 {normal} 天 | 异常 {late} 天")
    return "\n".join(lines)


def build_monthly_report(user_id: int, first_name: str) -> str:
    """生成个人月报"""
    month = month_str()
    records = get_records(user_id, month + "-01")
    if not records:
        return f"📭 <b>{first_name}</b> · {month} 月考勤月报\n\n本月暂无打卡记录。"
    title = f"{first_name} · {month} 月考勤月报"
    days = {}
    for action, ts in records:
        d = ts[:10]
        if d not in days:
            days[d] = {}
        days[d][action] = ts[11:19]
    lines = [f"📋 <b>{title}</b>\n", "━" * 30]
    for d in sorted(days.keys(), reverse=True):
        acts = days[d]
        clock_in = acts.get("in", "—")
        clock_out = acts.get("out", "—")
        if clock_in != "—" and clock_out != "—":
            status = "✅"
        elif clock_in != "—":
            status = "⚠️"
        else:
            status = "❌"
        lines.append(f"{status} {d}  🏢{clock_in}  🏠{clock_out}")
    lines.append("━" * 30)
    total = len(days)
    normal = sum(1 for a in days.values() if "in" in a and "out" in a)
    lines.append(f"📊 出勤 {total} 天 | 正常 {normal} 天")
    return "\n".join(lines)


def build_admin_daily_report() -> str:
    """管理员日报：今日全员打卡"""
    today = today_str()
    records = get_all_users_records(today)
    if not records:
        return "📭 今日全员日报\n\n今天还没有任何人打卡。"
    users = {}
    for uid, uname, fname, action, ts in records:
        name = fname or uname or str(uid)
        if name not in users:
            users[name] = {}
        users[name][action] = ts[11:19]
    lines = [f"📋 <b>今日全员考勤日报（{today}）</b>\n", "━" * 30]
    for name in sorted(users.keys()):
        acts = users[name]
        ci = acts.get("in", "—")
        co = acts.get("out", "—")
        if ci != "—" and co != "—":
            status = "✅"
        elif ci != "—":
            status = "⚠️"
        else:
            status = "❌"
        lines.append(f"{status} {name}  🏢{ci}  🏠{co}")
    lines.append("━" * 30)
    total = len(users)
    normal = sum(1 for a in users.values() if "in" in a and "out" in a)
    lines.append(f"👥 总人数 {total} | 已正常上下班 {normal} 人")
    return "\n".join(lines)


def build_admin_weekly_report() -> str:
    """管理员周报：本周全员打卡"""
    mon, today = week_range_str()
    records = get_all_users_records(mon, today)
    if not records:
        return f"📭 本周全员周报（{mon} ~ {today}）\n\n本周暂无打卡记录。"
    user_days = {}
    for uid, uname, fname, action, ts in records:
        name = fname or uname or str(uid)
        d = ts[:10]
        if name not in user_days:
            user_days[name] = {}
        if d not in user_days[name]:
            user_days[name][d] = set()
        user_days[name][d].add(action)
    lines = [f"📋 <b>本周全员考勤周报（{mon} ~ {today}）</b>\n", "━" * 30]
    for name in sorted(user_days.keys()):
        days_data = user_days[name]
        total = len(days_data)
        normal = sum(1 for acts in days_data.values() if "in" in acts and "out" in acts)
        lines.append(f"👤 {name}  出勤 {total} 天 | 正常 {normal} 天")
    return "\n".join(lines)


def build_admin_summary_report(days: int = 30) -> str:
    """管理员统计报表"""
    from_date = (datetime.now(TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    records = get_all_users_records(from_date)
    if not records:
        return f"📭 近 {days} 天没有打卡记录。"
    stats = {}
    for uid, uname, fname, action, ts in records:
        name = fname or uname or str(uid)
        d = ts[:10]
        if name not in stats:
            stats[name] = {}
        if d not in stats[name]:
            stats[name][d] = set()
        stats[name][d].add(action)
    lines = [f"📊 <b>近 {days} 天考勤统计报表</b>\n", "━" * 30]
    for name in sorted(stats.keys()):
        total = len(stats[name])
        normal = sum(1 for a in stats[name].values() if "in" in a and "out" in a)
        lines.append(f"👤 {name}")
        lines.append(f"   出勤 {total} 天 | 正常 {normal} 天")
    return "\n".join(lines)


# ==================== 键盘构建 ====================

def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)

def main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """输入框下方的持久回复键盘"""
    kb = [
        ["🏢 上班打卡", "🏠 下班打卡"],
        ["📋 日报", "📋 周报", "📋 月报"],
        ["⚙️ 设置"],
    ]
    if is_admin:
        kb.append(["👑 管理员面板"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, is_persistent=True)

def admin_keyboard() -> InlineKeyboardMarkup:
    """管理员内联键盘（子菜单）"""
    kb = [
        [btn("📋 今日日报", "admin_daily")],
        [btn("📋 本周周报", "admin_weekly")],
        [btn("📊 近30天统计", "admin_summary_report")],
        [btn("👥 今日全员打卡", "admin_today_all")],
        [btn("🔙 返回主菜单", "main_menu")],
    ]
    return InlineKeyboardMarkup(kb)

def settings_keyboard(reminder_on: bool) -> InlineKeyboardMarkup:
    """设置内联键盘（子菜单）"""
    label = "✅ 打卡提醒已开启" if reminder_on else "❌ 打卡提醒已关闭"
    kb = [
        [btn(label, "toggle_reminder")],
        [btn("🔙 返回主菜单", "main_menu")],
    ]
    return InlineKeyboardMarkup(kb)


# ==================== 命令处理 ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_admin = user.id in ADMIN_IDS
    await update.message.reply_text(
        "👋 欢迎使用考勤打卡机器人！\n\n"
        "📌 使用下方按键操作：\n"
        "🏢 上班打卡 / 🏠 下班打卡\n"
        "📋 日报 / 周报 / 月报\n"
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
        "<b>输入框下方按键：</b>\n"
        "🏢 上班打卡 — 记录上班时间\n"
        "🏠 下班打卡 — 需先上班打卡\n"
        "📋 日报 — 今日打卡明细\n"
        "📋 周报 — 本周打卡情况\n"
        "📋 月报 — 本月打卡统计\n"
        "⚙️ 设置 — 开启/关闭提醒\n"
        "👑 管理员面板（管理员可见）\n\n"
        "<b>管理员命令：</b>\n"
        "/today_all — 今日全员记录\n"
        "/summary — 近30天统计\n\n"
        "/start — 启动机器人\n"
        "/menu — 显示主菜单",
        parse_mode="HTML",
    )


# ==================== 按钮回调处理 ====================

# ==================== 回复键盘点击处理（输入框下方的按键）====================

REPLY_KEYS = {
    "🏢 上班打卡": "clock_in",
    "🏠 下班打卡": "clock_out",
    "📋 日报": "report_daily",
    "📋 周报": "report_weekly",
    "📋 月报": "report_monthly",
    "⚙️ 设置": "settings",
    "👑 管理员面板": "admin_panel",
}

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理输入框下方回复键盘的点击"""
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    is_admin = user_id in ADMIN_IDS
    text = update.message.text.strip()

    action = REPLY_KEYS.get(text)
    if not action:
        return

    if action == "clock_in":
        now = record_action(user_id, username, first_name, "in")
        await update.message.reply_text(
            f"✅ <b>{first_name}</b>，上班打卡成功！\n🕐 {now}",
            reply_markup=main_keyboard(is_admin), parse_mode="HTML",
        )

    elif action == "clock_out":
        records = get_records(user_id)
        has_in = any(r[0] == "in" for r in records)
        if not has_in:
            await update.message.reply_text("⚠️ 今天还没有上班打卡，请先上班打卡！", reply_markup=main_keyboard(is_admin))
            return
        now = record_action(user_id, username, first_name, "out")
        await update.message.reply_text(
            f"✅ <b>{first_name}</b>，下班打卡成功！\n🕐 {now}",
            reply_markup=main_keyboard(is_admin), parse_mode="HTML",
        )

    elif action == "report_daily":
        report = build_daily_report(user_id, first_name)
        await update.message.reply_text(report, reply_markup=main_keyboard(is_admin), parse_mode="HTML")

    elif action == "report_weekly":
        report = build_weekly_report(user_id, first_name)
        await update.message.reply_text(report, reply_markup=main_keyboard(is_admin), parse_mode="HTML")

    elif action == "report_monthly":
        report = build_monthly_report(user_id, first_name)
        await update.message.reply_text(report, reply_markup=main_keyboard(is_admin), parse_mode="HTML")

    elif action == "settings":
        prefs = get_user_prefs(user_id, username, first_name)
        await update.message.reply_text(
            f"⚙️ <b>{first_name}</b> 的个人设置",
            reply_markup=settings_keyboard(prefs["reminder"]), parse_mode="HTML",
        )

    elif action == "admin_panel":
        if not is_admin:
            await update.message.reply_text("⛔ 你没有管理员权限！", reply_markup=main_keyboard(False))
            return
        await update.message.reply_text("👑 <b>管理员面板</b>", reply_markup=admin_keyboard(), parse_mode="HTML")


# ==================== 内联按钮回调处理（子菜单）====================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理内联键盘按钮（设置、管理员面板等子菜单）"""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    is_admin = user_id in ADMIN_IDS
    data = query.data

    if data == "main_menu":
        await query.message.reply_text("📌 请选择操作：", reply_markup=main_keyboard(is_admin))
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "toggle_reminder":
        new_state = toggle_reminder(user_id)
        status = "开启" if new_state else "关闭"
        await query.message.reply_text(
            f"✅ 打卡提醒已{status}！", reply_markup=settings_keyboard(new_state),
        )
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "admin_daily":
        if not is_admin: return
        report = build_admin_daily_report()
        await query.message.reply_text(report, reply_markup=admin_keyboard(), parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "admin_weekly":
        if not is_admin: return
        report = build_admin_weekly_report()
        await query.message.reply_text(report, reply_markup=admin_keyboard(), parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "admin_summary_report":
        if not is_admin: return
        report = build_admin_summary_report(30)
        await query.message.reply_text(report, reply_markup=admin_keyboard(), parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=None)

    elif data == "admin_today_all":
        if not is_admin: return
        today = today_str()
        records = get_all_users_records(today)
        if not records:
            await query.message.reply_text("📭 今天还没有任何人打卡。", reply_markup=admin_keyboard())
            await query.edit_message_reply_markup(reply_markup=None)
            return
        lines = ["📊 <b>今日全员打卡明细：</b>\n", "━" * 30]
        for uid, uname, fname, action, ts in records:
            display = fname or uname or str(uid)
            emoji = "🏢" if action == "in" else "🏠"
            label = "上班" if action == "in" else "下班"
            lines.append(f"{emoji} {display} — {label}：{ts[11:19]}")
        await query.message.reply_text("\n".join(lines), reply_markup=admin_keyboard(), parse_mode="HTML")
        await query.edit_message_reply_markup(reply_markup=None)


# ==================== 命令兼容 ====================

async def today_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ 你没有管理员权限！")
        return
    report = build_admin_daily_report()
    is_admin = user_id in ADMIN_IDS
    await update.message.reply_text(report, reply_markup=main_keyboard(is_admin) if is_admin else None, parse_mode="HTML")

async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ 你没有管理员权限！")
        return
    report = build_admin_summary_report(30)
    is_admin = user_id in ADMIN_IDS
    await update.message.reply_text(report, reply_markup=main_keyboard(is_admin) if is_admin else None, parse_mode="HTML")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"更新 {update} 发生错误：{context.error}", exc_info=True)


# ==================== Health Check ====================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "attendance-bot"}).encode())
    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("健康检查 HTTP 服务已启动，端口：%d", port)


# ==================== 主函数 ====================

def main():
    if not BOT_TOKEN:
        logger.error("未设置 BOT_TOKEN 环境变量！")
        sys.exit(1)
    if DB_TYPE == "postgres" and not DATABASE_URL:
        logger.error("使用 PostgreSQL 但未设置 DATABASE_URL！")
        sys.exit(1)

    start_health_server()
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("today_all", today_all))
    app.add_handler(CommandHandler("summary", summary_cmd))

    # 回复键盘（输入框下方的按键）→ 放在命令后面，避免抢命令
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_handler))

    # 内联按钮（子菜单）
    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_error_handler(error_handler)

    logger.info("考勤机器人已启动...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
