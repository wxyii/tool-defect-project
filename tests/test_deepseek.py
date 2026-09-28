import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.deepseek.batch import run_batch  # noqa: E402
from tool_defect.deepseek.client import DeepSeekVisionClient, image_to_data_url  # noqa: E402
from tool_defect.deepseek.schema import parse_json_content, validate_result  # noqa: E402


class FakeCompletions:
    def __init__(self):
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(
            id="fake-response",
            model="deepseek-flash",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "has_defect": "yes",
                                "image_quality": "usable",
                                "defects": [
                                    {
                                        "type": "edge_damage",
                                        "location": "3点钟方向外缘",
                                        "evidence": "边缘有明显缺口",
                                    }
                                ],
                                "certainty": "high",
                            },
                            ensure_ascii=False,
                        )
                    ),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


class DeepSeekTests(unittest.TestCase):
    def test_schema_accepts_and_normalises_result(self):
        result = validate_result(
            {
                "has_defect": "是",
                "image_quality": "可用",
                "defects": [],
                "certainty": "高",
            }
        )
        self.assertEqual(result["has_defect"], "yes")
        self.assertEqual(result["image_quality"], "usable")

    def test_json_fence_is_supported(self):
        result = parse_json_content(
            '```json\n{"has_defect":"no","image_quality":"usable","defects":[],"certainty":"high"}\n```'
        )
        self.assertEqual(result["has_defect"], "no")

    def test_image_request_contains_data_url_and_json_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "sample.png"
            image_path.write_bytes(b"not-a-real-png-but-valid-transport-test")
            fake = FakeClient()
            client = DeepSeekVisionClient(client=fake)
            result = client.analyze_image(image_path)
            request = fake.chat.completions.requests[0]
            self.assertEqual(request["response_format"], {"type": "json_object"})
            image_block = request["messages"][1]["content"][1]
            self.assertTrue(image_block["image_url"]["url"].startswith("data:image/png;base64,"))
            self.assertEqual(result["parsed"]["has_defect"], "yes")

    def test_batch_writes_results_and_errors_are_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image_path = root / "sample.png"
            image_path.write_bytes(b"test")
            output = root / "out"
            summary = run_batch(DeepSeekVisionClient(client=FakeClient()), [image_path], output)
            self.assertEqual(summary["total_images"], 1)
            self.assertEqual(summary["successful_requests"], 1)
            self.assertTrue((output / "deepseek_predictions.csv").is_file())
            self.assertTrue((output / "summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
