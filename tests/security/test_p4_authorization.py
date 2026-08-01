from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class P4AuthorizationTest(unittest.TestCase):
    def test_review_operations_require_atomic_scopes(self) -> None:
        contract = json.loads(
            (ROOT / "contracts/openapi/tool-defect-api-v1.json").read_text(
                encoding="utf-8"
            )
        )
        expected = {
            "listReviewTasks": "review:read",
            "getReviewWorkspace": "review:read",
            "claimReviewTask": "review:claim",
            "releaseReviewTask": "review:claim",
            "submitReview": "review:submit",
            "createAnnotationUploadTicket": "review:annotate",
            "completeReviewAnnotation": "review:annotate",
        }
        actual: set[str] = set()
        for path in contract["paths"].values():
            for operation in path.values():
                if not isinstance(operation, dict):
                    continue
                operation_id = operation.get("operationId")
                if operation_id in expected:
                    self.assertEqual(
                        [{"UserSession": []}],
                        operation["security"],
                    )
                    actual.add(operation_id)
        self.assertEqual(set(expected), actual)

    def test_http_security_enforces_review_scopes_before_fallback(self) -> None:
        source = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business/identity/"
            "infrastructure/SecurityConfiguration.java"
        ).read_text(encoding="utf-8")
        fallback = source.rindex(".anyRequest().authenticated()")
        for authority in (
            "review:read",
            "review:claim",
            "review:submit",
            "review:annotate",
        ):
            self.assertGreater(fallback, source.index(authority))
        self.assertIn('"/api/v1/review-tasks/*"', source)

    def test_system_operator_has_all_personnel_permissions(self) -> None:
        matrix = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business/identity/"
            "domain/RolePermissionMatrix.java"
        ).read_text(encoding="utf-8")

        def permissions(role: str) -> set[str]:
            match = re.search(
                rf"SystemRole\.{role},\s*Set\.of\((.*?)\)\s*\)",
                matrix,
                re.DOTALL,
            )
            self.assertIsNotNone(match, role)
            return set(re.findall(r'"([^"]+)"', match.group(1)))

        system_operator = permissions("SYSTEM_OPERATOR")
        self.assertNotIn("review:submit", permissions("OPERATOR"))
        self.assertNotIn("quality:override", permissions("ALGORITHM_ENGINEER"))
        self.assertNotIn("review:claim", permissions("AUDITOR"))
        self.assertNotIn("image:original:download", permissions("AUDITOR"))
        self.assertIn("dataset:approve", permissions("QUALITY_MANAGER"))
        self.assertTrue({
            "capture:read",
            "detection:read",
            "image:view",
            "image:original:download",
            "review:read",
            "review:claim",
            "review:submit",
            "review:annotate",
            "review:escalate",
            "quality:override",
            "quality:read",
            "dataset:approve",
            "dataset:create",
            "training:create",
            "training:read",
            "model:register",
            "model:validate",
            "model:deploy:approve",
            "model:rollback",
            "device:configure",
            "user:manage",
            "model:deploy:execute",
            "certificate:manage",
            "security:policy:manage",
            "audit:read",
        }.issubset(system_operator))

        migration = (
            ROOT
            / "services/business-api/src/main/resources/db/migration/"
            "V13__system_operator_full_permissions.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("role.role_code = 'SYSTEM_OPERATOR'", migration)
        self.assertIn("CROSS JOIN sys_permission permission", migration)

    def test_review_audit_and_training_decisions_are_append_only(self) -> None:
        migration = (
            ROOT
            / "services/business-api/src/main/resources/db/migration/"
            "V5__auditable_human_review_loop.sql"
        ).read_text(encoding="utf-8")
        audit = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business/audit/"
            "infrastructure/JdbcAuditTrail.java"
        ).read_text(encoding="utf-8")
        self.assertIn("trg_review_training_decision_append_only", migration)
        self.assertIn("td_reject_fact_mutation()", migration)
        self.assertIn("INSERT INTO audit_log", audit)
        self.assertIn("request_id", audit)
        self.assertIn("trace_id", audit)
        self.assertNotRegex(audit, r"\b(?:UPDATE|DELETE)\s+audit_log\b")

    def test_frontend_does_not_persist_images_or_signed_urls_in_review_drafts(self) -> None:
        source = (
            ROOT
            / "apps/web-console/src/components/image-workbench/mask-history.ts"
        ).read_text(encoding="utf-8")
        self.assertIn("strokes", source)
        self.assertNotIn("sourceUrl", source)
        self.assertNotIn("overlayUrl", source)
        self.assertNotIn("signed", source.lower())


if __name__ == "__main__":
    unittest.main()
