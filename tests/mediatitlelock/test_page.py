"""Run the Vue interaction regressions as part of the existing unittest suite."""

import shutil
import subprocess
import unittest
from pathlib import Path


repository = Path(__file__).resolve().parents[2]


@unittest.skipUnless(
    shutil.which("node")
    and (repository / "plugins.v2/mediatitlelock/node_modules/vue").is_dir(),
    "Frontend tests require Node.js and the plugin's existing npm dependencies",
)
class PageTest(unittest.TestCase):
    def test_page_interactions(self):
        result = subprocess.run(
            ["node", "--test", str(Path(__file__).with_name("page.test.mjs"))],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
