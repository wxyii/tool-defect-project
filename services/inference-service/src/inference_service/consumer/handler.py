"""只有后端接受结果后才确认队列消息。"""

from typing import Any, Mapping, Protocol

from inference_service.orchestration.pipeline import (
    InferenceOrchestrator,
    InferenceTask,
)
from inference_service.orchestration.single_item import (
    SingleItemOrchestrator,
    SingleItemTask,
)


class MessageDelivery(Protocol):
    async def ack(self) -> None:
        ...

    async def reject_to_dead_letter(self) -> None:
        ...


class InferenceMessageHandler:
    def __init__(self, orchestrator: InferenceOrchestrator):
        self._orchestrator = orchestrator

    async def handle(
        self,
        task: InferenceTask,
        delivery: MessageDelivery,
    ) -> bool:
        acceptance = await self._orchestrator.execute(task)
        if acceptance.accepted:
            await delivery.ack()
            return True
        return False


class SingleItemMessageHandler:
    """第二版入口：严格解析单个 image，事件发布成功后才确认。"""

    def __init__(self, orchestrator: SingleItemOrchestrator):
        self._orchestrator = orchestrator

    async def handle(
        self,
        payload: Mapping[str, Any],
        delivery: MessageDelivery,
    ) -> bool:
        task = SingleItemTask.from_contract(payload)
        accepted = await self._orchestrator.execute(task)
        if accepted:
            await delivery.ack()
            return True
        return False
