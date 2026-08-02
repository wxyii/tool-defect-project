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
    """验证 01—14 与 DOC-16 的稳定编号、任务、验收和测试反向链接。"""

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
        self.assertEqual(
            self.lock["requirement_count"],
            self.first["requirement_count"],
        )
        self.assertEqual(
            self.lock["stable_requirements_sha256"],
            self.first["stable_requirements_sha256"],
        )

    def test_doc16_product_requirements_have_stable_tasks_and_p0_acceptance(self):
        self.assertEqual(
            self.lock["product_requirement_count"],
            self.first["product_requirement_count"],
        )
        self.assertEqual(
            self.lock["p0_product_requirement_count"],
            self.first["p0_product_requirement_count"],
        )
        product_ids = set()
        tracking_ids = set()
        acceptance_ids = {
            item["id"] for item in self.first["acceptance_scenarios"]
        }
        for requirement in self.first["product_requirements"]:
            self.assertRegex(
                requirement["product_id"],
                r"^(?:FR-[A-Z]+|NFR-[A-Z]+|MIG)-\d{3}$",
            )
            self.assertRegex(
                requirement["tracking_id"],
                r"^REQ-DOC-16-[0-9A-F]{12}$",
            )
            self.assertNotIn(requirement["product_id"], product_ids)
            self.assertNotIn(requirement["tracking_id"], tracking_ids)
            product_ids.add(requirement["product_id"])
            tracking_ids.add(requirement["tracking_id"])
            self.assertTrue(requirement["tasks"])
            self.assertTrue(all(task.startswith("R") for task in requirement["tasks"]))
            if requirement["priority"] == "P0":
                self.assertTrue(requirement["acceptance_refs"])
                self.assertTrue(
                    set(requirement["acceptance_refs"]).issubset(acceptance_ids)
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

    def test_r0_baselines_close_from_confirmed_non_use(self):
        runtime = json.loads(
            (PROJECT_ROOT / "Docs/baseline/R0-v1-runtime-inventory.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("PASS", runtime["overall_status"])
        self.assertEqual("CONFIRMED", runtime["non_use_declaration"]["status"])
        self.assertTrue(
            (PROJECT_ROOT / runtime["non_use_declaration"]["evidence_ref"]).is_file()
        )
        self.assertTrue(runtime["source_scan"]["consistent"])
        self.assertEqual(
            runtime["source_scan"]["scan_1_sha256"],
            runtime["source_scan"]["scan_2_sha256"],
        )
        for consumer in runtime["consumers"]:
            self.assertTrue(consumer["consumer_id"])
            self.assertTrue(consumer["owner"])
            self.assertTrue(consumer["version"])
            self.assertIn("migration_status", consumer)
            self.assertIn("last_call_evidence", consumer)
            self.assertIn("telemetry_source", consumer)
            self.assertEqual("NEVER_CALLED", consumer["last_call_evidence"]["status"])
            self.assertEqual(
                "NOT_APPLICABLE_NEVER_DEPLOYED",
                consumer["telemetry_source"]["status"],
            )
            self.assertEqual("PASS", consumer["gate_status"])

        cancellation = json.loads(
            (PROJECT_ROOT / "Docs/baseline/R0-cancellation-inventory.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("ACCEPTED_BY_ADR", cancellation["approval_status"])
        for item in cancellation["items"]:
            self.assertTrue(item["current_consumers"])
            self.assertTrue(item["historical_retention"])
            self.assertTrue(item["retirement_tasks"])
        self.assertEqual(
            "PASS",
            cancellation["verification"]["runtime_zero_call_status"],
        )

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
