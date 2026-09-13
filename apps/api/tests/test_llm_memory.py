import json

import httpx
import pytest

from tevion_api import services
from tevion_api.learning import ProjectedPreference
from tevion_api.llm_memory import DeepSeekMemorySummarizer, MemorySummaryError


def _adapter(content: str, *, status_code: int = 200) -> DeepSeekMemorySummarizer:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(
            status_code,
            json={"choices": [{"message": {"content": content}}]},
            request=request,
        )

    return DeepSeekMemorySummarizer(
        api_key="test-secret",
        base_url="https://deepseek.test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_summarizer_parses_json_response() -> None:
    adapter = _adapter(json.dumps({"summary": "清爽自然", "avoid": ["过度暖色"], "guidance": "保留自然光"}))
    result = adapter.summarize([{"selected": True, "direction": "自然光"}])
    assert result.summary == "清爽自然"
    assert result.avoid == ("过度暖色",)
    assert result.guidance == "保留自然光"


def test_summarizer_parses_markdown_json() -> None:
    adapter = _adapter('```json\n{"summary":"年轻清透","avoid":[],"guidance":"减少复杂背景"}\n```')
    assert adapter.summarize([{"rejected": True}]).guidance == "减少复杂背景"


@pytest.mark.parametrize(
    "payload",
    [
        {"summary": "", "avoid": [], "guidance": "ok"},
        {"summary": "ok", "avoid": [1], "guidance": "ok"},
        {"summary": "ok", "avoid": [], "guidance": ""},
        {"summary": "ok", "avoid": [], "guidance": "x" * 501},
    ],
)
def test_summarizer_rejects_untrusted_shape(payload: dict) -> None:
    adapter = _adapter(json.dumps(payload))
    with pytest.raises(MemorySummaryError):
        adapter.summarize([{"selected": True}])


def test_summarizer_does_not_expose_api_key_in_error() -> None:
    adapter = _adapter("not-json", status_code=500)
    with pytest.raises(httpx.HTTPStatusError) as error:
        adapter.summarize([{"selected": True}])
    assert "test-secret" not in str(error.value)


def test_from_environment_requires_explicit_enablement_or_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MEMORY_ENABLED", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert DeepSeekMemorySummarizer.from_environment() is None
    monkeypatch.setenv("LLM_MEMORY_ENABLED", "true")
    assert DeepSeekMemorySummarizer.from_environment() is None


def test_project_memory_is_injected_without_replacing_current_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        services,
        "project_preferences_for_task",
        lambda *args, **kwargs: [
            ProjectedPreference(
                scope="project",
                scope_id="project-1",
                key="视觉总结",
                value="清爽自然",
                weight=0.8,
                source="inference",
                evidence_count=2,
                id="pref-1",
                evidence_ids=("event-1",),
            )
        ],
    )
    task = type("Task", (), {"session": type("Session", (), {"id": "task-1"})()})()
    prompt, adopted = services.generation_prompt_with_project_memory(
        object(), task, user_id="user-1", base_prompt="拍一张侧脸肖像"
    )
    assert "拍一张侧脸肖像" in prompt
    assert "清爽自然" in prompt
    assert adopted[0].evidence_ids == ("event-1",)
