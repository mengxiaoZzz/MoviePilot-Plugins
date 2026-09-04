import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MIGRATION_BACKUP_SUFFIX = ".before-source-id-v2.bak"


@dataclass(frozen=True)
class TitleBinding:
    """固定标题绑定记录。"""

    media_source: str
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
    def _key(media_source: str, media_id: str) -> tuple:
        return media_source, media_id

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @staticmethod
    def _create_table(connection: sqlite3.Connection, table_name: str = "title_bindings") -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                media_source TEXT NOT NULL,
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
                PRIMARY KEY (media_source, media_id)
            )
            """
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(title_bindings)").fetchall()
            }
            if "media_type" in columns:
                self._backup_before_migration(connection)
                self._migrate_legacy_schema(connection)
            else:
                self._create_table(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_title_bindings_updated_at "
                "ON title_bindings(updated_at DESC)"
            )

    def _backup_before_migration(self, connection: sqlite3.Connection) -> None:
        backup_path = Path(f"{self._database_path}{MIGRATION_BACKUP_SUFFIX}")
        if backup_path.exists():
            return
        with sqlite3.connect(backup_path) as backup_connection:
            connection.backup(backup_connection)

    def _migrate_legacy_schema(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT * FROM title_bindings ORDER BY updated_at ASC, rowid ASC"
        ).fetchall()
        connection.execute("DROP TABLE IF EXISTS title_bindings_source_id")
        self._create_table(connection, "title_bindings_source_id")
        for row in rows:
            connection.execute(
                """
                INSERT OR REPLACE INTO title_bindings_source_id (
                    media_source, media_id, canonical_title, canonical_year,
                    media_root_name, origin, server_name, server_item_id,
                    media_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["media_source"],
                    row["media_id"],
                    row["canonical_title"],
                    row["canonical_year"],
                    row["media_root_name"],
                    row["origin"],
                    row["server_name"],
                    row["server_item_id"],
                    row["media_path"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        connection.execute("DROP TABLE title_bindings")
        connection.execute(
            "ALTER TABLE title_bindings_source_id RENAME TO title_bindings"
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> TitleBinding:
        return TitleBinding(**dict(row))

    def reload_cache(self) -> None:
        """从数据库重新加载内存缓存。"""

        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM title_bindings").fetchall()
            self._cache = {
                self._key(row["media_source"], row["media_id"]): self._from_row(row)
                for row in rows
            }

    def get(self, media_source: str, media_id: str) -> Optional[TitleBinding]:
        """读取一条标题绑定。"""

        with self._lock:
            return self._cache.get(self._key(media_source, media_id))

    def insert_if_absent(self, binding: TitleBinding) -> bool:
        """仅在身份尚未绑定时写入，保证首次成功整理的标题优先。"""

        now = datetime.now().strftime(TIME_FORMAT)
        values = (
            binding.media_source,
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
                    media_source, media_id, canonical_title, canonical_year,
                    media_root_name, origin, server_name, server_item_id,
                    media_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            inserted = cursor.rowcount == 1
            if inserted:
                self._refresh_cached_binding(connection, binding.media_source, binding.media_id)
            return inserted

    def upsert(self, binding: TitleBinding) -> bool:
        """新增或覆盖一条人工标题绑定。"""

        now = datetime.now().strftime(TIME_FORMAT)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO title_bindings (
                    media_source, media_id, canonical_title, canonical_year,
                    media_root_name, origin, server_name, server_item_id,
                    media_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(media_source, media_id) DO UPDATE SET
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
            self._refresh_cached_binding(connection, binding.media_source, binding.media_id)
            return True

    def _refresh_cached_binding(
        self,
        connection: sqlite3.Connection,
        media_source: str,
        media_id: str,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM title_bindings WHERE media_source = ? AND media_id = ?",
            (media_source, media_id),
        ).fetchone()
        self._cache[self._key(media_source, media_id)] = self._from_row(row)

    def delete(self, media_source: str, media_id: str) -> bool:
        """删除一条标题绑定并返回是否影响了数据库记录。"""

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM title_bindings WHERE media_source = ? AND media_id = ?",
                (media_source, media_id),
            )
            deleted = cursor.rowcount == 1
            if deleted:
                self._cache.pop(self._key(media_source, media_id), None)
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
