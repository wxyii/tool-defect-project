import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_resolves_project_relative_paths(self):
        """Catches reintroduction of machine-specific D-drive paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config_dir = project_root / "configs"
            config_dir.mkdir()
            config_path = config_dir / "default.json"
            config_path.write_text(
                json.dumps(
                    {
                        "paths": {
                            "data": "data",
                            "classification_model": "artifacts/classification",
                        },
                        "image_size": 256,
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(project_root / "data", config.path("data"))
            self.assertEqual(
                project_root / "artifacts/classification",
                config.path("classification_model"),
            )
            self.assertEqual(256, config.image_size)

    def test_load_config_rejects_absolute_project_paths(self):
        """Catches non-portable configuration tied to the original workstation."""
        absolute_paths = ("D:/chedao/yuan", r"\\fileserver\share\images", "/data/images")
        for absolute_path in absolute_paths:
            with self.subTest(absolute_path=absolute_path):
                with tempfile.TemporaryDirectory() as temp_dir:
                    config_path = Path(temp_dir) / "default.json"
                    config_path.write_text(
                        json.dumps(
                            {"paths": {"data": absolute_path}, "image_size": 256}
                        ),
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ValueError, "relative"):
                        load_config(config_path)


if __name__ == "__main__":
    unittest.main()
