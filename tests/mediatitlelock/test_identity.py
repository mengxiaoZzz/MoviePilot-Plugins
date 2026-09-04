import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins.v2" / "mediatitlelock"))

from identity import (
    apply_locked_title,
    extract_media_identity,
)


class IdentityTest(unittest.TestCase):
    def test_extract_media_identity_prefers_unified_source_and_id(self):
        media = SimpleNamespace(
            source="themoviedb",
            media_id="330150",
            type=SimpleNamespace(value="电视剧"),
            tmdb_id=999,
            douban_id=None,
            bangumi_id=None,
            anilist_id=None,
        )

        identity = extract_media_identity(media)

        self.assertEqual(identity.media_source, "themoviedb")
        self.assertEqual(identity.media_id, "330150")

    def test_extract_media_identity_falls_back_to_tmdb_id(self):
        media = SimpleNamespace(
            source=None,
            media_id=None,
            type="电影",
            tmdb_id=1280738,
            douban_id=None,
            bangumi_id=None,
            anilist_id=None,
        )

        identity = extract_media_identity(media)

        self.assertEqual(identity.media_source, "themoviedb")
        self.assertEqual(identity.media_id, "1280738")

    def test_apply_locked_title_updates_title_year_consistently(self):
        rename_dict = {"title": "新标题", "year": "2026", "title_year": "新标题 (2026)"}

        apply_locked_title(rename_dict, "首次入库标题", "2025")

        self.assertEqual(rename_dict["title"], "首次入库标题")
        self.assertEqual(rename_dict["year"], "2025")
        self.assertEqual(rename_dict["title_year"], "首次入库标题 (2025)")

if __name__ == "__main__":
    unittest.main()
