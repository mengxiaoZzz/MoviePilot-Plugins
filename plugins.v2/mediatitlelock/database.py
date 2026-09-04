import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class TitleBinding:
    """固定标题绑定记录。"""

    media_source: str
    media_type: str
    media_id: str
    canonical_title: str
    canonical_year: str = ""
    media_root_name: str = ""
    origin: str = "automatic"
    server_name: str = ""
    server_item_id: str = ""
    media_path: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        """转换为接口和页面可使用的字典。"""

        return asdict(self)


class BindingStore:
    """使用插件私有 SQLite 文件保存标题绑定。"""

    def __init__(self, database_path: Path):
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = {}
        self._lock = threading.RLock()
        self._initialize()
        self.reload_cache()

    @staticmethod
    def _key(media_source: str, media_type: str, media_id: str) -> tuple:
        return media_source, media_type, media_id

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS title_bindings (
                    media_source TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    media_id TEXT NOT NULL,
                    canonical_title TEXT NOT NULL,
                    canonical_year TEXT NOT NULL DEFAULT '',
                    media_root_name TEXT NOT NULL DEFAULT '',
                    origin TEXT NOT NULL,
                    server_name TEXT NOT NULL DEFAULT '',
                    server_item_id TEXT NOT NULL DEFAULT '',
                    media_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (media_source, media_type, media_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_title_bindings_updated_at "
                "ON title_bindings(updated_at DESC)"
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TitleBinding:
        return TitleBinding(**dict(row))

    def reload_cache(self) -> None:
        """从数据库重新加载内存缓存。"""

        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM title_bindings").fetchall()
            self._cache = {
                self._key(row["media_source"], row["media_type"], row["media_id"]): self._from_row(row)
                for row in rows
            }

    def get(self, media_source: str, media_type: str, media_id: str) -> Optional[TitleBinding]:
        """读取一条标题绑定。"""

        with self._lock:
            return self._cache.get(self._key(media_source, media_type, media_id))

    def insert_if_absent(self, binding: TitleBinding) -> bool:
        """仅在身份尚未绑定时写入，保证首次成功整理的标题优先。"""

        now = datetime.now().strftime(TIME_FORMAT)
        values = (
            binding.media_source,
            binding.media_type,
            binding.media_id,
            binding.canonical_title,
            binding.canonical_year,
            binding.media_root_name,
            binding.origin,
            binding.server_name,
            binding.server_item_id,
            binding.media_path,
            binding.created_at or now,
            now,
        )
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO title_bindings (
                    media_source, media_type, media_id, canonical_title,
                    canonical_year, media_root_name, origin, server_name,
                    server_item_id, media_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            inserted = cursor.rowcount == 1
            if inserted:
                row = connection.execute(
                    "SELECT * FROM title_bindings WHERE media_source = ? AND media_type = ? AND media_id = ?",
                    (binding.media_source, binding.media_type, binding.media_id),
                ).fetchone()
                self._cache[self._key(binding.media_source, binding.media_type, binding.media_id)] = self._from_row(row)
            return inserted

    def upsert(self, binding: TitleBinding) -> bool:
        """新增或覆盖一条人工标题绑定。"""

        now = datetime.now().strftime(TIME_FORMAT)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO title_bindings (
                    media_source, media_type, media_id, canonical_title,
                    canonical_year, media_root_name, origin, server_name,
                    server_item_id, media_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_source, media_type, media_id) DO UPDATE SET
                    canonical_title = excluded.canonical_title,
                    canonical_year = excluded.canonical_year,
                    media_root_name = excluded.media_root_name,
                    origin = excluded.origin,
                    server_name = excluded.server_name,
                    server_item_id = excluded.server_item_id,
                    media_path = excluded.media_path,
                    updated_at = excluded.updated_at
                """,
                (
                    binding.media_source,
                    binding.media_type,
                    binding.media_id,
                    binding.canonical_title,
                    binding.canonical_year,
                    binding.media_root_name,
                    binding.origin,
                    binding.server_name,
                    binding.server_item_id,
                    binding.media_path,
                    binding.created_at or now,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                return False
            row = connection.execute(
                "SELECT * FROM title_bindings WHERE media_source = ? AND media_type = ? AND media_id = ?",
                (binding.media_source, binding.media_type, binding.media_id),
            ).fetchone()
            self._cache[self._key(binding.media_source, binding.media_type, binding.media_id)] = self._from_row(row)
            return True

    def delete(self, media_source: str, media_type: str, media_id: str) -> bool:
        """删除一条标题绑定并返回是否影响了数据库记录。"""

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM title_bindings WHERE media_source = ? AND media_type = ? AND media_id = ?",
                (media_source, media_type, media_id),
            )
            deleted = cursor.rowcount == 1
            if deleted:
                self._cache.pop(self._key(media_source, media_type, media_id), None)
            return deleted

    def list_bindings(self, limit: int = 500) -> List[TitleBinding]:
        """按更新时间倒序返回绑定记录。"""

        safe_limit = min(max(int(limit), 1), 5000)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM title_bindings ORDER BY updated_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def count(self) -> int:
        """返回绑定总数。"""

        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM title_bindings").fetchone()
        return int(row["total"])

    def clear_cache(self) -> None:
        """释放插件停止后不再使用的内存缓存。"""

        with self._lock:
            self._cache.clear()
