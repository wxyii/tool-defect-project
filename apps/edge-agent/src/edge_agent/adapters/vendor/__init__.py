"""厂商硬件适配器 — 1.0.0 — 需要现场硬件。

提供 GigE Vision、USB/UVC 相机、PLC 和光学传感器的真实硬件适配器。
所有厂商 SDK 导入均受 try/except ImportError 保护；在开发环境中通过
PENDING_HARDWARE 守卫阻止真实硬件访问。

注意：必须安装目标厂商 SDK 并在目标工控机上运行。
"""

__version__ = "1.0.0"

from .gige_camera import PENDING_HARDWARE as _gige_hw
from .gige_camera import create_gige_camera
from .optical_sensor import PENDING_HARDWARE as _optical_hw
from .optical_sensor import create_optical_trigger
from .plc_trigger import PENDING_HARDWARE as _plc_hw
from .plc_trigger import create_plc_trigger
from .usb_camera import PENDING_HARDWARE as _usb_hw
from .usb_camera import create_usb_camera

__all__ = [
    "create_gige_camera",
    "create_optical_trigger",
    "create_plc_trigger",
    "create_usb_camera",
]
