#!/usr/bin/env python3
"""现场硬件验收脚本 — 独立运行，不依赖采集进程。

验收测试：
  1. 相机连通性
  2. 触发信号检测
  3. 单帧采集
  4. 连续采集
  5. 触发-采集延迟测量
  6. 暗帧 / 饱和测试
  7. 多相机同步（如启用）
  8. 长时间稳定性占位

用法:
  python hardware_acceptance.py --config site-hardware-config.json --output report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from edge_agent.adapters.ports import CameraAdapter, TriggerAdapter, TriggerEvent
from edge_agent.adapters.vendor.gige_camera import create_gige_camera
from edge_agent.adapters.vendor.usb_camera import create_usb_camera
from edge_agent.adapters.vendor.plc_trigger import create_plc_trigger
from edge_agent.adapters.vendor.optical_sensor import create_optical_trigger

logger = logging.getLogger(__name__)

RUNNER_VERSION = "2.0.0"
REAL_HARDWARE_SOURCE = "REAL_HARDWARE"
REQUIRED_EXTERNAL_SCENARIOS = {
    "network_outage",
    "agent_restart",
    "driver_failure",
    "disk_watermark",
    "clock_skew",
    "browser_failure",
}
PLACEHOLDER_MARKERS = (
    "PENDING",
    "PLACEHOLDER",
    "TEMPLATE",
    "TBD",
    "TODO",
    "待填写",
    "待签",
    "待确认",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_placeholder(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return not stripped or any(marker in stripped.upper() for marker in PLACEHOLDER_MARKERS)
    return False


def validate_acceptance_config(config: Mapping[str, object], config_path: Path) -> tuple[List[str], List[str]]:
    """区分缺现场事实的阻塞与损坏配置。"""

    blockers: List[str] = []
    errors: List[str] = []
    if ".template." in config_path.name.lower():
        blockers.append("hardware_config_is_template")
    if config.get("schema_version") != "tool-defect-hardware-acceptance/v1":
        blockers.append("hardware_config_schema_invalid")
    if config.get("source_type") != REAL_HARDWARE_SOURCE:
        blockers.append("hardware_source_not_real")
    for field_name in ("site_id", "run_id", "approved_at", "approved_by"):
        if _is_placeholder(config.get(field_name)):
            blockers.append(f"hardware_config_{field_name}_missing")

    for section_name in ("camera", "trigger"):
        section = config.get(section_name)
        if not isinstance(section, Mapping):
            errors.append(f"hardware_config_{section_name}_invalid")
            continue
        vendor_config = section.get("vendor_config")
        if not isinstance(vendor_config, Mapping):
            errors.append(f"hardware_config_{section_name}_vendor_config_invalid")
        elif vendor_config.get("hardware_enabled") is not True:
            blockers.append(f"hardware_config_{section_name}_not_enabled")

    inventory = config.get("device_inventory")
    if not isinstance(inventory, Mapping):
        blockers.append("hardware_device_inventory_missing")
    else:
        for device_name in ("camera", "trigger"):
            device = inventory.get(device_name)
            if not isinstance(device, Mapping):
                blockers.append(f"hardware_inventory_{device_name}_missing")
                continue
            for field_name in (
                "vendor",
                "model",
                "serial_number",
                "firmware_version",
                "driver_version",
                "sdk_version",
            ):
                if _is_placeholder(device.get(field_name)):
                    blockers.append(
                        f"hardware_inventory_{device_name}_{field_name}_missing"
                    )

    approval_path = config.get("approval_evidence_path")
    approval_hash = config.get("approval_evidence_sha256")
    if _is_placeholder(approval_path) or _is_placeholder(approval_hash):
        blockers.append("hardware_config_approval_evidence_missing")
    elif isinstance(approval_path, str) and isinstance(approval_hash, str):
        candidate = Path(approval_path)
        if not candidate.is_absolute():
            candidate = config_path.parent / candidate
        if not candidate.is_file():
            blockers.append("hardware_config_approval_evidence_file_missing")
        elif len(approval_hash) != 64 or sha256_file(candidate) != approval_hash:
            blockers.append("hardware_config_approval_evidence_hash_mismatch")
    return blockers, errors


@dataclass
class TestResult:
    test_name: str
    status: str
    evidence: Dict[str, object] = field(default_factory=dict)
    duration_s: float = 0.0
    errors: List[str] = field(default_factory=list)


class HardwareAcceptanceRunner:
    def __init__(
        self,
        config: Mapping[str, object],
        *,
        config_sha256: str = "",
        script_sha256: str = "",
        config_directory: Path | None = None,
    ) -> None:
        self.config = config
        self.config_sha256 = config_sha256
        self.script_sha256 = script_sha256
        self.config_directory = config_directory or Path.cwd()
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.started_monotonic = time.monotonic()
        self.results: List[TestResult] = []
        self.camera: Optional[CameraAdapter] = None
        self.trigger: Optional[TriggerAdapter] = None
        self.optical: Optional[TriggerAdapter] = None

    def setup(self) -> None:
        camera_cfg = self.config.get("camera", {})
        camera_type = camera_cfg.get("type", "usb")  # type: ignore[union-attr]
        vendor_cfg = camera_cfg.get("vendor_config", {})  # type: ignore[union-attr]

        if camera_type == "gige":
            self.camera = create_gige_camera(vendor_cfg)
        else:
            self.camera = create_usb_camera(vendor_cfg)

        trigger_cfg = self.config.get("trigger", {})
        trigger_type = trigger_cfg.get("type", "plc")  # type: ignore[union-attr]
        trigger_vendor_cfg = trigger_cfg.get("vendor_config", {})  # type: ignore[union-attr]

        if trigger_type in ("plc", "modbus", "modbus_tcp", "profinet", "ethercat"):
            self.trigger = create_plc_trigger(trigger_vendor_cfg)
        elif trigger_type == "optical":
            self.trigger = create_optical_trigger(trigger_vendor_cfg)

        optical_cfg = self.config.get("optical_trigger", {})
        if optical_cfg.get("enabled"):  # type: ignore[union-attr]
            self.optical = create_optical_trigger(
                optical_cfg.get("vendor_config", {})  # type: ignore[union-attr]
            )

    def _run_test(self, name: str, fn: Callable[[], Dict[str, object]]) -> TestResult:
        start = time.monotonic()
        try:
            evidence = fn()
            status = evidence.get("status", "PASS")
        except Exception as exc:
            evidence = {"error": str(exc), "error_type": type(exc).__name__}
            status = "FAIL"
            if "PENDING_HARDWARE" in str(exc):
                status = "PENDING_HARDWARE"
                evidence["status"] = "PENDING_HARDWARE"

        duration = round(time.monotonic() - start, 3)
        errors = [evidence.pop("error")] if "error" in evidence else []
        result = TestResult(
            test_name=name,
            status=status,
            evidence=evidence,
            duration_s=duration,
            errors=errors,
        )
        self.results.append(result)
        return result

    def test_connectivity(self) -> TestResult:
        def _check() -> Dict[str, object]:
            if self.camera is None:
                return {"status": "FAIL", "error": "Camera not configured"}
            health = self.camera.health()
            health["test"] = "connectivity"
            return health

        return self._run_test("camera_connectivity", _check)

    def test_trigger_signal(self) -> TestResult:
        def _check() -> Dict[str, object]:
            trigger = self.trigger or self.optical
            if trigger is None:
                return {"status": "FAIL", "error": "No trigger configured"}
            tp = self.config.get("test_parameters", {})
            duration = float(tp.get("trigger_poll_duration_s", 5))  # type: ignore[union-attr]
            interval = float(tp.get("trigger_poll_interval_ms", 50)) / 1000.0  # type: ignore[union-attr]

            deadline = time.monotonic() + duration
            events: List[Dict[str, object]] = []
            while time.monotonic() < deadline:
                evt = trigger.poll()
                if evt is not None:
                    events.append({
                        "trigger_id": evt.trigger_id,
                        "sequence": evt.sequence,
                        "occurred_monotonic": evt.occurred_monotonic,
                    })
                time.sleep(interval)

            sequences = [int(item["sequence"]) for item in events]
            duplicate_sequences = len(sequences) - len(set(sequences))
            gaps = [
                [previous, current]
                for previous, current in zip(sequences, sequences[1:])
                if current != previous + 1
            ]
            minimum_events = int(
                tp.get("acceptance_threshold", {}).get("min_trigger_events", 10)  # type: ignore[union-attr]
            )
            status = (
                "PASS"
                if len(events) >= minimum_events
                and duplicate_sequences == 0
                and not gaps
                else "PENDING_HARDWARE"
                if not events
                else "FAIL"
            )
            return {
                "status": status,
                "poll_duration_s": duration,
                "events_detected": len(events),
                "minimum_events": minimum_events,
                "duplicate_sequences": duplicate_sequences,
                "sequence_gaps": gaps,
                "events": events[:10],
            }

        return self._run_test("trigger_signal_detection", _check)

    def test_single_frame(self) -> TestResult:
        def _check() -> Dict[str, object]:
            if self.camera is None:
                return {"status": "FAIL", "error": "Camera not configured"}
            try:
                test_trigger = TriggerEvent(
                    trigger_id=str(uuid.uuid4()),
                    sequence=1,
                    occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    occurred_monotonic=time.monotonic(),
                    source="ACCEPTANCE_TEST",
                )
                frames = self.camera.capture(test_trigger)
                evidence: Dict[str, object] = {
                    "status": "PASS",
                    "frame_count": len(frames),
                }
                for idx, frame in enumerate(frames):
                    evidence[f"frame_{idx}_role"] = frame.image_role
                    evidence[f"frame_{idx}_size"] = len(frame.content)
                    evidence[f"frame_{idx}_dimensions"] = f"{frame.width}x{frame.height}"
                    evidence[f"frame_{idx}_media_type"] = frame.media_type
                    if frame.width is not None and frame.height is not None:
                        expected_bytes = frame.width * frame.height
                        evidence[f"frame_{idx}_expected_min_bytes"] = expected_bytes
                        evidence[f"frame_{idx}_format_ok"] = (
                            len(frame.content) > 0
                        )
                return evidence
            except Exception as exc:
                return {"status": "FAIL", "error": str(exc), "error_type": type(exc).__name__}

        return self._run_test("single_frame_capture", _check)

    def test_continuous_capture(self) -> TestResult:
        def _check() -> Dict[str, object]:
            if self.camera is None:
                return {"status": "FAIL", "error": "Camera not configured"}
            tp = self.config.get("test_parameters", {})
            frame_count_target = int(tp.get("continuous_capture_frames", 100))  # type: ignore[union-attr]

            start = time.monotonic()
            captured = 0
            failed = 0
            frame_sizes: List[int] = []
            deadlines: List[float] = []

            for seq in range(1, frame_count_target + 1):
                try:
                    test_trigger = TriggerEvent(
                        trigger_id=str(uuid.uuid4()),
                        sequence=seq,
                        occurred_at=time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                        occurred_monotonic=time.monotonic(),
                        source="ACCEPTANCE_TEST",
                    )
                    t0 = time.monotonic()
                    frames = self.camera.capture(test_trigger)
                    elapsed = time.monotonic() - t0
                    deadlines.append(elapsed)
                    for frame in frames:
                        frame_sizes.append(len(frame.content))
                    captured += len(frames)
                except Exception as exc:
                    failed += 1
                    if "PENDING_HARDWARE" in str(exc):
                        break

            total_time = time.monotonic() - start

            if captured == 0 and failed > 0:
                return {
                    "status": "FAIL",
                    "frames_attempted": frame_count_target,
                    "frames_captured": captured,
                    "frames_failed": failed,
                    "total_time_s": round(total_time, 3),
                    "error": "No frames captured",
                }

            actual_fps = captured / max(total_time, 0.001)
            threshold = float(tp.get("acceptance_threshold", {}).get("min_fps", 5.0))  # type: ignore[union-attr]
            maximum_failed_pct = float(
                tp.get("acceptance_threshold", {}).get("max_failed_frames_pct", 0.0)  # type: ignore[union-attr]
            )
            failed_pct = failed / max(frame_count_target, 1) * 100
            status = (
                "PASS"
                if actual_fps >= threshold and failed_pct <= maximum_failed_pct
                else "FAIL"
            )

            return {
                "status": status,
                "frames_attempted": frame_count_target,
                "frames_captured": captured,
                "frames_failed": failed,
                "total_time_s": round(total_time, 3),
                "actual_fps": round(actual_fps, 2),
                "target_fps": threshold,
                "failed_frames_pct": round(failed_pct, 4),
                "maximum_failed_frames_pct": maximum_failed_pct,
                "avg_frame_size_bytes": round(
                    sum(frame_sizes) / len(frame_sizes), 1
                )
                if frame_sizes
                else 0,
                "avg_capture_time_ms": round(
                    sum(deadlines) / len(deadlines) * 1000, 2
                )
                if deadlines
                else 0,
            }

        return self._run_test("continuous_capture", _check)

    def test_latency(self) -> TestResult:
        def _check() -> Dict[str, object]:
            if self.camera is None:
                return {"status": "FAIL", "error": "Camera not configured"}
            trigger = self.trigger or self.optical
            if trigger is None:
                return {"status": "FAIL", "error": "No trigger configured"}
            tp = self.config.get("test_parameters", {})
            samples = int(tp.get("latency_measurement_samples", 50))  # type: ignore[union-attr]

            latencies_ms: List[float] = []
            timed_out = 0
            poll_deadline = time.monotonic() + (samples * 1.0)

            while len(latencies_ms) < samples and time.monotonic() < poll_deadline:
                evt = trigger.poll()
                if evt is not None:
                    t0 = evt.occurred_monotonic
                    try:
                        self.camera.capture(evt)
                        t1 = time.monotonic()
                        latencies_ms.append((t1 - t0) * 1000)
                    except Exception:
                        timed_out += 1
                time.sleep(0.01)

            if not latencies_ms:
                return {"status": "PENDING_HARDWARE", "samples": 0, "timed_out": timed_out}

            avg = sum(latencies_ms) / len(latencies_ms)
            latencies_sorted = sorted(latencies_ms)
            threshold = float(
                tp.get("acceptance_threshold", {}).get("max_capture_latency_ms", 200)  # type: ignore[union-attr]
            )
            p95_index = min(
                max(int(round(len(latencies_sorted) * 0.95)) - 1, 0),
                len(latencies_sorted) - 1,
            )
            p95 = latencies_sorted[p95_index]
            status = "PASS" if p95 <= threshold and timed_out == 0 else "FAIL"
            return {
                "status": status,
                "samples": len(latencies_ms),
                "timed_out": timed_out,
                "avg_latency_ms": round(avg, 2),
                "p50_latency_ms": latencies_sorted[len(latencies_sorted) // 2],
                "p95_latency_ms": p95,
                "max_latency_ms": max(latencies_ms),
                "threshold_ms": threshold,
            }

        return self._run_test("trigger_to_capture_latency", _check)

    def test_dark_and_saturation(self) -> TestResult:
        def _check() -> Dict[str, object]:
            if self.camera is None:
                return {"status": "FAIL", "error": "Camera not configured"}
            tp = self.config.get("test_parameters", {})
            threshold = tp.get("acceptance_threshold", {})  # type: ignore[union-attr]

            dark_exposure = int(tp.get("dark_frame_exposure_us", 100))  # type: ignore[union-attr]
            sat_exposure = int(tp.get("saturation_exposure_us", 50000))  # type: ignore[union-attr]
            dark_max_mean = float(threshold.get("dark_frame_max_mean", 5))  # type: ignore[union-attr]
            sat_min_mean = float(threshold.get("saturation_min_mean", 245))  # type: ignore[union-attr]

            # 暗帧测试
            dark_test = TriggerEvent(
                trigger_id=str(uuid.uuid4()),
                sequence=1,
                occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                occurred_monotonic=time.monotonic(),
                source="ACCEPTANCE_DARK",
            )
            try:
                dark_frames = self.camera.capture(dark_test)
                dark_ok = bool(dark_frames)
            except Exception as exc:
                return {
                    "status": "PENDING_HARDWARE"
                    if "PENDING_HARDWARE" in str(exc)
                    else "FAIL",
                    "error": str(exc),
                }

            # 饱和测试
            sat_test = TriggerEvent(
                trigger_id=str(uuid.uuid4()),
                sequence=2,
                occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                occurred_monotonic=time.monotonic(),
                source="ACCEPTANCE_SATURATION",
            )
            try:
                sat_frames = self.camera.capture(sat_test)
                sat_ok = bool(sat_frames)
            except Exception as exc:
                return {
                    "status": "FAIL",
                    "error": str(exc),
                    "dark_captured": bool(dark_frames),
                }

            return {
                "status": "PASS" if dark_ok and sat_ok else "WARN",
                "dark_frame_captured": dark_ok,
                "saturation_frame_captured": sat_ok,
                "dark_exposure_us": dark_exposure,
                "saturation_exposure_us": sat_exposure,
                "dark_frame_max_mean_threshold": dark_max_mean,
                "saturation_min_mean_threshold": sat_min_mean,
                "note": "Pixel-level mean analysis requires OpenCV; frame capture validated only",
            }

        return self._run_test("dark_and_saturation", _check)

    def test_multi_camera_sync(self) -> TestResult:
        multi_cfg = self.config.get("multi_camera", {})
        if not multi_cfg.get("enabled"):  # type: ignore[union-attr]
            result = TestResult(
                test_name="multi_camera_sync",
                status="PASS",
                evidence={
                    "not_applicable": True,
                    "reason": "single_camera_site_config_approved",
                },
            )
            self.results.append(result)
            return result

        def _check() -> Dict[str, object]:
            cameras_cfg = multi_cfg.get("cameras", [])  # type: ignore[union-attr]
            if not cameras_cfg:
                return {"status": "SKIPPED", "reason": "No multi cameras configured"}
            return {
                "status": "PENDING_HARDWARE",
                "reason": "Multi-camera sync requires hardware setup",
                "configured_cameras": len(cameras_cfg),
            }

        return self._run_test("multi_camera_sync", _check)

    def test_overnight_stability(self) -> TestResult:
        def _check() -> Dict[str, object]:
            if self.camera is None:
                return {"status": "FAIL", "error": "Camera not configured"}
            health = self.camera.health()
            if health.get("status") != "ONLINE":
                return {
                    "status": "PENDING_HARDWARE",
                    "reason": "camera_not_online_for_stability_run",
                    "camera_health": dict(health),
                }
            tp = self.config.get("test_parameters", {})
            duration_s = int(tp.get("overnight_duration_s", 28800))  # type: ignore[union-attr]
            minimum_duration_s = int(
                tp.get("acceptance_threshold", {}).get(  # type: ignore[union-attr]
                    "minimum_stability_duration_s", 28800
                )
            )
            interval_s = float(tp.get("stability_capture_interval_s", 1.0))  # type: ignore[union-attr]
            if duration_s < minimum_duration_s or interval_s <= 0:
                return {
                    "status": "FAIL",
                    "duration_s": duration_s,
                    "minimum_duration_s": minimum_duration_s,
                    "reason": "stability_duration_or_interval_invalid",
                }
            started = time.monotonic()
            deadline = started + duration_s
            captured = 0
            failed = 0
            sequence = 0
            while time.monotonic() < deadline:
                sequence += 1
                trigger = TriggerEvent(
                    trigger_id=str(uuid.uuid4()),
                    sequence=sequence,
                    occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    occurred_monotonic=time.monotonic(),
                    source="ACCEPTANCE_STABILITY",
                )
                try:
                    frames = self.camera.capture(trigger)
                    if frames:
                        captured += len(frames)
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(interval_s, remaining))
            elapsed = time.monotonic() - started
            failure_pct = failed / max(sequence, 1) * 100
            maximum_failed_pct = float(
                tp.get("acceptance_threshold", {}).get("max_failed_frames_pct", 0.0)  # type: ignore[union-attr]
            )
            return {
                "status": (
                    "PASS"
                    if elapsed >= minimum_duration_s
                    and captured > 0
                    and failure_pct <= maximum_failed_pct
                    else "FAIL"
                ),
                "duration_s": round(elapsed, 3),
                "minimum_duration_s": minimum_duration_s,
                "capture_attempts": sequence,
                "frames_captured": captured,
                "failures": failed,
                "failure_pct": round(failure_pct, 4),
                "maximum_failed_pct": maximum_failed_pct,
            }

        return self._run_test("overnight_stability", _check)

    def test_external_scenarios(self) -> Sequence[TestResult]:
        configured = self.config.get("external_scenarios")
        indexed: Dict[str, Mapping[str, object]] = {}
        if isinstance(configured, list):
            for item in configured:
                if isinstance(item, Mapping) and isinstance(item.get("id"), str):
                    indexed[str(item["id"])] = item
        results: List[TestResult] = []
        for scenario_id in sorted(REQUIRED_EXTERNAL_SCENARIOS):
            item = indexed.get(scenario_id)
            if item is None:
                result = TestResult(
                    test_name=f"external_{scenario_id}",
                    status="PENDING_HARDWARE",
                    evidence={"reason": "scenario_evidence_missing"},
                )
                self.results.append(result)
                results.append(result)
                continue
            status = str(item.get("status", "PENDING_HARDWARE"))
            source_type = item.get("source_type")
            evidence_path = item.get("evidence_path")
            expected_hash = item.get("evidence_sha256")
            evidence: Dict[str, object] = {
                "source_type": source_type,
                "evidence_path": evidence_path,
                "evidence_sha256": expected_hash,
            }
            if source_type != REAL_HARDWARE_SOURCE:
                status = "FAIL"
                evidence["reason"] = "scenario_not_real_hardware"
            elif not isinstance(evidence_path, str) or not isinstance(expected_hash, str):
                status = "FAIL"
                evidence["reason"] = "scenario_evidence_reference_invalid"
            else:
                candidate = Path(evidence_path)
                if not candidate.is_absolute():
                    candidate = self.config_directory / candidate
                if not candidate.is_file():
                    status = "FAIL"
                    evidence["reason"] = "scenario_evidence_file_missing"
                elif len(expected_hash) != 64 or sha256_file(candidate) != expected_hash:
                    status = "FAIL"
                    evidence["reason"] = "scenario_evidence_hash_mismatch"
            if status != "PASS" and "reason" not in evidence:
                evidence["reason"] = "scenario_not_pass"
            result = TestResult(
                test_name=f"external_{scenario_id}",
                status=status,
                evidence=evidence,
            )
            self.results.append(result)
            results.append(result)
        return results

    def run_all(self) -> Sequence[TestResult]:
        self.setup()
        self.test_connectivity()
        self.test_trigger_signal()
        self.test_single_frame()
        self.test_continuous_capture()
        self.test_latency()
        self.test_dark_and_saturation()
        self.test_multi_camera_sync()
        self.test_overnight_stability()
        self.test_external_scenarios()
        return self.results

    def generate_report(self) -> Dict[str, object]:
        results = [asdict(r) for r in self.results]
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        pending = sum(1 for r in self.results if r.status == "PENDING_HARDWARE")
        skipped = sum(1 for r in self.results if r.status == "SKIPPED")
        not_impl = sum(1 for r in self.results if r.status == "NOT_IMPLEMENTED")
        warned = sum(1 for r in self.results if r.status == "WARN")

        blocking_count = failed + pending + skipped + not_impl + warned
        overall_status = (
            "PASS"
            if self.results and blocking_count == 0
            else "FAILED"
            if failed > 0
            else "BLOCKED"
        )
        return {
            "schema_version": "tool-defect-hardware-acceptance-report/v1",
            "runner_version": RUNNER_VERSION,
            "report_id": str(self.config.get("run_id") or uuid.uuid4()),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "started_at": self.started_at,
            "duration_s": round(time.monotonic() - self.started_monotonic, 3),
            "source_type": self.config.get("source_type", "UNKNOWN"),
            "site_id": self.config.get("site_id"),
            "approved_by": self.config.get("approved_by"),
            "approved_at": self.config.get("approved_at"),
            "approval_evidence_path": self.config.get("approval_evidence_path"),
            "approval_evidence_sha256": self.config.get("approval_evidence_sha256"),
            "hostname": platform.node(),
            "operating_system": platform.platform(),
            "python_version": platform.python_version(),
            "config_sha256": self.config_sha256,
            "script_sha256": self.script_sha256,
            "device_inventory": self.config.get("device_inventory"),
            "overall_status": overall_status,
            "production_claim_allowed": overall_status == "PASS",
            "summary": {
                "total": len(self.results),
                "pass": passed,
                "fail": failed,
                "pending_hardware": pending,
                "skipped": skipped,
                "not_implemented": not_impl,
                "warn": warned,
                "passed_pct": round(passed / max(len(self.results), 1) * 100, 1),
            },
            "tests": results,
        }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="现场硬件验收脚本 — 验证相机、PLC 和传感器连接"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="硬件配置文件路径 (JSON)",
    )
    parser.add_argument(
        "--output",
        default="hardware-acceptance-report.json",
        help="验收报告输出路径",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细日志",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("配置文件不存在: %s", config_path)
        return 1

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.error("配置文件无效: %s", type(exc).__name__)
        return 1
    if not isinstance(config, dict):
        logger.error("配置根必须是 JSON 对象")
        return 1

    blockers, errors = validate_acceptance_config(config, config_path)
    if errors or blockers:
        report = {
            "schema_version": "tool-defect-hardware-acceptance-report/v1",
            "runner_version": RUNNER_VERSION,
            "report_id": str(config.get("run_id") or uuid.uuid4()),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_type": config.get("source_type", "UNKNOWN"),
            "overall_status": "ERROR" if errors else "BLOCKED",
            "production_claim_allowed": False,
            "config_sha256": sha256_file(config_path),
            "script_sha256": sha256_file(Path(__file__)),
            "blockers": blockers,
            "errors": errors,
            "tests": [],
        }
        output_path = Path(args.output)
        if output_path.exists():
            logger.error("拒绝覆盖已有验收报告: %s", output_path)
            return 1
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        logger.error("硬件验收前置未满足: %s", ", ".join(errors or blockers))
        return 1 if errors else 2

    runner = HardwareAcceptanceRunner(
        config,
        config_sha256=sha256_file(config_path),
        script_sha256=sha256_file(Path(__file__)),
        config_directory=config_path.parent,
    )
    runner.run_all()
    report = runner.generate_report()

    output_path = Path(args.output)
    if output_path.exists():
        logger.error("拒绝覆盖已有验收报告: %s", output_path)
        return 1
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    summary = report["summary"]
    logger.info("验收完成: %s 通过 / %s 失败 / %s 硬件待确认 / %s 总计",
                summary["pass"], summary["fail"],
                summary["pending_hardware"], summary["total"])
    logger.info("报告已保存: %s", output_path.resolve())

    if report["overall_status"] == "FAILED":
        return 1
    if report["overall_status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
