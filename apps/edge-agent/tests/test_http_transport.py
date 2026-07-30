import hashlib
import io
import json
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
from urllib.error import HTTPError, URLError


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "packages/python-contracts/src"))
sys.path.insert(0, str(EDGE_ROOT / "src"))

from edge_agent.sync.client import SyncClientError
from edge_agent.sync.http_transport import HttpApiClient, HttpsObjectUploader


class FakeResponse:
    def __init__(self, payload=b"{}", *, status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        self._stream = io.BytesIO(payload)
        self.closed = False

    def read(self, size=-1):
        return self._stream.read(size)

    def close(self):
        self.closed = True


class RecordingOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, request, *, timeout):
        body = request.data
        if body is None:
            consumed = b""
        elif isinstance(body, bytes):
            consumed = body
        else:
            consumed = b"".join(body)
        self.calls.append(
            {
                "request": request,
                "body": consumed,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def json_response(payload, *, status=200, headers=None):
    return FakeResponse(
        json.dumps(payload).encode("utf-8"),
        status=status,
        headers=headers,
    )


def http_error(status, *, retry_after=None, body=None):
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    payload = json.dumps(body or {}).encode("utf-8")
    return HTTPError(
        "https://api.example.invalid/redacted",
        status,
        "error",
        headers,
        io.BytesIO(payload),
    )


class HttpApiClientTests(unittest.TestCase):
    def setUp(self):
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.secret = "test-bearer-token"

    def client(self, responses):
        opener = RecordingOpener(responses)
        client = HttpApiClient(
            "https://api.example.invalid/tenant/",
            token_provider=lambda: self.secret,
            ssl_context=self.context,
            timeout_seconds=3.5,
            opener=opener,
        )
        return client, opener

    def test七个生成操作发送真实json请求(self):
        capture_id = "capture /中文"
        image_id = "image/one"
        device_id = "device one"
        responses = [
            json_response({"operation": operation})
            for operation in (
                "createCapture",
                "renewCaptureImageUploadTicket",
                "completeCaptureImage",
                "submitCapture",
                "getEdgeCapture",
                "queryCaptureSync",
                "reportDeviceHeartbeat",
            )
        ]
        client, opener = self.client(responses)

        calls = (
            client.createCapture({"body": {"capture_id": capture_id}}),
            client.renewCaptureImageUploadTicket(
                {
                    "path": {"capture_id": capture_id, "image_id": image_id},
                    "headers": {"Idempotency-Key": "renew"},
                    "body": {"size_bytes": 3, "sha256": "a" * 64},
                }
            ),
            client.completeCaptureImage(
                {
                    "path": {"capture_id": capture_id, "image_id": image_id},
                    "body": {"upload_receipt": "etag"},
                }
            ),
            client.submitCapture(
                {
                    "path": {"capture_id": capture_id},
                    "body": {"requested_at": "2026-07-29T00:00:00.000Z"},
                }
            ),
            client.getEdgeCapture({"path": {"capture_id": capture_id}}),
            client.queryCaptureSync({"body": {"capture_ids": [capture_id]}}),
            client.reportDeviceHeartbeat(
                {
                    "path": {"device_id": device_id},
                    "body": {"queue_depth": 0},
                }
            ),
        )

        self.assertEqual(7, len(calls))
        self.assertEqual(7, len(opener.calls))
        expected_urls = (
            "https://api.example.invalid/tenant/api/v1/edge/captures",
            "https://api.example.invalid/tenant/api/v1/edge/captures/"
            "capture%20%2F%E4%B8%AD%E6%96%87/images/image%2Fone/upload-ticket",
            "https://api.example.invalid/tenant/api/v1/edge/captures/"
            "capture%20%2F%E4%B8%AD%E6%96%87/images/image%2Fone/complete",
            "https://api.example.invalid/tenant/api/v1/edge/captures/"
            "capture%20%2F%E4%B8%AD%E6%96%87/submit",
            "https://api.example.invalid/tenant/api/v1/edge/captures/"
            "capture%20%2F%E4%B8%AD%E6%96%87",
            "https://api.example.invalid/tenant/api/v1/edge/sync/captures/query",
            "https://api.example.invalid/tenant/api/v1/edge/devices/"
            "device%20one/heartbeat",
        )
        self.assertEqual(
            expected_urls,
            tuple(call["request"].full_url for call in opener.calls),
        )
        self.assertEqual("GET", opener.calls[4]["request"].method)
        self.assertEqual(b"", opener.calls[4]["body"])
        self.assertEqual(
            {"capture_ids": [capture_id]},
            json.loads(opener.calls[5]["body"]),
        )
        for call in opener.calls:
            request = call["request"]
            self.assertEqual(
                f"Bearer {self.secret}",
                request.get_header("Authorization"),
            )
            self.assertEqual(3.5, call["timeout"])
        self.assertIs(self.context, client.ssl_context)

    def test状态码和retry_after映射为同步错误且不泄露令牌(self):
        cases = (
            (401, False, None, "TD-AUTH-UNAUTHORIZED-001"),
            (403, False, None, "TD-AUTH-FORBIDDEN-001"),
            (429, True, 7.0, "TD-API-TRANSIENT-429"),
            (503, True, 11.0, "TD-API-TRANSIENT-503"),
        )
        for status, retryable, retry_after, code in cases:
            with self.subTest(status=status):
                client, _ = self.client(
                    [http_error(status, retry_after=str(int(retry_after or 0)))]
                )
                with self.assertRaises(SyncClientError) as raised:
                    client.createCapture({"body": {"capture_id": "capture"}})
                error = raised.exception
                self.assertEqual(status, error.status_code)
                self.assertEqual(retryable, error.retryable)
                self.assertEqual(retry_after, error.retry_after_seconds)
                self.assertEqual(code, error.code)
                self.assertNotIn(self.secret, str(error))

    def test服务端合法错误码可保留但重试属性由状态码决定(self):
        client, _ = self.client(
            [
                http_error(
                    503,
                    body={"code": "TD-STORAGE-TRANSIENT-009", "retryable": False},
                )
            ]
        )
        with self.assertRaises(SyncClientError) as raised:
            client.queryCaptureSync({"body": {"capture_ids": []}})
        self.assertEqual("TD-STORAGE-TRANSIENT-009", raised.exception.code)
        self.assertTrue(raised.exception.retryable)

    def test上传会话过期专用契约错误码穿透传输层(self):
        client, _ = self.client(
            [
                http_error(
                    409,
                    body={
                        "code": "TD-STORAGE-EXPIRED-001",
                        "message": "上传授权已过期",
                        "request_id": (
                            "019f0000-0000-7000-8000-000000000904"
                        ),
                        "trace_id": "0" * 32,
                        "retryable": True,
                        "details": [],
                    },
                )
            ]
        )
        with self.assertRaises(SyncClientError) as raised:
            client.completeCaptureImage(
                {
                    "path": {
                        "capture_id": "capture",
                        "image_id": "image",
                    },
                    "body": {"upload_receipt": "opaque"},
                }
            )
        self.assertEqual(
            "TD-STORAGE-EXPIRED-001",
            raised.exception.code,
        )
        self.assertEqual(409, raised.exception.status_code)

    def test拒绝非https基础地址和调用方authorization头(self):
        with self.assertRaises(ValueError):
            HttpApiClient(
                "http://api.example.invalid",
                token_provider=lambda: "token",
                opener=RecordingOpener([]),
            )
        client, opener = self.client([json_response({})])
        with self.assertRaises(ValueError):
            client.getEdgeCapture(
                {
                    "path": {"capture_id": "capture"},
                    "headers": {"Authorization": "Bearer attacker"},
                }
            )
        self.assertEqual([], opener.calls)

    def test令牌获取失败不会把异常内容带入传输错误(self):
        def broken_provider():
            raise RuntimeError("secret-token-in-provider-error")

        client = HttpApiClient(
            "https://api.example.invalid",
            token_provider=broken_provider,
            opener=RecordingOpener([]),
        )
        with self.assertRaises(SyncClientError) as raised:
            client.createCapture({"body": {}})
        self.assertNotIn("secret-token", str(raised.exception))

    def test断网和超时映射为可重试控制面错误(self):
        cases = (
            (
                URLError(OSError("network unreachable")),
                "TD-API-TRANSIENT-001",
            ),
            (TimeoutError("timed out"), "TD-API-TIMEOUT-001"),
        )
        for failure, expected_code in cases:
            with self.subTest(code=expected_code):
                client, _ = self.client([failure])
                with self.assertRaises(SyncClientError) as raised:
                    client.createCapture({"body": {"capture_id": "same"}})
                self.assertTrue(raised.exception.retryable)
                self.assertEqual(expected_code, raised.exception.code)
                self.assertIsNone(raised.exception.status_code)


class HttpsObjectUploaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.file_path = Path(self.temporary.name) / "capture.bin"
        self.content = b"abcdefghij"
        self.file_path.write_bytes(self.content)
        self.digest = hashlib.sha256(self.content).hexdigest()

    def tearDown(self):
        self.temporary.cleanup()

    def test签名put按分块读取并返回etag(self):
        response = FakeResponse(status=200, headers={"ETag": '"etag-opaque"'})
        opener = RecordingOpener([response])
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        uploader = HttpsObjectUploader(
            ssl_context=context,
            timeout_seconds=9,
            chunk_size=3,
            opener=opener,
        )
        receipt = uploader.put(
            url="https://objects.example.invalid/bucket/object?signature=secret",
            method="PUT",
            headers={"Content-Type": "application/octet-stream"},
            file_path=self.file_path,
            sha256=self.digest,
            size_bytes=len(self.content),
        )
        self.assertEqual('"etag-opaque"', receipt)
        self.assertEqual(self.content, opener.calls[0]["body"])
        request = opener.calls[0]["request"]
        self.assertEqual("PUT", request.method)
        self.assertEqual(str(len(self.content)), request.get_header("Content-length"))
        self.assertEqual(9.0, opener.calls[0]["timeout"])
        self.assertIs(context, uploader.ssl_context)

    def test控制面回执优先返回且绝不外发给对象存储(self):
        response = FakeResponse(
            status=200,
            headers={"ETag": '"storage-etag"'},
        )
        opener = RecordingOpener([response])
        uploader = HttpsObjectUploader(opener=opener, chunk_size=4)
        receipt = uploader.put(
            url="https://objects.example.invalid/bucket/object?signature=secret",
            method="PUT",
            headers={
                "Content-Type": "application/octet-stream",
                "x-ToOl-DeFeCt-UpLoAd-ReCeIpT": "control-plane-receipt",
            },
            file_path=self.file_path,
            sha256=self.digest,
            size_bytes=len(self.content),
        )
        self.assertEqual("control-plane-receipt", receipt)
        sent_names = {
            name.lower()
            for name, _ in opener.calls[0]["request"].header_items()
        }
        self.assertNotIn("x-tool-defect-upload-receipt", sent_names)

    def test拒绝非https地址和非put方法(self):
        uploader = HttpsObjectUploader(opener=RecordingOpener([]))
        common = {
            "headers": {},
            "file_path": self.file_path,
            "sha256": self.digest,
            "size_bytes": len(self.content),
        }
        with self.assertRaises(SyncClientError) as raised:
            uploader.put(url="http://objects.example.invalid/a", method="PUT", **common)
        self.assertEqual("TD-UPLOAD-URL-001", raised.exception.code)
        with self.assertRaises(SyncClientError) as raised:
            uploader.put(
                url="https://objects.example.invalid/a",
                method="POST",
                **common,
            )
        self.assertEqual("TD-UPLOAD-METHOD-001", raised.exception.code)

    def test大小或哈希不符时不发起网络请求(self):
        for size, digest in (
            (len(self.content) + 1, self.digest),
            (len(self.content), "0" * 64),
        ):
            with self.subTest(size=size, digest=digest):
                opener = RecordingOpener([])
                uploader = HttpsObjectUploader(opener=opener)
                with self.assertRaises(SyncClientError) as raised:
                    uploader.put(
                        url="https://objects.example.invalid/a?signature=secret",
                        method="PUT",
                        headers={},
                        file_path=self.file_path,
                        sha256=digest,
                        size_bytes=size,
                    )
                self.assertEqual("TD-EDGE-INTEGRITY-001", raised.exception.code)
                self.assertEqual([], opener.calls)
                self.assertNotIn("signature=secret", str(raised.exception))

    def test上传503保留retry_after但不泄露签名地址(self):
        opener = RecordingOpener([http_error(503, retry_after="13")])
        uploader = HttpsObjectUploader(opener=opener)
        with self.assertRaises(SyncClientError) as raised:
            uploader.put(
                url="https://objects.example.invalid/a?signature=secret",
                method="PUT",
                headers={},
                file_path=self.file_path,
                sha256=self.digest,
                size_bytes=len(self.content),
            )
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(13.0, raised.exception.retry_after_seconds)
        self.assertNotIn("signature=secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
