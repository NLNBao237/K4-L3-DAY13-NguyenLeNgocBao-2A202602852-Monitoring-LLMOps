from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = Path(__import__("os").getenv("LOG_PATH", REPO_ROOT / "data" / "logs.jsonl"))
DASHBOARD_CONFIG_PATH = REPO_ROOT / "config" / "dashboard.yaml"


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = max(0, math.ceil(percentile / 100 * len(values)) - 1)
    return float(values[index])


def _load_thresholds() -> dict[str, float]:
    payload = yaml.safe_load(DASHBOARD_CONFIG_PATH.read_text(encoding="utf-8"))
    panels = {panel["id"]: panel for panel in payload["dashboard"]["panels"]}
    return {
        "latency_p95_ms": float(panels["latency"]["threshold"]["value"]),
        "error_rate_pct": float(panels["errors"]["threshold"]["value"]),
        "cost_usd": float(panels["cost"]["threshold"]["value"]),
        "tokens": float(panels["tokens"]["threshold"]["value"]),
        "quality_score": float(panels["quality"]["threshold"]["value"]),
    }


def build_dashboard_data(
    log_path: Path = LOG_PATH, now: datetime | None = None
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window_minutes = 60
    window_end = now.replace(second=0, microsecond=0)
    window_start = window_end - timedelta(minutes=window_minutes - 1)
    labels = [
        (window_start + timedelta(minutes=offset)).strftime("%H:%M")
        for offset in range(window_minutes)
    ]
    minute_records: dict[datetime, list[dict[str, Any]]] = defaultdict(list)

    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = _parse_timestamp(record.get("ts"))
            if timestamp is None or timestamp < window_start or timestamp > now:
                continue
            minute = timestamp.replace(second=0, microsecond=0)
            minute_records[minute].append(record)

    series: dict[str, list[float | None]] = {
        name: []
        for name in (
            "latency_p50",
            "latency_p95",
            "latency_p99",
            "ttft_p95",
            "requests",
            "error_rate_pct",
            "retrieval_success_pct",
            "cost_usd",
            "tokens_in",
            "tokens_out",
            "quality_score",
        )
    }
    all_latencies: list[float] = []
    all_ttft: list[float] = []
    all_costs: list[float] = []
    all_tokens_in: list[float] = []
    all_tokens_out: list[float] = []
    all_quality: list[float] = []
    total_requests = 0
    total_errors = 0
    total_retrieval_attempts = 0
    successful_retrievals = 0

    for offset in range(window_minutes):
        minute = window_start + timedelta(minutes=offset)
        records = minute_records[minute]
        requests = sum(record.get("event") == "request_received" for record in records)
        errors = sum(record.get("event") == "request_failed" for record in records)
        responses = [record for record in records if record.get("event") == "response_sent"]
        latencies = [float(item["latency_ms"]) for item in responses if isinstance(item.get("latency_ms"), (int, float))]
        ttft = [float(item["ttft_ms"]) for item in responses if isinstance(item.get("ttft_ms"), (int, float))]
        costs = [float(item["cost_usd"]) for item in responses if isinstance(item.get("cost_usd"), (int, float))]
        tokens_in = [float(item["tokens_in"]) for item in responses if isinstance(item.get("tokens_in"), (int, float))]
        tokens_out = [float(item["tokens_out"]) for item in responses if isinstance(item.get("tokens_out"), (int, float))]
        quality = [float(item["quality_score"]) for item in responses if isinstance(item.get("quality_score"), (int, float))]
        retrieval = [
            record.get("tool_success")
            for record in records
            if record.get("tool_name") == "retrieval" and isinstance(record.get("tool_success"), bool)
        ]
        retrieval_successes = sum(value is True for value in retrieval)

        total_requests += requests
        total_errors += errors
        total_retrieval_attempts += len(retrieval)
        successful_retrievals += retrieval_successes
        all_latencies.extend(latencies)
        all_ttft.extend(ttft)
        all_costs.extend(costs)
        all_tokens_in.extend(tokens_in)
        all_tokens_out.extend(tokens_out)
        all_quality.extend(quality)

        series["latency_p50"].append(_percentile(latencies, 50))
        series["latency_p95"].append(_percentile(latencies, 95))
        series["latency_p99"].append(_percentile(latencies, 99))
        series["ttft_p95"].append(_percentile(ttft, 95))
        series["requests"].append(float(requests))
        series["error_rate_pct"].append(errors / requests * 100 if requests else None)
        series["retrieval_success_pct"].append(
            retrieval_successes / len(retrieval) * 100 if retrieval else None
        )
        series["cost_usd"].append(sum(costs))
        series["tokens_in"].append(sum(tokens_in))
        series["tokens_out"].append(sum(tokens_out))
        series["quality_score"].append(mean(quality) if quality else None)

    return {
        "window_minutes": window_minutes,
        "generated_at": now.isoformat(),
        "summary": {
            "request_count": total_requests,
            "error_rate_pct": total_errors / total_requests * 100 if total_requests else 0.0,
            "retrieval_success_pct": (
                successful_retrievals / total_retrieval_attempts * 100
                if total_retrieval_attempts
                else None
            ),
            "latency_p50_ms": _percentile(all_latencies, 50),
            "latency_p95_ms": _percentile(all_latencies, 95),
            "latency_p99_ms": _percentile(all_latencies, 99),
            "ttft_p95_ms": _percentile(all_ttft, 95),
            "cost_usd": round(sum(all_costs), 6),
            "tokens_in": int(sum(all_tokens_in)),
            "tokens_out": int(sum(all_tokens_out)),
            "quality_score": mean(all_quality) if all_quality else None,
        },
        "labels": labels,
        "series": series,
        "thresholds": _load_thresholds(),
    }


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Day 13 | Operations</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,500;6..72,600&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root { color-scheme: light; --ink:#172d2c; --muted:#647574; --line:#dce5e0; --paper:#f4f7f2; --surface:#fff; --teal:#187c73; --coral:#d1654d; --blue:#477fb1; --gold:#b37a22; --green:#4e8a58; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--paper); color:var(--ink); font-family:"DM Sans", "Segoe UI", sans-serif; }
    .topbar { min-height:58px; display:flex; align-items:center; justify-content:space-between; padding:0 4.5vw; border-bottom:1px solid var(--line); background:#fbfcf9; }
    .brand { display:flex; align-items:center; gap:12px; font-weight:700; font-size:13px; }
    .mark { width:22px; height:22px; border:2px solid var(--teal); border-radius:50%; position:relative; }
    .mark:after { content:""; position:absolute; left:4px; right:4px; top:8px; height:2px; background:var(--coral); transform:rotate(-36deg); }
    .env { color:var(--muted); font:11px "DM Mono", monospace; text-transform:uppercase; letter-spacing:0; }
    main { max-width:1440px; margin:0 auto; padding:34px 4.5vw 56px; }
    .heading { display:flex; align-items:end; justify-content:space-between; gap:24px; margin-bottom:24px; }
    .kicker { color:var(--teal); font:11px "DM Mono", monospace; text-transform:uppercase; }
    h1 { margin:8px 0 0; font:600 34px/1.08 Newsreader, Georgia, serif; letter-spacing:0; }
    .refresh { display:flex; align-items:center; gap:10px; color:var(--muted); font-size:12px; white-space:nowrap; }
    .pulse { width:8px; height:8px; background:#4e9a62; border-radius:50%; box-shadow:0 0 0 4px #4e9a6222; }
    .meta { color:var(--muted); font:11px "DM Mono", monospace; margin-top:9px; }
    .grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
    .panel { min-width:0; background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:18px 18px 14px; box-shadow:0 4px 14px #18312b08; animation:enter .4s ease both; }
    .panel:nth-child(2) { animation-delay:45ms } .panel:nth-child(3) { animation-delay:90ms } .panel:nth-child(4) { animation-delay:135ms } .panel:nth-child(5) { animation-delay:180ms } .panel:nth-child(6) { animation-delay:225ms }
    @keyframes enter { from { opacity:0; transform:translateY(7px) } to { opacity:1; transform:translateY(0) } }
    .panel-head { display:flex; justify-content:space-between; align-items:start; gap:12px; min-height:52px; }
    .panel-id { color:#8b9995; font:10px "DM Mono", monospace; }
    h2 { margin:4px 0 0; font-size:15px; font-weight:600; letter-spacing:0; }
    .value { text-align:right; font:500 19px "DM Mono", monospace; color:var(--ink); white-space:nowrap; }
    .unit { display:block; margin-top:4px; font:10px "DM Sans", sans-serif; color:var(--muted); }
    .chart-wrap { height:178px; margin-top:12px; }
    .panel-foot { display:flex; justify-content:space-between; gap:8px; padding-top:10px; border-top:1px solid #edf1ed; color:var(--muted); font-size:10px; }
    .legend { display:flex; flex-wrap:wrap; gap:10px; }
    .legend span:before { content:""; display:inline-block; width:7px; height:7px; margin-right:5px; border-radius:50%; background:var(--dot); }
    .threshold { font-family:"DM Mono", monospace; white-space:nowrap; }
    .error { margin:16px 0 0; color:#a33e32; font-size:12px; }
    @media(max-width:980px) { .grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
    @media(max-width:620px) { main { padding:24px 16px 40px; } .topbar { padding:0 16px; } .heading { align-items:start; flex-direction:column; gap:12px; } h1 { font-size:30px; } .grid { grid-template-columns:1fr; gap:10px; } .panel { padding:15px; } .chart-wrap { height:165px; } }
    @media(prefers-reduced-motion:reduce) { *, *:before, *:after { animation-duration:.01ms!important; animation-iteration-count:1!important; scroll-behavior:auto!important; } }
  </style>
</head>
<body>
  <div class="topbar"><div class="brand"><span class="mark" aria-hidden="true"></span><span>DAY 13 / LLMOPS</span></div><div class="env">Operational view · 60 min</div></div>
  <main>
    <div class="heading">
      <div><div class="kicker">Service telemetry / K4-L3B</div><h1>Monitoring overview</h1><div class="meta" id="window-label">Loading recent log window…</div></div>
      <div class="refresh"><span class="pulse" aria-hidden="true"></span><span id="refresh-label">Connecting</span></div>
    </div>
    <div class="grid">
      <section class="panel"><div class="panel-head"><div><div class="panel-id">01 / EXPERIENCE</div><h2>Latency & first token</h2></div><div class="value" id="latency-value">--<span class="unit">P95 · ms</span></div></div><div class="chart-wrap"><canvas id="latency-chart" aria-label="Latency percentiles and TTFT over time"></canvas></div><div class="panel-foot"><div class="legend"><span style="--dot:#187c73">P50</span><span style="--dot:#d1654d">P95</span><span style="--dot:#477fb1">P99</span><span style="--dot:#b37a22">TTFT</span></div><span class="threshold" id="latency-threshold"></span></div></section>
      <section class="panel"><div class="panel-head"><div><div class="panel-id">02 / VOLUME</div><h2>Request traffic</h2></div><div class="value" id="traffic-value">--<span class="unit">requests / hour</span></div></div><div class="chart-wrap"><canvas id="traffic-chart" aria-label="Requests per minute"></canvas></div><div class="panel-foot"><span>Counted from request_received</span><span>per minute</span></div></section>
      <section class="panel"><div class="panel-head"><div><div class="panel-id">03 / RELIABILITY</div><h2>Errors & retrieval</h2></div><div class="value" id="error-value">--<span class="unit">error rate</span></div></div><div class="chart-wrap"><canvas id="errors-chart" aria-label="Error and retrieval success rates"></canvas></div><div class="panel-foot"><div class="legend"><span style="--dot:#d1654d">Errors</span><span style="--dot:#187c73">Retrieval OK</span></div><span class="threshold" id="errors-threshold"></span></div></section>
      <section class="panel"><div class="panel-head"><div><div class="panel-id">04 / EFFICIENCY</div><h2>Estimated cost</h2></div><div class="value" id="cost-value">--<span class="unit">USD · 60 min</span></div></div><div class="chart-wrap"><canvas id="cost-chart" aria-label="Estimated cost per minute"></canvas></div><div class="panel-foot"><span>From response_sent.cost_usd</span><span class="threshold" id="cost-threshold"></span></div></section>
      <section class="panel"><div class="panel-head"><div><div class="panel-id">05 / CAPACITY</div><h2>Token volume</h2></div><div class="value" id="tokens-value">--<span class="unit">input + output</span></div></div><div class="chart-wrap"><canvas id="tokens-chart" aria-label="Input and output tokens per minute"></canvas></div><div class="panel-foot"><div class="legend"><span style="--dot:#477fb1">Input</span><span style="--dot:#b37a22">Output</span></div><span class="threshold" id="tokens-threshold"></span></div></section>
      <section class="panel"><div class="panel-head"><div><div class="panel-id">06 / QUALITY</div><h2>Answer quality proxy</h2></div><div class="value" id="quality-value">--<span class="unit">mean · 0–1</span></div></div><div class="chart-wrap"><canvas id="quality-chart" aria-label="Mean quality score over time"></canvas></div><div class="panel-foot"><span>Heuristic score from responses</span><span class="threshold" id="quality-threshold"></span></div></section>
    </div>
    <p class="error" id="error-message" role="status" hidden></p>
  </main>
<script>
const colors = {teal:'#187c73', coral:'#d1654d', blue:'#477fb1', gold:'#b37a22', green:'#4e8a58', grid:'#edf1ed', text:'#71807b'};
const charts = {};
function line(label, values, color, extra={}) { return {label, data:values, borderColor:color, backgroundColor:color+'22', borderWidth:2, pointRadius:0, pointHoverRadius:3, tension:.25, spanGaps:false, ...extra}; }
function chart(id, labels, datasets, suffix='') {
  const ctx=document.getElementById(id);
  if(charts[id]) { charts[id].data.labels=labels; charts[id].data.datasets=datasets; charts[id].update('none'); return; }
  charts[id]=new Chart(ctx,{type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${c.parsed.y == null ? '—' : c.parsed.y.toFixed(2)}${suffix}`}}},scales:{x:{grid:{display:false},ticks:{maxTicksLimit:6,maxRotation:0,color:colors.text,font:{size:9}}},y:{beginAtZero:true,grid:{color:colors.grid},ticks:{maxTicksLimit:5,color:colors.text,font:{size:9},callback:v=>`${v}${suffix}`}}}}});
}
const fmt=(value,digits=0)=>value==null?'—':Number(value).toLocaleString(undefined,{maximumFractionDigits:digits,minimumFractionDigits:digits});
async function refresh() {
  try {
    const response=await fetch('/dashboard/data',{cache:'no-store'});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const data=await response.json(), s=data.summary, t=data.thresholds, x=data.labels, d=data.series;
    document.getElementById('window-label').textContent=`Rolling ${data.window_minutes} minutes · refreshed ${new Date(data.generated_at).toLocaleTimeString()}`;
    document.getElementById('refresh-label').textContent='Live · refreshes every 30s';
    document.getElementById('latency-value').innerHTML=`${fmt(s.latency_p95_ms)}<span class="unit">P95 · ms</span>`;
    document.getElementById('traffic-value').innerHTML=`${fmt(s.request_count)}<span class="unit">requests / hour</span>`;
    document.getElementById('error-value').innerHTML=`${fmt(s.error_rate_pct,1)}%<span class="unit">error rate</span>`;
    document.getElementById('cost-value').innerHTML=`$${fmt(s.cost_usd,3)}<span class="unit">USD · 60 min</span>`;
    document.getElementById('tokens-value').innerHTML=`${fmt(s.tokens_in+s.tokens_out)}<span class="unit">input + output</span>`;
    document.getElementById('quality-value').innerHTML=`${fmt(s.quality_score,2)}<span class="unit">mean · 0–1</span>`;
    document.getElementById('latency-threshold').textContent=`P95 limit ${fmt(t.latency_p95_ms)} ms`;
    document.getElementById('errors-threshold').textContent=`error ≤ ${fmt(t.error_rate_pct)}%`;
    document.getElementById('cost-threshold').textContent=`window limit $${fmt(t.cost_usd,2)}`;
    document.getElementById('tokens-threshold').textContent=`window limit ${fmt(t.tokens)}`;
    document.getElementById('quality-threshold').textContent=`minimum ${fmt(t.quality_score,2)}`;
    const flat=(value)=>x.map(()=>value);
    chart('latency-chart',x,[line('P50',d.latency_p50,colors.teal),line('P95',d.latency_p95,colors.coral),line('P99',d.latency_p99,colors.blue),line('TTFT P95',d.ttft_p95,colors.gold),line('P95 limit',flat(t.latency_p95_ms),'#a4aaa4',{borderDash:[5,4],borderWidth:1})],' ms');
    chart('traffic-chart',x,[line('Requests / min',d.requests,colors.blue,{fill:true})],' req');
    chart('errors-chart',x,[line('Error rate',d.error_rate_pct,colors.coral),line('Retrieval success',d.retrieval_success_pct,colors.teal),line('Error limit',flat(t.error_rate_pct),'#a4aaa4',{borderDash:[5,4],borderWidth:1}),line('Retrieval target',flat(90),colors.gold,{borderDash:[5,4],borderWidth:1})],'%');
    chart('cost-chart',x,[line('USD / min',d.cost_usd,colors.gold,{fill:true})],' USD');
    chart('tokens-chart',x,[line('Input',d.tokens_in,colors.blue,{fill:true}),line('Output',d.tokens_out,colors.gold,{fill:true})],' tokens');
    chart('quality-chart',x,[line('Quality proxy',d.quality_score,colors.green),line('Minimum',flat(t.quality_score),'#a4aaa4',{borderDash:[5,4],borderWidth:1})]);
    document.getElementById('error-message').hidden=true;
  } catch(error) {
    document.getElementById('refresh-label').textContent='Data unavailable';
    const message=document.getElementById('error-message'); message.textContent=`Dashboard data could not be loaded: ${error.message}`; message.hidden=false;
  }
}
refresh(); setInterval(refresh,30000);
</script>
</body>
</html>"""
