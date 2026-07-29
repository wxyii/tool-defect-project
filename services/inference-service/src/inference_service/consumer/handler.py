"""只有后端接受结果后才确认队列消息。"""

from typing import Protocol

from inference_service.orchestration.pipeline import (
    InferenceOrchestrator,
    InferenceTask,
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
