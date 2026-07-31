"""光学 / 传感器触发适配器 — 实现 TriggerAdapter 协议。

用于简单数字 I/O 或传感器触发场景。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Mapping, Optional

from ..ports import TriggerAdapter, TriggerEvent

logger = logging.getLogger(__name__)

PENDING_HARDWARE = True

try:
    pass  # GPIO SDK 占位（如 RPi.GPIO、libgpiod）
    _GPIO_AVAILABLE = False
except ImportError:
    _GPIO_AVAILABLE = False

_VALID_EDGES = frozenset({"rising", "falling", "both"})


class _OpticalTriggerAdapter:
    """光学 / 传感器触发适配器。

    通过 GPIO 引脚检测触发边沿，支持防抖和边沿选择。
    """

    def __init__(self, vendor_config: Mapping[str, Any]) -> None:
        self._config = dict(vendor_config)
        self._hardware_enabled = self._config.get("hardware_enabled") is True
        self._gpio_pin = int(self._config.get("gpio_pin", 0))
        self._trigger_edge = self._config.get("trigger_edge", "rising").lower()
        self._debounce_ms = int(self._config.get("debounce_ms", 20))
        self._pull_mode = self._config.get("pull_mode", "down")
        self._source_label = self._config.get("source_label", "OPTICAL")
        self._holdoff_ms = int(self._config.get("holdoff_ms", 100))
        self._signal_invert = bool(self._config.get("signal_invert", False))
        self._read_interval_ms = int(self._config.get("read_interval_ms", 5))

        self._sequence = 0
        self._last_state: Optional[int] = None
        self._last_event_time: Optional[float] = None
        self._validate_config()

    def _validate_config(self) -> None:
        if "hardware_enabled" in self._config and not isinstance(
            self._config["hardware_enabled"], bool
        ):
            raise ValueError("Optical trigger config: hardware_enabled must be boolean")
        if self._gpio_pin < 0:
            raise ValueError(
                f"Optical trigger config: gpio_pin must be non-negative, "
                f"got {self._gpio_pin}"
            )
        if self._trigger_edge not in _VALID_EDGES:
            raise ValueError(
                f"Optical trigger config: unknown trigger_edge "
                f"'{self._trigger_edge}'. Valid: {sorted(_VALID_EDGES)}"
            )
        if self._debounce_ms < 0:
            raise ValueError("Optical trigger config: debounce_ms must be >= 0")
        if self._holdoff_ms < 0:
            raise ValueError("Optical trigger config: holdoff_ms must be >= 0")
        if self._read_interval_ms < 1:
            raise ValueError("Optical trigger config: read_interval_ms must be >= 1")
        if self._pull_mode not in ("up", "down", "none"):
            raise ValueError(
                f"Optical trigger config: unknown pull_mode '{self._pull_mode}'"
            )

    def poll(self) -> Optional[TriggerEvent]:
        if not self._hardware_enabled:
            logger.debug("Optical sensor poll blocked by PENDING_HARDWARE guard")
            return None

        if not _GPIO_AVAILABLE:
            logger.error("GPIO SDK is not installed on this machine")
            return None

        try:
            return self._do_poll()
        except Exception as exc:
            logger.error("Optical sensor poll on pin %s failed: %s", self._gpio_pin, exc)
            return None

    def _do_poll(self) -> Optional[TriggerEvent]:
        now_mono = time.monotonic()

        current_raw = self._read_gpio()
        current_state = 1 if current_raw else 0
        if self._signal_invert:
            current_state = 1 - current_state

        if self._last_state is None:
            self._last_state = current_state
            return None

        previous = self._last_state
        self._last_state = current_state

        edge_detected = False
        if self._trigger_edge == "rising" and previous == 0 and current_state == 1:
            edge_detected = True
        elif self._trigger_edge == "falling" and previous == 1 and current_state == 0:
            edge_detected = True
        elif self._trigger_edge == "both" and previous != current_state:
            edge_detected = True

        if not edge_detected:
            return None

        if (
            self._last_event_time is not None
            and (now_mono - self._last_event_time) * 1000 < self._holdoff_ms
        ):
            return None

        self._last_event_time = now_mono
        self._sequence += 1

        try:
            time.sleep(self._debounce_ms / 1000.0)
        except Exception:
            pass

        return TriggerEvent(
            trigger_id=str(uuid.uuid4()),
            sequence=self._sequence,
            occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            occurred_monotonic=now_mono,
            source=self._source_label,
            metadata={
                "gpio_pin": self._gpio_pin,
                "trigger_edge": self._trigger_edge,
                "debounce_ms": self._debounce_ms,
                "signal_raw": current_raw,
            },
        )

    def _read_gpio(self) -> int:
        if not _GPIO_AVAILABLE:
            return 0
        return 0


def create_optical_trigger(vendor_config: Mapping[str, Any]) -> TriggerAdapter:
    """创建光学 / 传感器触发适配器。"""
    return _OpticalTriggerAdapter(vendor_config)
