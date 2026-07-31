"""PLC 触发适配器 — 实现 TriggerAdapter 协议。

支持 Modbus TCP、PROFINET、EtherCAT 协议栈桩。
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
    import pyModbusTCP  # noqa: F401

    _MODBUS_AVAILABLE = True
except ImportError:
    _MODBUS_AVAILABLE = False

try:
    pass  # PROFINET SDK 占位
    _PROFINET_AVAILABLE = False
except ImportError:
    _PROFINET_AVAILABLE = False

try:
    pass  # EtherCAT SDK 占位
    _ETHERCAT_AVAILABLE = False
except ImportError:
    _ETHERCAT_AVAILABLE = False

_VALID_PROTOCOLS = frozenset({"modbus_tcp", "profinet", "ethercat"})


class _PLCTriggerAdapter:
    """PLC 触发适配器。

    通过 vendor_config 配置协议参数。poll() 读取触发信号并应用防抖。
    """

    def __init__(self, vendor_config: Mapping[str, Any]) -> None:
        self._config = dict(vendor_config)
        self._hardware_enabled = self._config.get("hardware_enabled") is True
        self._protocol = self._config.get("protocol", "modbus_tcp").lower()
        self._host = self._config.get("host", "")
        self._port = int(self._config.get("port", 502))
        self._register_address = int(self._config.get("register_address", 0))
        self._register_count = int(self._config.get("register_count", 1))
        self._debounce_ms = int(self._config.get("debounce_ms", 20))
        self._poll_interval_ms = int(self._config.get("poll_interval_ms", 10))
        self._signal_active_value = self._config.get("signal_active_value", 1)
        self._connection_timeout_s = float(self._config.get("connection_timeout_s", 3.0))
        self._unit_id = int(self._config.get("unit_id", 1))
        self._source_label = self._config.get("source_label", "PLC")
        self._device: object = None
        self._sequence = 0
        self._last_high_time: Optional[float] = None
        self._last_event_time: Optional[float] = None

        self._validate_config()

    def _validate_config(self) -> None:
        if "hardware_enabled" in self._config and not isinstance(
            self._config["hardware_enabled"], bool
        ):
            raise ValueError("PLC config: hardware_enabled must be boolean")
        if self._protocol not in _VALID_PROTOCOLS:
            raise ValueError(
                f"PLC config: unknown protocol '{self._protocol}'. "
                f"Valid: {sorted(_VALID_PROTOCOLS)}"
            )
        if not self._host:
            raise ValueError("PLC config: 'host' is required")
        if self._port < 1 or self._port > 65535:
            raise ValueError(f"PLC config: invalid port {self._port}")
        if self._debounce_ms < 0:
            raise ValueError("PLC config: debounce_ms must be >= 0")
        if self._poll_interval_ms < 1:
            raise ValueError("PLC config: poll_interval_ms must be >= 1")
        if self._register_address < 0:
            raise ValueError("PLC config: register_address must be >= 0")

    def poll(self) -> Optional[TriggerEvent]:
        if not self._hardware_enabled:
            logger.debug("PLC trigger poll blocked by PENDING_HARDWARE guard")
            return None

        sdk_available = self._check_sdk()
        if not sdk_available:
            logger.error(
                "PLC SDK for protocol '%s' is not installed", self._protocol
            )
            return None

        try:
            return self._do_poll()
        except Exception as exc:
            logger.error("PLC poll failed for %s:%s: %s", self._host, self._port, exc)
            return None

    def _check_sdk(self) -> bool:
        if self._protocol == "modbus_tcp":
            return _MODBUS_AVAILABLE
        if self._protocol == "profinet":
            return _PROFINET_AVAILABLE
        if self._protocol == "ethercat":
            return _ETHERCAT_AVAILABLE
        return False

    def _do_poll(self) -> Optional[TriggerEvent]:
        now_mono = time.monotonic()

        signal = self._read_signal()
        if signal != self._signal_active_value:
            self._last_high_time = None
            return None

        if self._last_high_time is None:
            self._last_high_time = now_mono
            return None

        high_duration_ms = (now_mono - self._last_high_time) * 1000
        if high_duration_ms < self._debounce_ms:
            return None

        if (
            self._last_event_time is not None
            and (now_mono - self._last_event_time) * 1000 < self._debounce_ms
        ):
            return None

        self._sequence += 1
        self._last_event_time = now_mono

        return TriggerEvent(
            trigger_id=str(uuid.uuid4()),
            sequence=self._sequence,
            occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            occurred_monotonic=now_mono,
            source=self._source_label,
            metadata={
                "protocol": self._protocol,
                "host": self._host,
                "register": self._register_address,
                "debounce_ms": self._debounce_ms,
            },
        )

    def _read_signal(self) -> int:
        if self._protocol == "modbus_tcp" and _MODBUS_AVAILABLE:
            return self._read_modbus()
        if self._protocol == "profinet":
            return self._read_profinet()
        if self._protocol == "ethercat":
            return self._read_ethercat()
        return 0

    def _read_modbus(self) -> int:
        import pyModbusTCP.client as _modbus_client  # type: ignore[import-untyped]

        client = _modbus_client.ModbusClient(
            host=self._host,
            port=self._port,
            unit_id=self._unit_id,
            timeout=self._connection_timeout_s,
        )
        if not client.open():
            return 0
        try:
            regs = client.read_holding_registers(
                self._register_address, self._register_count
            )
            if not regs:
                return 0
            return regs[0]
        finally:
            client.close()

    def _read_profinet(self) -> int:
        return 0

    def _read_ethercat(self) -> int:
        return 0


def create_plc_trigger(vendor_config: Mapping[str, Any]) -> TriggerAdapter:
    """创建 PLC 触发适配器。"""
    return _PLCTriggerAdapter(vendor_config)
