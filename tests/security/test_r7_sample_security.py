from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class R7SampleSecurityTest(unittest.TestCase):
    def test_r7_routes_are_admin_atomic_permissions_before_fallback(self) -> None:
        source = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business/identity/infrastructure/SecurityConfiguration.java"
        ).read_text(encoding="utf-8")
        fallback = source.rindex(".anyRequest().authenticated()")
        for route in (
            '"/api/v2/admin/detection-items"',
            '"/api/v2/sample-candidates"',
            '"/api/v2/sample-exports/*"',
            '"/api/v2/admin/detection-items/*/feedback"',
            '"/api/v2/sample-candidates/*/decision"',
            '"/api/v2/sample-exports"',
            '"/api/v2/sample-exports/*/download-ticket"',
        ):
            self.assertLess(source.index(route), fallback)
        for permission in (
            "sample:read",
            "sample:feedback",
            "sample:candidate:write",
            "sample:export",
            "sample:export:download",
        ):
            self.assertLess(source.index(permission), fallback)

    def test_only_administrator_has_r7_permissions_and_feature_is_disabled_by_default(self) -> None:
        matrix = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business/identity/domain/RolePermissionMatrix.java"
        ).read_text(encoding="utf-8")
        properties = (
            ROOT
            / "services/business-api/src/main/resources/application.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn('"sample:read"', matrix)
        self.assertIn('"sample:external-receipt"', matrix)
        administrator = matrix.index('SystemRole.ADMINISTRATOR')
        employee = matrix.index('SystemRole.PRODUCTION_EMPLOYEE')
        sample_start = matrix.index('"sample:read"')
        self.assertLess(administrator, sample_start)
        self.assertNotIn('"sample:read"', matrix[employee:administrator])
        self.assertIn('"sample:external-receipt"', matrix[administrator:])
        self.assertIn("sample-export:", properties)
        self.assertIn("TD_SAMPLE_EXPORT_ENABLED:false", properties)

    def test_sample_module_does_not_depend_on_dataset_or_training_facts(self) -> None:
        module = ROOT / "services/business-api/src/main/java/com/tooldefect/business/sample"
        source = "\n".join(path.read_text(encoding="utf-8") for path in module.rglob("*.java"))
        self.assertNotIn("dataset_version_id", source)
        self.assertNotIn("training_run_id", source)
        self.assertNotIn("com.tooldefect.business.training", source)


if __name__ == "__main__":
    unittest.main()
