"""DeepSeek 视觉 API 客户端。

密钥只从 DEEPSEEK_API_KEY 环境变量读取，绝不写入配置文件或输出日志。
"""

import base64
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from tool_defect.deepseek.prompts import SYSTEM_PROMPT, build_user_prompt
from tool_defect.deepseek.schema import parse_json_content


try:  # 允许在未安装 openai 时运行离线单元测试
    from openai import OpenAI
except ImportError:  # pragma: no cover - 由运行环境决定
    OpenAI = None


SUPPORTED_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
MAX_IMAGE_BYTES = 32 * 1024 * 1024


def image_to_data_url(image_path: Path) -> str:
    image_path = Path(image_path)
    suffix = image_path.suffix.lower()
    mime_type = SUPPORTED_MIME_TYPES.get(suffix)
    if mime_type is None:
        raise ValueError(f"不支持的图片格式: {image_path.suffix}")
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    if image_path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError(f"图片超过 32 MiB API 限制: {image_path}")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


class DeepSeekVisionClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek-flash",
        base_url: str = "https://api.deepseek.com",
        timeout: float = 120.0,
        thinking: str = "disabled",
        reasoning_effort: Optional[str] = None,
        max_retries: int = 2,
        client: Any = None,
    ):
        resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not resolved_key and client is None:
            raise ValueError(
                "未找到 API 密钥。请先设置环境变量 DEEPSEEK_API_KEY；不要把密钥写入代码。"
            )
        if thinking not in {"enabled", "disabled"}:
            raise ValueError("thinking 必须是 enabled 或 disabled")
        self.model = model
        self.base_url = base_url
        self.timeout = float(timeout)
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.max_retries = max(0, int(max_retries))
        if client is not None:
            self._client = client
        else:
            if OpenAI is None:
                raise RuntimeError("未安装 openai，请执行: pip install 'openai>=1.0,<2'")
            self._client = OpenAI(
                api_key=resolved_key,
                base_url=base_url,
                timeout=self.timeout,
            )

    def analyze_image(
        self,
        image_path: Path,
        prompt: Optional[str] = None,
        system_prompt: str = SYSTEM_PROMPT,
        detail: str = "original",
        max_tokens: int = 500,
    ) -> Dict[str, Any]:
        if detail not in {"low", "high", "original", "auto"}:
            raise ValueError("detail 必须是 low、high、original 或 auto")
        image_path = Path(image_path)
        image_url = image_to_data_url(image_path)
        user_prompt = prompt or build_user_prompt(image_path.name)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url, "detail": detail},
                    },
                ],
            },
        ]
        request = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "response_format": {"type": "json_object"},
            "max_tokens": int(max_tokens),
        }
        request["extra_body"] = {"thinking": {"type": self.thinking}}
        if self.reasoning_effort:
            request["reasoning_effort"] = self.reasoning_effort

        started = time.perf_counter()
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(**request)
                choices = _field(response, "choices", [])
                if not choices:
                    raise ValueError("API 返回中没有 choices")
                message = _field(choices[0], "message", {})
                content = _field(message, "content", "")
                parsed = parse_json_content(content)
                usage = _field(response, "usage", {})
                usage_dict = {
                    key: _field(usage, key)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if _field(usage, key) is not None
                }
                return {
                    "parsed": parsed,
                    "raw_content": content,
                    "model": _field(response, "model", self.model),
                    "response_id": _field(response, "id", ""),
                    "finish_reason": _field(choices[0], "finish_reason", ""),
                    "usage": usage_dict,
                    "elapsed_seconds": round(time.perf_counter() - started, 4),
                }
            except Exception as error:  # API、解析和限流错误均不应放行
                last_error = error
                if attempt < self.max_retries:
                    time.sleep(2**attempt)
        raise RuntimeError(
            f"DeepSeek 图片分析失败（已重试 {self.max_retries} 次）：{type(last_error).__name__}"
        ) from last_error
