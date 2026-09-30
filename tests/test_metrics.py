import json
from datetime import datetime, timezone
from pathlib import Path

from app.dashboard import build_dashboard_data
from app.metrics import percentile


def test_percentile_basic() -> None:
    assert percentile([100, 200, 300, 400], 50) >= 100


def test_dashboard_aggregates_sli_cost_tokens_and_quality(tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    records = [
        {
            "ts": "2026-09-30T12:00:05Z",
            "event": "request_received",
            "correlation_id": "req-success1",
        },
        {
            "ts": "2026-09-30T12:00:06Z",
            "event": "response_sent",
            "latency_ms": 600,
            "ttft_ms": 100,
            "tokens_in": 40,
            "tokens_out": 60,
            "cost_usd": 0.001,
            "quality_score": 0.8,
            "tool_name": "retrieval",
            "tool_success": True,
        },
        {
            "ts": "2026-09-30T11:59:05Z",
            "event": "request_received",
            "correlation_id": "req-failure1",
        },
        {
            "ts": "2026-09-30T11:59:06Z",
            "event": "request_failed",
            "tool_name": "retrieval",
            "tool_success": False,
        },
    ]
    log_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    result = build_dashboard_data(
        log_path,
        now=datetime(2026, 9, 30, 12, 0, 30, tzinfo=timezone.utc),
    )

    assert len(result["labels"]) == 60
    assert result["summary"]["request_count"] == 2
    assert result["summary"]["error_rate_pct"] == 50
    assert result["summary"]["retrieval_success_pct"] == 50
    assert result["summary"]["latency_p95_ms"] == 600
    assert result["summary"]["ttft_p95_ms"] == 100
    assert result["summary"]["cost_usd"] == 0.001
    assert result["summary"]["tokens_in"] == 40
    assert result["summary"]["tokens_out"] == 60
    assert result["summary"]["quality_score"] == 0.8
