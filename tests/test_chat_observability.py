from __future__ import annotations

import json
import asyncio
from pathlib import Path

import httpx

from app import logging_config
from app.main import app
from app.pii import hash_user_id


def test_chat_response_log_exposes_quality_for_dashboard(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/chat",
                json={
                    "user_id": "student-01",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "Explain observability",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    response_event = next(event for event in events if event["event"] == "response_sent")
    request_event = next(event for event in events if event["event"] == "request_received")
    assert response_event["quality_score"] == response.json()["quality_score"]
    assert response_event["ttft_ms"] == response.json()["ttft_ms"]
    assert response_event["tool_name"] == "retrieval"
    assert response_event["tool_success"] is True
    correlation_id = response.headers["x-request-id"]
    assert correlation_id.startswith("req-")
    assert len(correlation_id) == 12
    assert response.json()["correlation_id"] == correlation_id
    assert request_event["correlation_id"] == correlation_id
    assert response_event["correlation_id"] == correlation_id
    assert float(response.headers["x-response-time-ms"]) >= 0
    for event in (request_event, response_event):
        assert event["user_id_hash"] == hash_user_id("student-01")
        assert event["session_id"] == "session-01"
        assert event["feature"] == "qa"
        assert event["model"] == "claude-sonnet-4-5"
        assert event["env"] == "dev"


def test_chat_honors_request_id_and_does_not_leak_it_to_next_request(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send_requests() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            payload = {
                "user_id": "student-02",
                "session_id": "session-02",
                "feature": "qa",
                "message": "How do traces work?",
            }
            supplied = await client.post(
                "/chat", json=payload, headers={"x-request-id": "client-request-42"}
            )
            generated = await client.post("/chat", json=payload)
            return supplied, generated

    supplied_response, generated_response = asyncio.run(send_requests())

    assert supplied_response.headers["x-request-id"] == "client-request-42"
    generated_id = generated_response.headers["x-request-id"]
    assert generated_id.startswith("req-")
    assert generated_id != "client-request-42"
    assert generated_response.json()["correlation_id"] == generated_id
    records = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    request_ids = [
        event["correlation_id"]
        for event in records
        if event["event"] == "request_received"
    ]
    assert request_ids == ["client-request-42", generated_id]

    from scripts import validate_logs

    monkeypatch.setattr(validate_logs, "LOG_PATH", log_path)
    validate_logs.main()
    assert "Estimated Score: 100/100" in capsys.readouterr().out
