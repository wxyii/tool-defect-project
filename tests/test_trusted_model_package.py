from base64 import b64encode
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from tool_defect.models.package import (
    ApprovedArtifact,
    Ed25519SignatureVerifier,
    ModelPackageVerifier,
    file_sha256,
)
from tool_defect.models.trusted_loader import TrustedKerasLoader
from tool_defect.plugin_api import PluginError, PluginErrorCode


class TrustedModelPackageTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        self.key_id = "model-signing-test"
        self.public_key = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.verifier = ModelPackageVerifier(
            Ed25519SignatureVerifier(
                {self.key_id: self.public_key}
            )
        )

    def test_valid_signed_registered_package_is_verified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, approval = self._build_package(Path(temporary) / "model")

            verified = self.verifier.verify(root, approval)

            self.assertEqual(verified.package_sha256, approval.package_sha256)
            self.assertEqual(verified.signer_key_id, self.key_id)
            self.assertEqual(
                verified.verification_report["status"], "VERIFIED"
            )
            self.assertEqual(
                set(verified.file_sha256),
                {
                    "environment.lock",
                    "labels.json",
                    "manifest.json",
                    "metrics.json",
                    "model.json",
                    "preprocessing.json",
                    "weights.h5",
                },
            )

    def test_tampered_weight_and_mixed_architecture_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first, approval = self._build_package(
                base / "first", architecture_name="first"
            )
            second, _ = self._build_package(
                base / "second", architecture_name="second"
            )

            (first / "weights.h5").write_bytes(b"tampered")
            self._assert_incompatible(first, approval)

            first, approval = self._build_package(
                base / "third", architecture_name="third"
            )
            (first / "model.json").write_bytes(
                (second / "model.json").read_bytes()
            )
            self._assert_incompatible(first, approval)

    def test_unsigned_and_wrong_framework_version_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            unsigned, approval = self._build_package(base / "unsigned")
            (unsigned / "signature.sig").unlink()
            self._assert_incompatible(unsigned, approval)

            incompatible, approval = self._build_package(
                base / "wrong-version",
                manifest_updates={"framework_version": "2.14.0"},
            )
            self._assert_incompatible(incompatible, approval)

    def test_wrong_labels_and_incomplete_warmup_pair_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            wrong_labels, approval = self._build_package(
                base / "wrong-labels",
                manifest_updates={
                    "label_map": {
                        "0": "unqualified",
                        "1": "qualified",
                    }
                },
            )
            self._assert_incompatible(wrong_labels, approval)

            incomplete, approval = self._build_package(
                base / "incomplete-warmup",
                warmup_expected={"cla_out": [1, 2]},
                include_warmup_input=False,
            )
            self._assert_incompatible(incomplete, approval)

    def test_loader_rejects_unknown_objects_and_executable_layers(self):
        loader = TrustedKerasLoader()
        with self.assertRaises(PluginError):
            loader.inspect_model_json(
                json.dumps(
                    {
                        "class_name": "UnknownResearchLayer",
                        "config": {},
                    }
                ),
                {},
            )
        with self.assertRaises(PluginError):
            loader.inspect_model_json(
                json.dumps(
                    {"class_name": "Lambda", "config": {}}
                ),
                {},
            )

    def test_loader_allows_only_documented_tensor_functions(self):
        loader = TrustedKerasLoader()
        accepted = loader.inspect_model_json(
            json.dumps(
                {
                    "class_name": "TFOpLambda",
                    "config": {"function": "math.reduce_mean"},
                    "module": "keras.src.layers.core.tf_op_layer",
                }
            ),
            {},
        )
        self.assertIn("TFOpLambda", accepted)

        with self.assertRaises(PluginError):
            loader.inspect_model_json(
                json.dumps(
                    {
                        "class_name": "TFOpLambda",
                        "config": {"function": "io.read_file"},
                    }
                ),
                {},
            )

    def test_fixed_warmup_input_and_expected_shapes_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, approval = self._build_package(
                Path(temporary) / "warmup",
                warmup_expected={"cla_out": [1, 2]},
            )
            verified = self.verifier.verify(root, approval)
            loader = TrustedKerasLoader()

            shapes = loader.warmup(_PredictModel((1, 2)), verified)

            self.assertEqual(shapes, {"cla_out": (1, 2)})

            root, approval = self._build_package(
                Path(temporary) / "warmup-mismatch",
                warmup_expected={"cla_out": [1, 3]},
            )
            verified = self.verifier.verify(root, approval)
            with self.assertRaises(PluginError):
                loader.warmup(_PredictModel((1, 2)), verified)

    def test_real_keras_structure_loads_but_mixed_weights_are_rejected(self):
        from tensorflow.keras import Model
        from tensorflow.keras.layers import Dense, Flatten, Input

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            inputs = Input(shape=(4, 4, 3), name="image")
            valid_model = Model(
                inputs,
                Dense(
                    2,
                    activation="softmax",
                    name="cla_out",
                )(Flatten()(inputs)),
            )
            valid_weights = base / "valid-weights.h5"
            valid_model.save_weights(valid_weights)
            root, _ = self._build_package(base / "valid")
            (root / "model.json").write_text(
                valid_model.to_json(), encoding="utf-8"
            )
            (root / "weights.h5").write_bytes(
                valid_weights.read_bytes()
            )
            approval = self._resign(root)
            verified = self.verifier.verify(root, approval)
            loader = TrustedKerasLoader()

            loaded = loader.load(verified, {})
            shapes = loader.warmup(loaded, verified)

            self.assertEqual(shapes, {"cla_out": (1, 2)})

            incompatible_model = Model(
                inputs,
                Dense(
                    3,
                    activation="softmax",
                    name="cla_out",
                )(Flatten()(inputs)),
            )
            mixed, _ = self._build_package(base / "mixed")
            (mixed / "model.json").write_text(
                incompatible_model.to_json(), encoding="utf-8"
            )
            (mixed / "weights.h5").write_bytes(
                valid_weights.read_bytes()
            )
            approval = self._resign(mixed)
            verified = self.verifier.verify(mixed, approval)

            with self.assertRaises(PluginError):
                loader.load(verified, {})

    def test_verifier_cli_reports_invalid_control_files_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            approval = root / "approval.json"
            keys = root / "keys.json"
            output = root / "report.json"
            _write_json(approval, {})
            _write_json(keys, {})
            module_path = (
                Path(__file__).resolve().parents[1]
                / "tools/verify-artifacts/verify_model_package.py"
            )
            spec = importlib.util.spec_from_file_location(
                "verify_model_package_test", module_path
            )
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)

            exit_code = module.main(
                [
                    "--package",
                    str(root / "missing-package"),
                    "--approval",
                    str(approval),
                    "--trusted-keys",
                    str(keys),
                    "--output",
                    str(output),
                ]
            )

            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 2)
            self.assertEqual(report["status"], "REJECTED")
            self.assertEqual(report["error"]["code"], "INPUT_INVALID")

    def _build_package(
        self,
        root,
        *,
        architecture_name="candidate",
        manifest_updates=None,
        warmup_expected=None,
        include_warmup_input=True,
    ):
        root.mkdir(parents=True)
        preprocessing = {
            "plugin_id": "tool-defect.basic-gray-resize",
            "plugin_version": "1.0.0",
            "config_hash": "sha256:" + "1" * 64,
        }
        manifest = {
            "model_name": "multitask-candidate",
            "model_version": "1",
            "framework": "tensorflow",
            "framework_version": "2.13.0",
            "keras_version": "2.13.1",
            "python_version": "3.11",
            "input_spec": {
                "shape": [4, 4, 3],
                "dtype": "float32",
                "color_space": "RGB",
                "range": [0.0, 1.0],
            },
            "output_names": ["cla_out"],
            "label_map": {
                "0": "qualified",
                "1": "unqualified",
            },
            "preprocessor": preprocessing,
            "dataset_version": "dataset-test/1",
            "source_run_id": "run-test",
        }
        manifest.update(manifest_updates or {})
        _write_json(root / "manifest.json", manifest)
        _write_json(
            root / "model.json",
            {
                "class_name": "Functional",
                "config": {
                    "name": architecture_name,
                    "layers": [],
                },
            },
        )
        (root / "weights.h5").write_bytes(
            ("weights-" + architecture_name).encode("utf-8")
        )
        _write_json(root / "labels.json", manifest["label_map"])
        _write_json(root / "preprocessing.json", preprocessing)
        _write_json(root / "metrics.json", {"status": "TEST_CANDIDATE"})
        (root / "environment.lock").write_text(
            "tensorflow==2.13.0\nkeras==2.13.1\n",
            encoding="utf-8",
        )
        if warmup_expected is not None:
            if include_warmup_input:
                np.save(
                    root / "warmup-input.npy",
                    np.zeros((1, 4, 4, 3), dtype=np.float32),
                    allow_pickle=False,
                )
            _write_json(
                root / "warmup-expected.json",
                {"output_shapes": warmup_expected},
            )
        return root, self._resign(root)

    def _resign(self, root):
        manifest = json.loads(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
        checksummed = sorted(
            path.name
            for path in root.iterdir()
            if path.name
            not in {"checksums.sha256", "signature.sig"}
        )
        checksum_payload = "".join(
            f"{file_sha256(root / name)}  {name}\n"
            for name in checksummed
        ).encode("utf-8")
        (root / "checksums.sha256").write_bytes(checksum_payload)
        signature = self.private_key.sign(checksum_payload)
        _write_json(
            root / "signature.sig",
            {
                "algorithm": "ed25519",
                "key_id": self.key_id,
                "signature_base64": b64encode(signature).decode("ascii"),
            },
        )
        package_sha256 = hashlib.sha256(checksum_payload).hexdigest()
        approval = ApprovedArtifact(
            model_name=manifest["model_name"],
            model_version=manifest["model_version"],
            package_sha256=package_sha256,
            signer_key_id=self.key_id,
            approval_state="APPROVED",
        )
        return approval

    def _assert_incompatible(self, root, approval):
        with self.assertRaises(PluginError) as captured:
            self.verifier.verify(root, approval)
        self.assertEqual(
            captured.exception.info.code,
            PluginErrorCode.MODEL_INCOMPATIBLE,
        )


class _PredictModel:
    def __init__(self, output_shape):
        self.output_shape = output_shape

    def predict(self, sample, verbose=0):
        return np.zeros(self.output_shape, dtype=np.float32)


def _write_json(path, payload):
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
