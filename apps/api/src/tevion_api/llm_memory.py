"""Bounded DeepSeek adapter for project-memory summarization."""

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


class MemorySummaryError(RuntimeError):
    """Raised when the optional LLM memory summary cannot be trusted."""


@dataclass(frozen=True)
class MemorySummary:
    summary: str
    avoid: tuple[str, ...]
    guidance: str


class DeepSeekMemorySummarizer:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout_seconds: float = 8.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise MemorySummaryError("DeepSeek API key is required")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = http_client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = http_client is None

    @classmethod
    def from_environment(cls) -> "DeepSeekMemorySummarizer | None":
        if os.environ.get("LLM_MEMORY_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
            return None
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return None
        try:
            timeout_seconds = float(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "8"))
        except ValueError:
            return None
        return cls(
            api_key=api_key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            timeout_seconds=timeout_seconds,
        )

    def summarize(self, feedback: list[dict[str, Any]]) -> MemorySummary:
        if not feedback:
            raise MemorySummaryError("feedback is required")
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "temperature": 0,
                "max_tokens": 500,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是 Tevion 的项目视觉记忆总结器。只根据反馈证据总结项目偏好，"
                            "不要编造人物身份、隐私或未出现的视觉属性。只返回 JSON："
                            '{"summary":"...","avoid":["..."],"guidance":"..."}。'
                        ),
                    },
                    {"role": "user", "content": json.dumps(feedback, ensure_ascii=False)},
                ],
            },
        )
        response.raise_for_status()
        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
            content = content.strip()
            if content.startswith("```"):
                content = content[3:].strip()
                if content.lower().startswith("json"):
                    content = content[4:].strip()
                if content.endswith("```"):
                    content = content[:-3].strip()
            data = json.loads(content)
            summary = data.get("summary")
            avoid = data.get("avoid", [])
            guidance = data.get("guidance")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise MemorySummaryError("DeepSeek returned malformed memory summary") from exc
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 255:
            raise MemorySummaryError("DeepSeek summary is invalid")
        if not isinstance(avoid, list) or len(avoid) > 8 or not all(isinstance(item, str) and item.strip() for item in avoid):
            raise MemorySummaryError("DeepSeek avoid list is invalid")
        if not isinstance(guidance, str) or not guidance.strip() or len(guidance) > 500:
            raise MemorySummaryError("DeepSeek guidance is invalid")
        return MemorySummary(summary=summary.strip(), avoid=tuple(item.strip() for item in avoid), guidance=guidance.strip())

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


__all__ = ["DeepSeekMemorySummarizer", "MemorySummary", "MemorySummaryError"]
