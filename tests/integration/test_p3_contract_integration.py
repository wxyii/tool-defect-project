import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
for source in (
    ROOT / "src",
    ROOT / "services/inference-service/src",
    ROOT / "tools/verify-contracts",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from inference_service.orchestration.pipeline import InferenceTask
from schema_engine import SchemaEngine


P3_OPERATIONS = {
    "createCapture",
    "completeCaptureImage",
    "submitCapture",
    "getEdgeCapture",
    "queryCaptureSync",
    "reportDeviceHeartbeat",
    "startDetectionAttempt",
    "submitDetectionResult",
    "submitDetectionFailure",
    "listDetections",
    "getDetection",
    "createImageAccessTicket",
}


class P3ContractIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.openapi = json.loads(
            (
                ROOT / "contracts/openapi/tool-defect-api-v1.json"
            ).read_text(encoding="utf-8")
        )

    def test_p3_operations_are_frozen_and_generated_for_all_consumers(self):
        operations = {
            operation["operationId"]
            for path in self.openapi["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict) and "operationId" in operation
        }
        self.assertLessEqual(P3_OPERATIONS, operations)

        generated_sources = (
            ROOT / "packages/python-contracts/src/tool_defect_contracts/client.py",
            ROOT / "packages/java-contracts/src/main/java/local/tooldefect/contracts/ApiClient.java",
            ROOT / "packages/typescript-contracts/src/client.ts",
        )
        for source in generated_sources:
            text = source.read_text(encoding="utf-8")
            for operation_id in P3_OPERATIONS:
                self.assertIn(operation_id, text, source.as_posix())

    def test_inference_event_example_crosses_contract_and_runtime_boundary(self):
        event_path = (
            ROOT / "contracts/examples/events/inference-task-v1.json"
        )
        payload = json.loads(event_path.read_text(encoding="utf-8"))

        SchemaEngine().validate_file(
            payload,
            ROOT / "contracts/json-schema/inference-task-v1.schema.json",
        )
        task = InferenceTask.from_contract(
            payload,
            recipe_id="019f0000-0000-7000-8000-000000000099",
            model_sha256="1" * 64,
            now_monotonic=100.0,
        )

        self.assertEqual(payload["capture_id"], task.capture_id)
        self.assertEqual(payload["message_id"], task.message_id)
        self.assertEqual(payload["pipeline"]["version"], task.pipeline_version)
        self.assertEqual("td-original", task.images[0].bucket)

    def test_p3_writes_are_idempotent_and_internal_callbacks_are_scoped(self):
        by_operation = {
            operation["operationId"]: operation
            for path in self.openapi["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict) and "operationId" in operation
        }
        write_operations = P3_OPERATIONS.difference(
            {"getEdgeCapture", "listDetections", "getDetection"}
        )
        for operation_id in write_operations:
            parameters = by_operation[operation_id].get("parameters", [])
            parameter_names = {
                self._parameter(parameter).get("name")
                for parameter in parameters
                if isinstance(parameter, dict)
            }
            self.assertIn(
                "Idempotency-Key",
                parameter_names,
                operation_id,
            )

        for operation_id in (
            "startDetectionAttempt",
            "submitDetectionResult",
            "submitDetectionFailure",
        ):
            security = by_operation[operation_id]["security"]
            scopes = {
                scope
                for requirement in security
                for scope_list in requirement.values()
                for scope in scope_list
            }
            self.assertIn("inference:callback", scopes, operation_id)

    def _parameter(self, parameter):
        reference = parameter.get("$ref")
        if reference is None:
            return parameter
        name = reference.rsplit("/", 1)[-1]
        return self.openapi["components"]["parameters"][name]


if __name__ == "__main__":
    unittest.main()
