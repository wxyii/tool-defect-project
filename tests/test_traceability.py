import json
from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

from tools.baseline.hardcoded_scan import scan_hardcoded_site_parameters
from tools.traceability.build_matrix import (
    build_matrix,
    discover_tests,
    validate_matrix,
)


class TraceabilityTests(unittest.TestCase):
    """验证 P0-03 的 14 文档覆盖、稳定编号和测试反向链接。"""

    @classmethod
    def setUpClass(cls):
        cls.first = build_matrix(PROJECT_ROOT)
        cls.second = build_matrix(PROJECT_ROOT)
        cls.lock = json.loads(
            (
                PROJECT_ROOT / "Docs/traceability/matrix-lock.json"
            ).read_text(encoding="utf-8")
        )

    def test_matrix_generation_is_deterministic(self):
        self.assertEqual(self.first, self.second)
        self.assertEqual(355, self.first["requirement_count"])
        self.assertEqual(
            "dd73a39ef9c6ea413678bc8f8f5c3d451756c840e7fc5577670b42228506c803",
            self.first["stable_requirements_sha256"],
        )

    def test_all_fourteen_design_documents_are_covered(self):
        self.assertEqual(
            {f"{number:02d}" for number in range(1, 15)},
            set(self.first["documents"]),
        )
        for document in self.first["documents"].values():
            self.assertGreater(document["requirement_count"], 0)
            self.assertRegex(document["source_sha256"], r"^[0-9a-f]{64}$")

    def test_every_requirement_has_stable_source_task_gate_and_verification(self):
        identifiers = set()
        valid_kinds = {"任务自动化验证", "人工验收", "现场决策"}
        for requirement in self.first["requirements"]:
            self.assertRegex(
                requirement["id"],
                r"^REQ-(0[1-9]|1[0-4])-[0-9A-F]{12}$",
            )
            self.assertNotIn(requirement["id"], identifiers)
            identifiers.add(requirement["id"])
            source = requirement["source"]
            self.assertTrue((PROJECT_ROOT / source["document"]).is_file())
            self.assertGreater(source["line"], 0)
            self.assertNotEqual("", source["section"])
            self.assertNotEqual("", requirement["text"])
            self.assertTrue(requirement["tasks"])
            self.assertTrue(requirement["gates"])
            self.assertIn(requirement["verification_kind"], valid_kinds)
            self.assertTrue(requirement["verification_refs"])
            if requirement["go_live_prerequisite"]:
                self.assertTrue(requirement["gates"])

    def test_all_discovered_tests_reverse_link_to_known_requirements(self):
        known_ids = {
            requirement["id"]
            for requirement in self.first["requirements"]
        }
        discovered = {item["id"] for item in discover_tests(PROJECT_ROOT)}
        linked = {item["test_id"] for item in self.first["test_links"]}
        self.assertEqual(discovered, linked)
        for link in self.first["test_links"]:
            self.assertTrue(link["requirement_ids"])
            self.assertTrue(
                set(link["requirement_ids"]).issubset(known_ids)
            )

    def test_matrix_has_no_unassigned_requirement_or_source_drift(self):
        self.assertEqual(
            [],
            validate_matrix(PROJECT_ROOT, self.first, self.lock),
        )

    def test_site_decision_links_point_to_registered_decisions(self):
        registry = json.loads(
            (
                PROJECT_ROOT
                / "Docs/decisions/site-parameter-decisions.json"
            ).read_text(encoding="utf-8")
        )
        decision_ids = {item["id"] for item in registry["decisions"]}
        site_links = set()
        for requirement in self.first["requirements"]:
            if requirement["verification_kind"] == "现场决策":
                site_links.update(requirement["verification_refs"])
        self.assertTrue(site_links)
        self.assertTrue(site_links.issubset(decision_ids))

    def test_production_rules_have_document_sources_and_no_hardcoded_orphans(self):
        registry = json.loads(
            (
                PROJECT_ROOT
                / "Docs/decisions/site-parameter-decisions.json"
            ).read_text(encoding="utf-8")
        )
        source_pattern = re.compile(
            r"^Docs/(?:README|(?:0[1-9]|1[0-4])-.+)\.md#"
        )
        for decision in registry["decisions"]:
            self.assertTrue(decision["source_refs"])
            for source_ref in decision["source_refs"]:
                self.assertRegex(source_ref, source_pattern)
        self.assertEqual([], scan_hardcoded_site_parameters(PROJECT_ROOT))


if __name__ == "__main__":
    unittest.main()
