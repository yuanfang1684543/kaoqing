"""考勤报表生成模块"""

from datetime import date, timedelta
from typing import Dict, List, Optional

from .storage import AttendanceStorage


class AttendanceReporter:
    """考勤报表生成器"""

    def __init__(self, storage: AttendanceStorage):
        self.storage = storage

    def generate_daily_report(self, dt: date) -> str:
        """生成某一天的考勤报表"""
        summary = self.storage.get_today_summary(dt)
        lines = []
        lines.append("=" * 50)
        lines.append(f"      【考勤日报】{dt.isoformat()}")
        lines.append("=" * 50)

        if not summary:
            lines.append("  今日暂无考勤记录")
        else:
            header = f"{'姓名':<10} {'上班':<10} {'下班':<10} {'状态':<8}"
            lines.append(header)
            lines.append("-" * 40)
            for s in summary:
                lines.append(
                    f"{s['user']:<10} {s['clock_in']:<10} {s['clock_out']:<10} {s['status']:<8}"
                )

        lines.append("=" * 50)
        # 统计
        if summary:
            total = len(summary)
            normal = sum(1 for s in summary if s["status"] == "正常")
            abnormal = total - normal
            lines.append(f"  出勤: {total}人 | 正常: {normal}人 | 异常: {abnormal}人")

        lines.append("=" * 50)
        return "\n".join(lines)

    def generate_weekly_report(self, end_date: Optional[date] = None) -> str:
        """生成最近一周的考勤报表"""
        if end_date is None:
            end_date = date.today()
        start_date = end_date - timedelta(days=6)

        records = self.storage.get_records_by_date_range(start_date, end_date)

        lines = []
        lines.append("=" * 60)
        lines.append(f"      【考勤周报】{start_date.isoformat()} ~ {end_date.isoformat()}")
        lines.append("=" * 60)

        if not records:
            lines.append("  本周暂无考勤记录")
        else:
            # 收集所有用户
            users = set()
            for day_record in records.values():
                users.update(day_record.get("records", {}).keys())
            users = sorted(users)

            for user in users:
                lines.append(f"\n  [{user}]")
                for i in range(7):
                    day = start_date + timedelta(days=i)
                    key = day.isoformat()
                    day_data = records.get(key, {})
                    user_record = day_data.get("records", {}).get(user, {})
                    has_in = "clock_in" in user_record
                    has_out = "clock_out" in user_record
                    in_time = user_record.get("clock_in", "--:--")
                    out_time = user_record.get("clock_out", "--:--")
                    weekday = ["一", "二", "三", "四", "五", "六", "日"][day.weekday()]
                    status_mark = "✓" if has_in and has_out else "△" if has_in or has_out else "✗"
                    lines.append(f"    {key}(周{weekday}) {in_time} ~ {out_time} {status_mark}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def generate_monthly_report(self, year: int, month: int) -> str:
        """生成月度考勤报表"""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        records = self.storage.get_records_by_date_range(start_date, end_date)

        lines = []
        lines.append("=" * 70)
        lines.append(f"      【考勤月报】{year}年{month}月")
        lines.append("=" * 70)

        if not records:
            lines.append("  本月暂无考勤记录")
        else:
            users = set()
            for day_record in records.values():
                users.update(day_record.get("records", {}).keys())
            users = sorted(users)

            for user in users:
                lines.append(f"\n  [{user}]")
                total_days = 0
                normal_days = 0
                for i in range((end_date - start_date).days + 1):
                    day = start_date + timedelta(days=i)
                    key = day.isoformat()
                    day_data = records.get(key, {})
                    user_record = day_data.get("records", {}).get(user, {})
                    has_in = "clock_in" in user_record
                    has_out = "clock_out" in user_record
                    if has_in and has_out:
                        normal_days += 1
                        total_days += 1
                    elif has_in or has_out:
                        total_days += 1

                lines.append(f"    出勤天数: {total_days}天 | 正常: {normal_days}天 | 异常: {total_days - normal_days}天")

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)
