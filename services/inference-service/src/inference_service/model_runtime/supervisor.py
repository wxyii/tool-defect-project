"""有限数量运行槽的精确模型选择器。"""

from typing import Iterable

from tool_defect.plugin_api import PluginError, PluginErrorCode

from inference_service.model_runtime.slot import RuntimeSlot


class RuntimeSupervisor:
    def __init__(self, slots: Iterable[RuntimeSlot]):
        self._slots = {slot.slot_id: slot for slot in slots}
        if not self._slots:
            raise ValueError("运行时至少需要一个模型槽")

    def resolve(
        self,
        model_version: str,
        model_sha256: str,
        device: str,
    ) -> RuntimeSlot:
        matches = [
            slot
            for slot in self._slots.values()
            if slot.ready
            and slot.profile.device == device
            and slot.model_identity == (model_version, model_sha256)
        ]
        if len(matches) != 1:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "runtime_slot",
                "找不到唯一的精确已预热模型槽",
                {
                    "model_version": model_version,
                    "model_sha256": model_sha256,
                    "device": device,
                    "matches": len(matches),
                },
            )
        return matches[0]

    def health(self) -> tuple[dict, ...]:
        return tuple(
            slot.health()
            for slot in sorted(self._slots.values(), key=lambda item: item.slot_id)
        )

    async def close(self) -> None:
        for slot in self._slots.values():
            await slot.close()
