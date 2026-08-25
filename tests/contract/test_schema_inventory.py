import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SchemaInventoryTests(unittest.TestCase):
    def test_required_schema_groups_exist(self):
        expected = {
            "meeting": 3,
            "transcript": 1,
            "summary": 1,
            "result": 2,
            "observability": 4,
        }
        for group, count in expected.items():
            files = list((ROOT / "schemas" / group).glob("*.schema.json"))
            self.assertEqual(len(files), count, group)

    def test_observability_schema_versions_match_runtime_contract(self):
        expected = {
            "run-event.v1.schema.json": "run-event.v1",
            "run-manifest.v1.schema.json": "run-manifest.v1",
            "run-metrics.v1.schema.json": "run-metrics.v1",
            "error-report.v1.schema.json": "error-report.v1",
        }
        for name, version in expected.items():
            data = json.loads((ROOT / "schemas" / "observability" / name).read_text(encoding="utf-8"))
            self.assertEqual(data["properties"]["schema_version"]["const"], version)


if __name__ == "__main__":
    unittest.main()
