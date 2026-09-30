from __future__ import annotations

from contextlib import contextmanager

from app import agent as agent_module


class ManagedPrompt:
    version = 3

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.span_updates: list[dict] = []
        self.observation_starts: list[dict] = []
        self.observation_updates: list[dict] = []

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)

    def start_as_current_observation(self, **kwargs):
        self.observation_starts.append(kwargs)
        client = self

        @contextmanager
        def observation_context():
            class Observation:
                def update(self, **update_kwargs) -> None:
                    client.observation_updates.append(update_kwargs)

            yield Observation()

        return observation_context()


def test_agent_records_prompt_version_with_v4_observation_api(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    propagated: list[dict] = []

    @contextmanager
    def record_attributes(**kwargs):
        propagated.append(kwargs)
        yield

    monkeypatch.setattr(agent_module, "propagate_attributes", record_attributes)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain monitoring traces; email student@example.com",
        correlation_id="req-12345678",
    )

    span_update = client.span_updates[-1]
    assert span_update["metadata"] == {
        "doc_count": 1,
        "query_preview": "Explain monitoring traces; email [REDACTED_EMAIL]",
        "prompt_name": "day13-chat",
        "prompt_label": "production",
        "prompt_version": "3",
        "prompt_source": "langfuse",
        "prompt_fetch_error": "",
    }
    assert span_update["version"] == "3"
    assert propagated[0]["metadata"]["correlation_id"] == "req-12345678"
    assert len(propagated) == 1
    assert [item["as_type"] for item in client.observation_starts] == [
        "retriever",
        "generation",
    ]
    assert client.observation_starts[0]["name"] == "retrieval"
    assert client.observation_starts[1]["model"] == "claude-sonnet-4-5"
    assert client.observation_starts[1]["prompt"] is client.prompt
    assert "student@example.com" not in str(client.observation_starts)
    generation_update = client.observation_updates[-1]
    assert generation_update["usage_details"]["input"] > 0
    assert generation_update["usage_details"]["output"] > 0
    assert generation_update["cost_details"]["input"] > 0
    assert generation_update["cost_details"]["output"] > 0
