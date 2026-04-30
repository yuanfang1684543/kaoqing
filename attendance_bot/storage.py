"""数据持久化模块 - 使用 JSON 文件存储考勤数据"""

import json
import os
from datetime import date
from typing import Dict, List, Optional

def get_data_dir() -> str:
    """获取数据目录（支持通过环境变量 DATA_DIR 自定义）"""
    return os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))


class AttendanceStorage:
    """考勤数据存储管理"""

    def __init__(self, file_path: str = ""):
        if not file_path:
            file_path = os.path.join(get_data_dir(), "attendance.json")
        self.file_path = file_path
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        """确保数据目录存在"""
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def _load_all(self) -> Dict[str, Dict]:
        """加载全部考勤数据"""
        if not os.path.exists(self.file_path):
            return {}
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_all(self, data: Dict[str, Dict]):
        """保存全部考勤数据"""
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_date_key(self, dt: date) -> str:
        """获取日期键值"""
        return dt.isoformat()

    def get_attendance(self, dt: date) -> Optional[Dict]:
        """获取指定日期的考勤记录"""
        data = self._load_all()
        key = self.get_date_key(dt)
        return data.get(key)

    def clock_in(self, dt: date, time_str: str, user: str = "default") -> bool:
        """上班打卡"""
        data = self._load_all()
        key = self.get_date_key(dt)
        if key not in data:
            data[key] = {"date": key, "records": {}}
        if user not in data[key]["records"]:
            data[key]["records"][user] = {}
        record = data[key]["records"][user]
        if "clock_in" in record:
            return False  # 已打过上班卡
        record["clock_in"] = time_str
        self._save_all(data)
        return True

    def clock_out(self, dt: date, time_str: str, user: str = "default") -> bool:
        """下班打卡"""
        data = self._load_all()
        key = self.get_date_key(dt)
        if key not in data:
            data[key] = {"date": key, "records": {}}
        if user not in data[key]["records"]:
            data[key]["records"][user] = {}
        record = data[key]["records"][user]
        if "clock_out" in record:
            return False  # 已打过下班卡
        record["clock_out"] = time_str
        self._save_all(data)
        return True

    def get_all_records(self) -> Dict[str, Dict]:
        """获取所有考勤记录"""
        return self._load_all()

    def get_records_by_date_range(self, start_date: date, end_date: date) -> Dict[str, Dict]:
        """获取日期范围内的考勤记录"""
        all_data = self._load_all()
        result = {}
        from datetime import timedelta
        current = start_date
        while current <= end_date:
            key = self.get_date_key(current)
            if key in all_data:
                result[key] = all_data[key]
            current += timedelta(days=1)
        return result

    def get_today_summary(self, dt: date) -> List[Dict]:
        """获取当日考勤汇总"""
        record = self.get_attendance(dt)
        if not record:
            return []
        summary = []
        for user, times in record.get("records", {}).items():
            summary.append({
                "user": user,
                "clock_in": times.get("clock_in", "未打卡"),
                "clock_out": times.get("clock_out", "未打卡"),
                "status": self._evaluate_status(times),
            })
        return summary

    @staticmethod
    def _evaluate_status(times: Dict) -> str:
        """评估考勤状态"""
        has_in = "clock_in" in times
        has_out = "clock_out" in times
        if has_in and has_out:
            return "正常"
        elif has_in:
            return "未签退"
        elif has_out:
            return "未签到"
        return "缺卡"
