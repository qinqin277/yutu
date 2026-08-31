"""
数据库模块 - SQLite 持久化存储
"""
import sqlite3
import json
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from pathlib import Path

# 数据库路径
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "weread.db"


class Database:
    """数据库管理类（单例模式）"""

    _instance = None
    _conn = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._conn is None:
            self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._init_tables()

    def get_conn(self):
        return self._conn

    def _init_tables(self):
        """初始化所有表"""
        cursor = self._conn.cursor()

        # 1. 用户数据表（主表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id TEXT PRIMARY KEY,
                api_key TEXT,
                profile TEXT,
                personality TEXT,
                annual_goal INTEGER DEFAULT 50,
                monthly_goal INTEGER DEFAULT 4,
                last_refresh TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. 书架缓存表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shelf_cache (
                user_id TEXT PRIMARY KEY,
                catalog TEXT,
                shelf_info TEXT,
                reading_stats TEXT,
                notebooks_info TEXT,
                cached_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. 打卡记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkin_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                checkin_date TEXT NOT NULL,
                checked INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, checkin_date)
            )
        """)

        # 4. 对话历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 5. 每日一言缓存表（存储有划线的书籍列表）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quote_cache (
                user_id TEXT PRIMARY KEY,
                cache_key TEXT,
                books TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self._conn.commit()

    # ========== 用户数据操作 ==========

    def save_user_data(self, user_id: str, data: Dict[str, Any]) -> None:
        """保存用户数据"""
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO user_data (
                user_id, api_key, profile, personality, 
                annual_goal, monthly_goal, last_refresh, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            user_id,
            data.get('api_key', ''),
            json.dumps(data.get('profile', {}), ensure_ascii=False),
            json.dumps(data.get('personality', {}), ensure_ascii=False),
            data.get('annual_goal', 50),
            data.get('monthly_goal', 4),
            data.get('last_refresh')
        ))
        self._conn.commit()

    def get_user_data(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户数据"""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM user_data WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None

        result = dict(row)
        result['profile'] = json.loads(result['profile']) if result.get('profile') else {}
        result['personality'] = json.loads(result['personality']) if result.get('personality') else {}
        return result

    # ========== 书架缓存操作 ==========

    def save_shelf_cache(self, user_id: str, data: Dict[str, Any]) -> None:
        """保存书架缓存"""
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO shelf_cache (
                user_id, catalog, shelf_info, reading_stats, notebooks_info, cached_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            user_id,
            json.dumps(data.get('catalog', []), ensure_ascii=False),
            json.dumps(data.get('shelf_info', {}), ensure_ascii=False),
            json.dumps(data.get('reading_stats', {}), ensure_ascii=False),
            json.dumps(data.get('notebooks_info', {}), ensure_ascii=False)
        ))
        self._conn.commit()

    def get_shelf_cache(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取书架缓存"""
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM shelf_cache WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None

        return {
            'catalog': json.loads(row['catalog']) if row['catalog'] else [],
            'shelf_info': json.loads(row['shelf_info']) if row['shelf_info'] else {},
            'reading_stats': json.loads(row['reading_stats']) if row['reading_stats'] else {},
            'notebooks_info': json.loads(row['notebooks_info']) if row['notebooks_info'] else {},
            'cached_at': row['cached_at']
        }

    # ========== 打卡操作 ==========

    def get_checkin_history(self, user_id: str) -> Dict[str, bool]:
        """获取所有打卡记录"""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT checkin_date, checked FROM checkin_history WHERE user_id = ?",
            (user_id,)
        )
        rows = cursor.fetchall()
        return {row['checkin_date']: bool(row['checked']) for row in rows}

    def toggle_checkin(self, user_id: str, checkin_date: str, checked: bool = True) -> None:
        """设置打卡状态"""
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO checkin_history (user_id, checkin_date, checked)
            VALUES (?, ?, ?)
        """, (user_id, checkin_date, 1 if checked else 0))
        self._conn.commit()

    # ========== 对话操作 ==========

    def save_message(self, user_id: str, role: str, content: str) -> None:
        """保存对话消息"""
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT INTO messages (user_id, role, content)
            VALUES (?, ?, ?)
        """, (user_id, role, content))
        self._conn.commit()

    def get_messages(self, user_id: str, limit: int = 50) -> List[Dict[str, str]]:
        """获取对话历史"""
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT role, content FROM messages 
            WHERE user_id = ? 
            ORDER BY id DESC LIMIT ?
        """, (user_id, limit))
        rows = cursor.fetchall()
        return [dict(row) for row in reversed(rows)]

    def clear_messages(self, user_id: str) -> None:
        """清空对话"""
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        self._conn.commit()

    # ========== 每日一言缓存 ==========

    def save_quote_cache(self, user_id: str, cache_key: str, books: List[Dict]) -> None:
        """保存每日一言缓存"""
        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO quote_cache (user_id, cache_key, books, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (user_id, cache_key, json.dumps(books, ensure_ascii=False)))
        self._conn.commit()

    def get_quote_cache(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取每日一言缓存"""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT cache_key, books FROM quote_cache WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            'cache_key': row['cache_key'],
            'books': json.loads(row['books']) if row['books'] else []
        }

    def clear_quote_cache(self, user_id: str) -> None:
        """清空每日一言缓存"""
        cursor = self._conn.cursor()
        cursor.execute("DELETE FROM quote_cache WHERE user_id = ?", (user_id,))
        self._conn.commit()


# 全局数据库实例
db = Database()
