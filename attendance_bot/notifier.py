"""通知/输出模块 - 将考勤报表输出到不同渠道（控制台，可扩展 Webhook）"""

from datetime import date
from typing import Optional

from .storage import AttendanceStorage
from .reporter import AttendanceReporter


class ConsoleNotifier:
    """控制台输出通知器"""

    def __init__(self, storage: AttendanceStorage):
        self.storage = storage
        self.reporter = AttendanceReporter(storage)

    def send_daily_report(self, dt: Optional[date] = None):
        """在控制台输出日报"""
        if dt is None:
            dt = date.today()
        report = self.reporter.generate_daily_report(dt)
        print(report)
        print()

    def send_weekly_report(self, end_date: Optional[date] = None):
        """在控制台输出周报"""
        report = self.reporter.generate_weekly_report(end_date)
        print(report)
        print()

    def send_monthly_report(self, year: int, month: int):
        """在控制台输出月报"""
        report = self.reporter.generate_monthly_report(year, month)
        print(report)
        print()


# --- 可扩展的 Webhook 通知器示例 ---
# class WebhookNotifier:
#     """支持发送到企业微信/钉钉/Slack 等平台"""
#
#     def __init__(self, storage: AttendanceStorage, webhook_url: str):
#         self.storage = storage
#         self.reporter = AttendanceReporter(storage)
#         self.webhook_url = webhook_url
#
#     def _send_to_webhook(self, message: str):
#         """发送消息到 Webhook"""
#         import requests
#         payload = {"msgtype": "text", "text": {"content": message}}
#         requests.post(self.webhook_url, json=payload)
#
#     def send_daily_report(self, dt: Optional[date] = None):
#         if dt is None:
#             dt = date.today()
#         report = self.reporter.generate_daily_report(dt)
#         self._send_to_webhook(report)
