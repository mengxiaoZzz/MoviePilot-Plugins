import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins.v2" / "mediatitlelock"))

from database import BindingStore, TitleBinding


def binding(title="首次标题", origin="automatic"):
    return TitleBinding(
        media_source="themoviedb",
        media_type="电视剧",
        media_id="330150",
        canonical_title=title,
        canonical_year="2026",
        media_root_name=f"{title} (2026)",
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

        saved = self.store.get("themoviedb", "电视剧", "330150")
        self.assertEqual(saved.canonical_title, "首次标题")
        self.assertEqual(self.store.count(), 1)

    def test_manual_upsert_can_replace_existing_binding(self):
        self.store.insert_if_absent(binding())

        self.assertTrue(self.store.upsert(binding("人工固定标题", "manual")))

        saved = self.store.get("themoviedb", "电视剧", "330150")
        self.assertEqual(saved.canonical_title, "人工固定标题")
        self.assertEqual(saved.origin, "manual")

    def test_movie_and_series_with_same_source_id_do_not_conflict(self):
        self.store.insert_if_absent(binding())
        movie = TitleBinding(
            media_source="themoviedb",
            media_type="电影",
            media_id="330150",
            canonical_title="同号电影",
            origin="manual",
        )

        self.assertTrue(self.store.insert_if_absent(movie))
        self.assertEqual(self.store.count(), 2)

    def test_delete_reports_affected_row_and_clears_cache(self):
        self.store.insert_if_absent(binding())

        self.assertTrue(self.store.delete("themoviedb", "电视剧", "330150"))
        self.assertFalse(self.store.delete("themoviedb", "电视剧", "330150"))
        self.assertIsNone(self.store.get("themoviedb", "电视剧", "330150"))


if __name__ == "__main__":
    unittest.main()
