from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class R3ManualDetectionSecurityTest(unittest.TestCase):
    def test_v2_routes_have_atomic_permissions_before_authenticated_fallback(self) -> None:
        source = (ROOT / "services/business-api/src/main/java/com/tooldefect/business/identity/infrastructure/SecurityConfiguration.java").read_text(encoding="utf-8")
        self.assertIn('.securityMatcher("/api/v1/**", "/api/v2/**")', source)
        fallback = source.rindex(".anyRequest().authenticated()")
        for permission in ("manual-detection:read", "manual-detection:read:all", "manual-detection:write"):
            self.assertLess(source.index(permission), fallback)

    def test_repository_scopes_reads_and_writes_to_owner(self) -> None:
        source = (ROOT / "services/business-api/src/main/java/com/tooldefect/business/detectionbatch/infrastructure/JdbcManualDetectionRepository.java").read_text(encoding="utf-8")
        self.assertIn("b.created_by = ?", source)
        self.assertIn("(? OR created_by = ?)", source)
        self.assertIn("(? OR b.created_by=?)", source)

    def test_v2_errors_use_frozen_error_code_shape(self) -> None:
        source = (ROOT / "services/business-api/src/main/java/com/tooldefect/business/shared/api/StandardErrorFactory.java").read_text(encoding="utf-8")
        self.assertIn('startsWith("/api/v2/")', source)
        self.assertIn('"error_code", code', source)
        self.assertIn('"details", Map.of()', source)


if __name__ == "__main__":
    unittest.main()
