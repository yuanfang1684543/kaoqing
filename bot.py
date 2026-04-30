#!/usr/bin/env python3
"""Telegram 上下班打卡机器人

用法:
  1. 设置环境变量 TELEGRAM_BOT_TOKEN
  2. python bot.py

命令:
  /start       - 查看帮助
  /punchin     - 上班打卡
  /punchout    - 下班打卡
  /report      - 今日考勤日报
  /weekly      - 本周考勤周报
  /monthly     - 本月考勤月报
  /history     - 历史打卡记录
"""

import logging
import os
import sys
from datetime import date, datetime, timedelta

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 确保可以导入 attendance_bot 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from attendance_bot.storage import AttendanceStorage, get_data_dir
from attendance_bot.reporter import AttendanceReporter

# ── 配置 ──────────────────────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DATA_DIR = get_data_dir()
CHAT_IDS_FILE = os.path.join(DATA_DIR, "subscribed_chats.json")

# Logo / 启动问候
BOT_NAME = "\U0001f4cb 打卡机器人"
HELP_TEXT = (
    "\U0001f916 上下班打卡机器人\n"
    "\n"
    "\U0001f4cd 命令列表：\n"
    "  /punchin  \U0001f4e5 上班打卡\n"
    "  /punchout \U0001f4e4 下班打卡\n"
    "  /report   \U0001f4ca 今日考勤日报\n"
    "  /weekly   \U0001f4c5 本周考勤周报\n"
    "  /monthly  \U0001f5d3  本月考勤月报\n"
    "  /history  \U0001f4cb 历史打卡记录\n"
    "\n"
    "\U0001f514 每天 00:05 自动推送前一天的考勤日报"
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
storage = AttendanceStorage()
reporter = AttendanceReporter(storage)


# ── Chat ID 管理 ─────────────────────────────────────────────────────
def _load_subscribed_chats():
    """加载已订阅的 chat_id"""
    if not os.path.exists(CHAT_IDS_FILE):
        return []
    import json
    with open(CHAT_IDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_subscribed_chats(chat_ids):
    """保存已订阅的 chat_id"""
    import json
    os.makedirs(os.path.dirname(CHAT_IDS_FILE), exist_ok=True)
    with open(CHAT_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(chat_ids, f, ensure_ascii=False, indent=2)


def _subscribe_chat(chat_id: int):
    """订阅一个 chat_id（只增不删）"""
    ids = _load_subscribed_chats()
    if chat_id not in ids:
        ids.append(chat_id)
        _save_subscribed_chats(ids)
        logger.info("Subscribed new chat: %s", chat_id)


def _get_user_label(update) -> str:
    """获取用户显示名"""
    user = update.effective_user
    if user:
        return user.full_name or user.username or str(user.id)
    return "未知用户"


# ── 命令处理 ──────────────────────────────────────────────────────────
async def start(update, context):
    await update.message.reply_text(HELP_TEXT)


async def punch_in(update, context):
    user = _get_user_label(update)
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    success = storage.clock_in(now.date(), user)
    if success:
        await update.message.reply_text(
            f"\U00002705 {user} 上班打卡成功\n\U0001f4c5 {now.date()}  {time_str}"
        )
    else:
        await update.message.reply_text(
            f"\U000026a0 {user} 今天 ({now.date()}) 已经打过上班卡了"
        )


async def punch_out(update, context):
    user = _get_user_label(update)
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    success = storage.clock_out(now.date(), user)
    if success:
        await update.message.reply_text(
            f"\U00002705 {user} 下班打卡成功\n\U0001f4c5 {now.date()}  {time_str}"
        )
    else:
        await update.message.reply_text(
            f"\U000026a0 {user} 今天 ({now.date()}) 已经打过下班卡了"
        )


async def daily_report(update, context):
    _subscribe_chat(update.effective_chat.id)
    report = reporter.generate_daily_report(date.today())
    await update.message.reply_text(f"<code>{report}</code>", parse_mode="HTML")


async def weekly_report(update, context):
    report = reporter.generate_weekly_report()
    await update.message.reply_text(f"<code>{report}</code>", parse_mode="HTML")


async def monthly_report(update, context):
    today = date.today()
    report = reporter.generate_monthly_report(today.year, today.month)
    await update.message.reply_text(f"<code>{report}</code>", parse_mode="HTML")


async def history(update, context):
    records = storage.get_all_records()
    if not records:
        await update.message.reply_text("\U0001f4cb 暂无考勤记录")
        return

    lines = []
    lines.append("\U0001f4cb 考勤历史记录")
    lines.append("─" * 30)
    for day_key in sorted(records.keys(), reverse=True):
        day_data = records[day_key]
        for user, times in day_data.get("records", {}).items():
            in_time = times.get("clock_in", "--:--")
            out_time = times.get("clock_out", "--:--")
            lines.append(f"{day_key}  {user}: \U0001f4e5{in_time}  \U0001f4e4{out_time}")

    await update.message.reply_text("\n".join(lines))


# ── 定时任务：每天 00:05 推送前一天日报 ──────────────────────────
async def scheduled_daily_report(context):
    """在每天 00:05 自动发送前一天的考勤日报给所有已订阅的聊天"""
    yesterday = date.today() - timedelta(days=1)
    report = reporter.generate_daily_report(yesterday)
    chat_ids = _load_subscribed_chats()
    if not chat_ids:
        logger.warning("没有已订阅的 chat_id，无法发送日报")
        return
    for chat_id in chat_ids:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"<code>{report}</code>",
                parse_mode="HTML",
            )
            logger.info("日报已发送到 chat_id=%s", chat_id)
        except Exception as e:
            logger.error("发送日报到 chat_id=%s 失败: %s", chat_id, e)


# ── 错误处理 ──────────────────────────────────────────────────────────
async def error_handler(update, context):
    logger.error("异常: %s", context.error, exc_info=True)


# ── 主入口 ────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        print("错误: 请设置 Telegram Bot Token")
        print()
        print("方式一: 复制 .env.example 为 .env 并填入 Token")
        print("  cp .env.example .env")
        print("  编辑 .env 文件填入你的机器人 Token")
        print()
        print("方式二: 设置环境变量")
        print("  export TELEGRAM_BOT_TOKEN=你的机器人Token")
        print()
        print("获取 Token: 在 Telegram 中找 @BotFather 创建机器人")
        sys.exit(1)

    from telegram.ext import ApplicationBuilder, CommandHandler

    app = (ApplicationBuilder()
           .token(TOKEN)
           .build())

    # 注册命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("punchin", punch_in))
    app.add_handler(CommandHandler("punchout", punch_out))
    app.add_handler(CommandHandler("report", daily_report))
    app.add_handler(CommandHandler("weekly", weekly_report))
    app.add_handler(CommandHandler("monthly", monthly_report))
    app.add_handler(CommandHandler("history", history))

    # 错误处理
    app.add_error_handler(error_handler)

    # 定时任务：每天 00:05 发送前一天的日报
    # 使用 UTC+8 时区
    import pytz
    tz = pytz.timezone("Asia/Shanghai")
    app.job_queue.run_daily(
        scheduled_daily_report,
        time=datetime.strptime("00:05", "%H:%M").time(),
        days=tuple(range(7)),  # 每天
        name="daily_report_job",
    )

    logger.info("\U0001f680 打卡机器人已启动...")
    app.run_polling()


if __name__ == "__main__":
    main()
