import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
SERVICE_SRC = PROJECT_ROOT / "services/inference-service/src"
for path in (SRC_ROOT, SERVICE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from inference_service.storage.materializer import (
    MaterializedObject,
    ObjectMaterializer,
    ObjectReference,
)
from inference_service.orchestration.decoder import ImageDecoder
from tool_defect.plugin_api import PluginError, PluginErrorCode


class ObjectMaterializerTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_is_materialized_inside_temp_and_hash_checked(self):
        payload = b"trusted-image-bytes"
        reference = _reference(payload, image_id="../../escape")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialized = await ObjectMaterializer(
                _Reader(payload)
            ).materialize(reference, root)

            self.assertEqual(materialized.path.parent, root)
            self.assertEqual(materialized.path.read_bytes(), payload)
            self.assertNotIn("escape", materialized.path.name)

    async def test_size_and_hash_mismatches_are_input_errors(self):
        payload = b"actual"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong_hash = ObjectReference(
                image_id="image-1",
                object_key="object",
                sha256="0" * 64,
                media_type="image/png",
                size_bytes=len(payload),
            )
            with self.assertRaises(PluginError) as captured:
                await ObjectMaterializer(
                    _Reader(payload)
                ).materialize(wrong_hash, root)
            self.assertEqual(
                captured.exception.info.code,
                PluginErrorCode.INPUT_INVALID,
            )

            wrong_size = _reference(payload)
            wrong_size = ObjectReference(
                image_id=wrong_size.image_id,
                object_key=wrong_size.object_key,
                sha256=wrong_size.sha256,
                media_type=wrong_size.media_type,
                size_bytes=len(payload) + 1,
            )
            with self.assertRaises(PluginError):
                await ObjectMaterializer(
                    _Reader(payload)
                ).materialize(wrong_size, root)

    async def test_decoder_preserves_encoded_bytes_and_checks_media_type(self):
        pixels = np.full((3, 4, 3), 127, dtype=np.uint8)
        success, encoded = cv2.imencode(".png", pixels)
        self.assertTrue(success)
        payload = encoded.tobytes()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialized = await ObjectMaterializer(
                _Reader(payload)
            ).materialize(_reference(payload), root)

            frame = ImageDecoder(maximum_pixels=100).decode(materialized)

            self.assertEqual(frame.encoded_bytes, payload)
            self.assertEqual(frame.attributes["image_kind"], "RAW")
            self.assertEqual(frame.attributes["image_role"], "primary")
            np.testing.assert_array_equal(frame.pixels, pixels)

            wrong_reference = ObjectReference(
                image_id="image-2",
                object_key="captures/object.png",
                sha256=hashlib.sha256(payload).hexdigest(),
                media_type="image/jpeg",
                size_bytes=len(payload),
            )
            wrong = MaterializedObject(
                reference=wrong_reference,
                path=materialized.path,
                sha256=materialized.sha256,
                size_bytes=materialized.size_bytes,
            )
            with self.assertRaises(PluginError):
                ImageDecoder().decode(wrong)

            wrong_dimensions = ObjectReference(
                image_id="image-3",
                object_key="captures/object.png",
                sha256=hashlib.sha256(payload).hexdigest(),
                media_type="image/png",
                size_bytes=len(payload),
                width=99,
                height=3,
                image_role="PRIMARY",
            )
            with self.assertRaises(PluginError):
                ImageDecoder().decode(
                    MaterializedObject(
                        reference=wrong_dimensions,
                        path=materialized.path,
                        sha256=materialized.sha256,
                        size_bytes=materialized.size_bytes,
                    )
                )


class _Reader:
    def __init__(self, payload):
        self.payload = payload

    async def download(self, reference, destination):
        destination.write_bytes(self.payload)


def _reference(payload, *, image_id="image-1"):
    return ObjectReference(
        image_id=image_id,
        object_key="captures/object.png",
        sha256=hashlib.sha256(payload).hexdigest(),
        media_type="image/png",
        size_bytes=len(payload),
    )


if __name__ == "__main__":
    unittest.main()
