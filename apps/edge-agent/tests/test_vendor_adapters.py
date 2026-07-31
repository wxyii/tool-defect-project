"""厂商适配器单元测试 — P7-02。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, Sequence
from unittest.mock import MagicMock, patch

EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDGE_ROOT / "src"))

from edge_agent.adapters.ports import (
    CameraAdapter,
    CameraBusyError,
    CameraCaptureError,
    TriggerAdapter,
    TriggerEvent,
)
from edge_agent.capture.models import CapturedFrame


# ----- 工厂函数隔离测试（不需要真实 SDK）-----


class VendorAdapterFactoryTests(unittest.TestCase):
    """验证工厂函数创建的适配器实现正确协议接口。"""

    def test_gige_camera_implements_camera_adapter(self) -> None:
        from edge_agent.adapters.vendor.gige_camera import create_gige_camera

        adapter = create_gige_camera({
            "ip": "10.0.0.1",
            "port": 3956,
            "exposure_us": 5000,
        })
        self.assertIsInstance(adapter, object)
        self.assertTrue(callable(adapter.capture))
        self.assertTrue(callable(adapter.health))

    def test_usb_camera_implements_camera_adapter(self) -> None:
        from edge_agent.adapters.vendor.usb_camera import create_usb_camera

        adapter = create_usb_camera({
            "device_id": 0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
        })
        self.assertTrue(callable(adapter.capture))
        self.assertTrue(callable(adapter.health))

    def test_plc_trigger_implements_trigger_adapter(self) -> None:
        from edge_agent.adapters.vendor.plc_trigger import create_plc_trigger

        adapter = create_plc_trigger({
            "protocol": "modbus_tcp",
            "host": "192.168.1.10",
            "port": 502,
            "register_address": 100,
        })
        self.assertTrue(callable(adapter.poll))

    def test_optical_trigger_implements_trigger_adapter(self) -> None:
        from edge_agent.adapters.vendor.optical_sensor import create_optical_trigger

        adapter = create_optical_trigger({
            "gpio_pin": 17,
            "trigger_edge": "rising",
            "debounce_ms": 20,
        })
        self.assertTrue(callable(adapter.poll))


class VendorAdapterConfigValidationTests(unittest.TestCase):
    """验证配置校验拒绝无效参数。"""

    def test_gige_camera_rejects_missing_ip(self) -> None:
        from edge_agent.adapters.vendor.gige_camera import create_gige_camera

        with self.assertRaises(ValueError) as ctx:
            create_gige_camera({"port": 3956})
        self.assertIn("ip", str(ctx.exception))

    def test_gige_camera_rejects_invalid_port(self) -> None:
        from edge_agent.adapters.vendor.gige_camera import create_gige_camera

        with self.assertRaises(ValueError):
            create_gige_camera({"ip": "10.0.0.1", "port": 99999})

    def test_gige_camera_rejects_invalid_trigger_mode(self) -> None:
        from edge_agent.adapters.vendor.gige_camera import create_gige_camera

        with self.assertRaises(ValueError) as ctx:
            create_gige_camera(
                {"ip": "10.0.0.1", "trigger_mode": "invalid_mode"}
            )
        self.assertIn("trigger_mode", str(ctx.exception))

    def test_usb_camera_rejects_negative_device_id(self) -> None:
        from edge_agent.adapters.vendor.usb_camera import create_usb_camera

        with self.assertRaises(ValueError):
            create_usb_camera({"device_id": -1})

    def test_plc_trigger_rejects_unknown_protocol(self) -> None:
        from edge_agent.adapters.vendor.plc_trigger import create_plc_trigger

        with self.assertRaises(ValueError) as ctx:
            create_plc_trigger({
                "protocol": "unknown_protocol",
                "host": "192.168.1.10",
            })
        self.assertIn("protocol", str(ctx.exception))

    def test_plc_trigger_rejects_missing_host(self) -> None:
        from edge_agent.adapters.vendor.plc_trigger import create_plc_trigger

        with self.assertRaises(ValueError) as ctx:
            create_plc_trigger({"protocol": "modbus_tcp"})
        self.assertIn("host", str(ctx.exception))

    def test_plc_trigger_rejects_invalid_debounce(self) -> None:
        from edge_agent.adapters.vendor.plc_trigger import create_plc_trigger

        with self.assertRaises(ValueError):
            create_plc_trigger({
                "protocol": "modbus_tcp",
                "host": "192.168.1.10",
                "debounce_ms": -1,
            })

    def test_optical_trigger_rejects_invalid_edge(self) -> None:
        from edge_agent.adapters.vendor.optical_sensor import create_optical_trigger

        with self.assertRaises(ValueError) as ctx:
            create_optical_trigger({
                "gpio_pin": 17,
                "trigger_edge": "invalid",
            })
        self.assertIn("trigger_edge", str(ctx.exception))

    def test_optical_trigger_rejects_invalid_pull_mode(self) -> None:
        from edge_agent.adapters.vendor.optical_sensor import create_optical_trigger

        with self.assertRaises(ValueError) as ctx:
            create_optical_trigger({
                "gpio_pin": 17,
                "pull_mode": "invalid_mode",
            })
        self.assertIn("pull_mode", str(ctx.exception))


class VendorAdapterPendingHardwareTests(unittest.TestCase):
    """验证 PENDING_HARDWARE 守卫阻止真实硬件访问。"""

    def test_gige_camera_capture_raises_with_pending_hardware(self) -> None:
        from edge_agent.adapters.vendor.gige_camera import (
            PENDING_HARDWARE,
            create_gige_camera,
        )
        self.assertTrue(PENDING_HARDWARE)

        adapter = create_gige_camera({"ip": "10.0.0.1"})
        trigger = TriggerEvent(
            trigger_id="test-1",
            sequence=1,
            occurred_at="2026-07-31T00:00:00Z",
            occurred_monotonic=0.0,
            source="TEST",
        )
        with self.assertRaises(CameraCaptureError) as ctx:
            adapter.capture(trigger)
        self.assertIn("PENDING_HARDWARE", str(ctx.exception))

    def test_gige_camera_health_reports_pending_hardware(self) -> None:
        from edge_agent.adapters.vendor.gige_camera import create_gige_camera

        adapter = create_gige_camera({"ip": "10.0.0.1"})
        health = adapter.health()
        self.assertEqual(health["status"], "PENDING_HARDWARE")
        self.assertTrue(health["pending_hardware"])

    def test_usb_camera_capture_raises_with_pending_hardware(self) -> None:
        from edge_agent.adapters.vendor.usb_camera import (
            PENDING_HARDWARE,
            create_usb_camera,
        )
        self.assertTrue(PENDING_HARDWARE)

        adapter = create_usb_camera({"device_id": 0})
        trigger = TriggerEvent(
            trigger_id="test-2",
            sequence=2,
            occurred_at="2026-07-31T00:00:01Z",
            occurred_monotonic=1.0,
            source="TEST",
        )
        with self.assertRaises(CameraCaptureError) as ctx:
            adapter.capture(trigger)
        self.assertIn("PENDING_HARDWARE", str(ctx.exception))

    def test_plc_trigger_poll_returns_none_with_pending_hardware(self) -> None:
        from edge_agent.adapters.vendor.plc_trigger import (
            PENDING_HARDWARE,
            create_plc_trigger,
        )
        self.assertTrue(PENDING_HARDWARE)

        adapter = create_plc_trigger({
            "protocol": "modbus_tcp",
            "host": "192.168.1.10",
        })
        result = adapter.poll()
        self.assertIsNone(result)


class VendorAdapterExplicitHardwareTests(unittest.TestCase):
    """只有显式现场启用时才访问真实驱动，并验证非占位路径可运行。"""

    def test_usb_camera_opens_and_captures_when_explicitly_enabled(self) -> None:
        import edge_agent.adapters.vendor.usb_camera as module

        capture = MagicMock()
        capture.isOpened.return_value = True
        raw = MagicMock()
        raw.shape = (480, 640, 3)
        capture.read.return_value = (True, raw)
        encoded = MagicMock()
        encoded.tobytes.return_value = b"encoded-png"
        fake_cv2 = SimpleNamespace(
            VideoCapture=MagicMock(return_value=capture),
            VideoWriter_fourcc=MagicMock(return_value=1),
            imencode=MagicMock(return_value=(True, encoded)),
            CAP_PROP_FRAME_WIDTH=3,
            CAP_PROP_FRAME_HEIGHT=4,
            CAP_PROP_FPS=5,
            CAP_PROP_FOURCC=6,
            CAP_PROP_BUFFERSIZE=38,
            CAP_PROP_AUTO_EXPOSURE=21,
            CAP_PROP_EXPOSURE=15,
            CAP_PROP_AUTO_WB=44,
            IMWRITE_PNG_COMPRESSION=16,
        )
        with patch.object(module, "_OPENCV_AVAILABLE", True), patch.dict(
            sys.modules, {"cv2": fake_cv2}
        ):
            adapter = module.create_usb_camera(
                {"hardware_enabled": True, "device_id": 0, "width": 640, "height": 480}
            )
            self.assertEqual("ONLINE", adapter.health()["status"])
            frames = adapter.capture(
                TriggerEvent(
                    trigger_id="real-usb-1",
                    sequence=1,
                    occurred_at="2026-07-31T00:00:00Z",
                    occurred_monotonic=1.0,
                    source="TEST",
                )
            )
        self.assertEqual(1, len(frames))
        self.assertEqual(b"encoded-png", frames[0].content)

    def test_plc_can_emit_multiple_sequences_when_explicitly_enabled(self) -> None:
        import edge_agent.adapters.vendor.plc_trigger as module

        with patch.object(module, "_MODBUS_AVAILABLE", True):
            adapter = module.create_plc_trigger(
                {
                    "hardware_enabled": True,
                    "protocol": "modbus_tcp",
                    "host": "192.0.2.10",
                    "debounce_ms": 0,
                }
            )
            with patch.object(adapter, "_read_signal", side_effect=[1, 1, 0, 1, 1]):
                self.assertIsNone(adapter.poll())
                first = adapter.poll()
                self.assertIsNone(adapter.poll())
                self.assertIsNone(adapter.poll())
                second = adapter.poll()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(1, first.sequence)
        self.assertEqual(2, second.sequence)

    def test_optical_trigger_rearms_after_each_edge(self) -> None:
        import edge_agent.adapters.vendor.optical_sensor as module

        with patch.object(module, "_GPIO_AVAILABLE", True):
            adapter = module.create_optical_trigger(
                {
                    "hardware_enabled": True,
                    "gpio_pin": 17,
                    "trigger_edge": "rising",
                    "debounce_ms": 0,
                    "holdoff_ms": 0,
                }
            )
            with patch.object(adapter, "_read_gpio", side_effect=[0, 1, 0, 1]):
                self.assertIsNone(adapter.poll())
                first = adapter.poll()
                self.assertIsNone(adapter.poll())
                second = adapter.poll()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual((1, 2), (first.sequence, second.sequence))

    def test_optical_trigger_poll_returns_none_with_pending_hardware(self) -> None:
        from edge_agent.adapters.vendor.optical_sensor import (
            PENDING_HARDWARE,
            create_optical_trigger,
        )
        self.assertTrue(PENDING_HARDWARE)

        adapter = create_optical_trigger({"gpio_pin": 17})
        result = adapter.poll()
        self.assertIsNone(result)


class VendorAdapterModuleExportsTests(unittest.TestCase):
    """验证 vendor 包导出所有工厂函数。"""

    def test_vendor_init_exports_all_factories(self) -> None:
        from edge_agent.adapters.vendor import (
            create_gige_camera,
            create_optical_trigger,
            create_plc_trigger,
            create_usb_camera,
        )

        self.assertTrue(callable(create_gige_camera))
        self.assertTrue(callable(create_optical_trigger))
        self.assertTrue(callable(create_plc_trigger))
        self.assertTrue(callable(create_usb_camera))

    def test_vendor_init_version(self) -> None:
        import edge_agent.adapters.vendor as vendor_pkg

        self.assertEqual(vendor_pkg.__version__, "1.0.0")


if __name__ == "__main__":
    unittest.main()
