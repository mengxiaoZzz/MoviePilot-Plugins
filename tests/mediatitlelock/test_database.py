import sqlite3
import tempfile
import sys
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins.v2" / "mediatitlelock"))

from database import (
    BindingStore,
    CATEGORY_MIGRATION_BACKUP_SUFFIX,
    MIGRATION_BACKUP_SUFFIX,
    TitleBinding,
)


def binding(title="首次标题", origin="automatic"):
    return TitleBinding(
        media_source="themoviedb",
        media_id="330150",
        canonical_title=title,
        canonical_year="2026",
        media_category="日韩剧",
        origin=origin,
    )


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = BindingStore(Path(self.temporary_directory.name) / "bindings.sqlite3")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_first_successful_binding_wins(self):
        self.assertTrue(self.store.insert_if_absent(binding()))
        self.assertFalse(self.store.insert_if_absent(binding("TMDB 后续标题")))

        saved = self.store.get("themoviedb", "330150")
        self.assertEqual(saved.canonical_title, "首次标题")
        self.assertEqual(self.store.count(), 1)

    def test_manual_upsert_can_replace_existing_binding(self):
        self.store.insert_if_absent(binding())

        self.assertTrue(self.store.upsert(binding("人工固定标题", "manual")))

        saved = self.store.get("themoviedb", "330150")
        self.assertEqual(saved.canonical_title, "人工固定标题")
        self.assertEqual(saved.origin, "manual")

    def test_source_and_id_are_the_unique_key(self):
        self.store.insert_if_absent(binding())
        same_identity = TitleBinding(
            media_source="themoviedb",
            media_id="330150",
            canonical_title="另一个标题",
            origin="manual",
        )

        self.assertFalse(self.store.insert_if_absent(same_identity))
        self.assertEqual(self.store.count(), 1)

    def test_delete_reports_affected_row_and_clears_cache(self):
        self.store.insert_if_absent(binding())

        self.assertTrue(self.store.delete("themoviedb", "330150"))
        self.assertFalse(self.store.delete("themoviedb", "330150"))
        self.assertIsNone(self.store.get("themoviedb", "330150"))

    def test_list_can_filter_by_tmdbid_and_title(self):
        self.store.insert_if_absent(binding())
        self.store.insert_if_absent(
            TitleBinding(
                media_source="douban",
                media_id="123456",
                canonical_title="另一部影片",
                media_category="华语电影",
            )
        )

        by_tmdbid = self.store.list_bindings(tmdbid="015")
        by_title = self.store.list_bindings(title="另一部")

        self.assertEqual([item.media_id for item in by_tmdbid], ["330150"])
        self.assertEqual([item.media_id for item in by_title], ["123456"])
        self.assertEqual(self.store.count(tmdbid="015"), 1)
        self.assertEqual(self.store.count(title="另一部"), 1)

    def test_server_pagination_reaches_records_beyond_500_without_duplicates(self):
        for index in range(626):
            self.store.insert_if_absent(replace(binding(), media_id=str(index)))
        ids = []
        for page in range(1, 27):
            result = self.store.paginate(page=page, page_size=25)
            self.assertEqual(result.total, 626)
            self.assertEqual(result.page_count, 26)
            ids.extend(item.media_id for item in result.items)
        self.assertEqual(len(ids), 626)
        self.assertEqual(len(set(ids)), 626)

    def test_server_pagination_clamps_pages_and_filters_before_counting(self):
        self.store.insert_if_absent(binding())
        result = self.store.paginate(page=99, page_size=25, title="首次")
        self.assertEqual((result.page, result.total), (1, 1))
        empty = self.store.paginate(page=9, page_size=25, title="不存在")
        self.assertEqual((empty.page, empty.page_count, empty.total), (1, 1, 0))
        self.assertEqual(empty.items, [])
        bounded = self.store.paginate(page=-1, page_size=999999)
        self.assertEqual((bounded.page, bounded.page_size), (1, 100))

    def test_page_order_uses_existing_index_without_a_temporary_sort(self):
        with self.store._connect() as connection:
            plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM title_bindings "
                "ORDER BY updated_at DESC, rowid ASC LIMIT 25 OFFSET 500"
            ).fetchall()
        details = " ".join(row["detail"] for row in plan)
        self.assertIn("idx_title_bindings_updated_at", details)
        self.assertNotIn("TEMP B-TREE", details)

    def test_legacy_database_migrates_and_keeps_latest_duplicate(self):
        self.temporary_directory.cleanup()
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE title_bindings (
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
            rows = [
                ("themoviedb", "电影", "42", "较早标题", "2025", "", "manual", "", "", "", "2026-01-01 00:00:00", "2026-01-01 00:00:00"),
                ("themoviedb", "电视剧", "42", "较新标题", "2026", "", "manual", "", "", "", "2026-01-02 00:00:00", "2026-01-02 00:00:00"),
            ]
            connection.executemany(
                "INSERT INTO title_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            connection.commit()

        migrated = BindingStore(database_path)

        self.assertEqual(migrated.count(), 1)
        self.assertEqual(migrated.get("themoviedb", "42").canonical_title, "较新标题")
        self.assertTrue(Path(f"{database_path}{MIGRATION_BACKUP_SUFFIX}").is_file())
        with closing(sqlite3.connect(database_path)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(title_bindings)")}
        self.assertNotIn("media_type", columns)
        self.assertIn("media_category", columns)
        self.assertEqual(migrated.get("themoviedb", "42").media_category, "")

    def test_existing_database_adds_category_column_and_creates_backup(self):
        self.temporary_directory.cleanup()
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "current.sqlite3"
        with closing(sqlite3.connect(database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE title_bindings (
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
            connection.execute(
                "INSERT INTO title_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "themoviedb",
                    "42",
                    "旧记录",
                    "2026",
                    "旧根目录",
                    "manual",
                    "",
                    "",
                    "",
                    "2026-09-04 00:00:00",
                    "2026-09-04 00:00:00",
                ),
            )
            connection.commit()

        migrated = BindingStore(database_path)

        self.assertEqual(migrated.get("themoviedb", "42").media_category, "")
        self.assertTrue(
            Path(f"{database_path}{CATEGORY_MIGRATION_BACKUP_SUFFIX}").is_file()
        )


if __name__ == "__main__":
    unittest.main()
