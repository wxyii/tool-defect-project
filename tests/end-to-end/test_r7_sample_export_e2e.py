from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class R7SampleExportE2ETest(unittest.TestCase):
    def test_admin_filter_feedback_candidate_export_download_surfaces_are_connected(self) -> None:
        routes = (ROOT / "apps/web-console/src/router/routes.ts").read_text(encoding="utf-8")
        client = (ROOT / "apps/web-console/src/api/client.ts").read_text(encoding="utf-8")
        view = (ROOT / "apps/web-console/src/features/sample-library/SampleLibraryView.vue").read_text(encoding="utf-8")
        controller = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business/sample/api/SampleLibraryController.java"
        ).read_text(encoding="utf-8")
        self.assertIn("/sample-library", routes)
        self.assertIn("permissions: ['sample:read']", routes)
        for operation in (
            "listAdminDetectionItemsV2",
            "createAdminFeedbackV2",
            "listSampleCandidatesV2",
            "createSampleCandidateV2",
            "decideSampleCandidateV2",
            "createSampleExportV2",
            "getSampleExportV2",
            "createSampleExportDownloadTicketV2",
        ):
            self.assertIn(operation, client)
        for marker in (
            "saveFeedback",
            "createCandidate",
            "decideCandidate",
            "createExport",
            "issueDownload",
            "failedCandidateIds",
        ):
            self.assertIn(marker, view)
        for route in (
            '@GetMapping("/admin/detection-items")',
            '@PostMapping("/admin/detection-items/{item_id}/feedback")',
            '@PostMapping("/sample-candidates")',
            '@PostMapping("/sample-exports")',
            '@PostMapping("/sample-exports/{export_job_id}/download-ticket")',
        ):
            self.assertIn(route, controller)

    def test_r7_does_not_create_dataset_or_training_facts(self) -> None:
        files = [
            ROOT / "jobs/sample-export-worker/worker.py",
            ROOT / "services/business-api/src/main/java/com/tooldefect/business/sample/application/SampleLibraryService.java",
            ROOT / "services/business-api/src/main/resources/db/migration/V20__r7_sample_library_and_exports.sql",
        ]
        source = "\n".join(path.read_text(encoding="utf-8") for path in files)
        self.assertNotIn("dataset_version_id", source)
        self.assertNotIn("training_run_id", source)
        self.assertNotIn("createTrainingRun", source)
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("verify-sample-export:", makefile)


if __name__ == "__main__":
    unittest.main()
