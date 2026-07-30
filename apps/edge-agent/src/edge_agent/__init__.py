"""刀具缺陷采集端。

采集端只维护同步投影，不产生最终业务处置。
"""

from .local_queue.models import LocalCaptureState

__all__ = ["LocalCaptureState"]
