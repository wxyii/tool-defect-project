from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class R3ManualDetectionIntegrationTest(unittest.TestCase):
    def test_all_frozen_r3_paths_have_backend_consumers(self) -> None:
        contract = json.loads((ROOT / "contracts/openapi/tool-defect-api-v2.json").read_text(encoding="utf-8"))
        controller = (ROOT / "services/business-api/src/main/java/com/tooldefect/business/detectionbatch/api/ManualDetectionController.java").read_text(encoding="utf-8")
        operations = {
            "getManualDetectionCapabilitiesV2",
            "listDetectionBatchesV2",
            "createDetectionBatchV2",
            "getDetectionBatchV2",
            "addDetectionBatchItemV2",
            "getDetectionBatchItemV2",
            "deleteDetectionBatchItemV2",
            "completeDetectionBatchItemUploadV2",
            "submitDetectionBatchV2",
        }
        actual = {
            operation["operationId"]
            for path in contract["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict) and operation.get("operationId") in operations
        }
        self.assertEqual(operations, actual)
        for mapping in (
            '"/capabilities/manual-detection"',
            '"/detection-batches"',
            '"/detection-batches/{batch_id}/items"',
            '"/detection-batches/{batch_id}/items/{item_id}/complete"',
            '"/detection-batches/{batch_id}/submit"',
        ):
            self.assertIn(mapping, controller)


if __name__ == "__main__":
    unittest.main()
