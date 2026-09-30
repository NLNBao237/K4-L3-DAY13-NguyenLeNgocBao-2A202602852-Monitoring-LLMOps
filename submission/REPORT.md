# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Nguyễn Lê Ngọc Bảo
- **MSSV:** 2A202602852
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/NLNBao237/K4-L3-DAY13-NguyenLeNgocBao-2A202602852-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602852`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.txt` |
| Log validator | `evidence/02-log-validator.txt` |
| Dashboard validator | `evidence/03-dashboard-validator.txt` |
| Structured log | `evidence/04-structured-log.txt` |
| PII redaction | `evidence/05-pii-redaction.txt` |
| Trace list | `evidence/06-trace-list.png`, `evidence/06-trace-list.txt` |
| Trace waterfall | `evidence/07-trace-waterfall.png`, `evidence/07-trace-waterfall.txt` |
| Trace metadata | `evidence/08-trace-metadata.png`, `evidence/08b-generation.png`, `evidence/08-trace-metadata.txt` |
| Prompt versions | `evidence/09-prompt-versions.png`, `evidence/09-prompt-versions.txt` |
| Prompt rollback | `evidence/10b-production-v2-trace.png` (trước: production=v2), `evidence/10-prompt-rollback.png` (sau: production=v1), `evidence/10-prompt-rollback.txt` |
| Dashboard runtime | `evidence/11-dashboard-overview.png`, `evidence/11-dashboard-data.json` |
| Incident metric | `evidence/12-incident-metric.png`, `evidence/12-incident-metric.txt`, `evidence/12-incident-metric-data.json` |
| Incident log | `evidence/13-incident-log.txt` |
| Incident trace | `evidence/14-incident-trace.txt`, `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

Baseline đo lại trên commit starter `61a34f8` (bản sao riêng, tắt Langfuse) bằng cùng `load_test.py`; kết quả cuối đo trên working tree cuối.

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 (0 correlation ID, 20/21 record thiếu field và context) | 100/100 (248 records, 116 correlation ID) | `evidence/02-log-validator.txt` |
| `validate_dashboard.py` | HỢP LỆ 6/6 (contract có sẵn) | HỢP LỆ 6/6 panel | `evidence/03-dashboard-validator.txt` |
| `pytest` | 22 passed | 27 passed | Thêm test PII, observability, dashboard, alert, trace child; `evidence/01-pytest.txt` |
| Số traces hợp lệ | Chỉ có root `lab-agent-run`, không có child | 18 traces (root + retrieval + generation) | `evidence/06-trace-list.txt`, run 04:35–04:36 UTC |
| Số PII leak | 0 theo validator (starter chỉ log rất ít field) | 0 trong log và 0 trong 54 observations | Quét email/điện thoại/thẻ trên input/output/metadata |
| Latency P95 / TTFT P95 | ~157 ms (client đo, không có dashboard) | 3281 ms / 50 ms (cửa sổ 60 phút) | P50 = 152 ms; P95 bị kéo lên bởi request cold-start đầu mỗi process |
| Retrieval success rate | Không đo được | 100% | Chưa bật incident; error rate 0%. Khi có challenge `rag_slow` vẫn 100% vì retrieval chậm chứ không lỗi |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` (`app/middleware.py`) chạy cho mọi request:
  1. Gọi `clear_contextvars()` để request mới không mang context của request trước.
  2. Nếu client gửi `x-request-id` thì dùng lại; nếu không thì sinh `req-<8-hex>` (`uuid4().hex[:8]`).
  3. `bind_contextvars(correlation_id=...)` và gán `request.state.correlation_id`.
  4. Trả lại `x-request-id` và `x-response-time-ms` trong response header; `finally` xóa context lần nữa.

  `/chat` truyền ID này vào `LabAgent.run()`, nên nó xuất hiện cả trong trace metadata và trong body `ChatResponse`.
- **Các metadata được ghi vào structured log:** trước dòng `request_received`, `app/main.py` bind `user_id_hash` (SHA-256 cắt 12 ký tự, không lưu user ID gốc), `session_id`, `feature`, `model`, `env`. Mọi log sau đó trong request tự mang các field này. Mỗi dòng JSON có thêm `ts` (ISO, UTC), `level`, `event`, `service`. `response_sent` có `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`. `request_failed` có `error_type`. Ví dụ ở `evidence/04-structured-log.txt`.
- **Cách bảo đảm PII được scrub trước khi ghi:** processor `scrub_event` (`app/logging_config.py`) đứng trước `JsonlFileProcessor` và `JSONRenderer` trong chuỗi processor của structlog. Nó đệ quy qua mọi string trong `dict`/`list`/`tuple`, nên cả `payload` lồng nhau cũng được scrub trước khi render hay ghi file. `app/pii.py` có pattern cho:
  - email;
  - số điện thoại Việt Nam `0`/`+84` + 9 chữ số, chấp nhận dấu cách, chấm, gạch;
  - CCCD 12 chữ số;
  - thẻ thanh toán 13–19 chữ số có hoặc không dấu cách/gạch.

  Ngoài ra, app chỉ log `summarize_text()` (đã scrub và cắt 80 ký tự), không log nội dung đầy đủ.
- **Cách kiểm chứng kết quả:**
  - `tests/test_pii.py` và `tests/test_chat_observability.py` kiểm tra redaction, correlation ID, header và việc không rò context giữa request.
  - Runtime: `validate_logs.py` đạt 100/100 với 0 PII leak.
  - `evidence/05-pii-redaction.txt` cho thấy email, số điện thoại và số thẻ mẫu trong `sample_queries.jsonl` đã thành `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CREDIT_CARD]`.
  - Trên Langfuse, quét 54 observations cũng không thấy PII.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** key trong `.env` (không commit) thuộc project `day13-k4-l3b-2A202602852`, đã xác nhận qua `GET /api/public/projects` bằng chính key đó. Tôi tự chạy workload qua API local. `evidence/06-trace-list.txt` liệt kê 18 traces của lần chạy 2026-09-30 04:35–04:36 UTC, lấy từ `GET /api/public/v2/observations` của project này. Mỗi trace có `correlation_id` khớp với `data/logs.jsonl`.
- **Cấu trúc root/retrieval/generation observations:** trace `day13-agent-request` có root `lab-agent-run` (`agent`, tạo bằng `@observe`) và hai child cùng parent:
  - `retrieval` (`retriever`): input/output chỉ gồm preview đã scrub và `doc_count`.
  - `fake-llm-generate` (`generation`): có `model`, `usage_details` input/output, `cost_details` input/output (giá $3/$15 cho mỗi 1M token) và `prompt=` là managed prompt để Langfuse link đúng prompt version.

  Xem `evidence/07-trace-waterfall.txt`: trace `ccd64d0b66c459dc62e805592ac07af5` có root `9c0c264b2a7ce78f`, hai child đều có `parent=9c0c264b2a7ce78f`. Generation có `usage={input: 45, output: 99}`, `cost.total=0.00162`, `promptName=day13-chat`, `promptVersion=1`.
- **Cách nối trace với log:** middleware sinh hoặc nhận `x-request-id` (`req-<8-hex>`) → `request.state.correlation_id` → `LabAgent.run(correlation_id=...)` → `propagate_attributes(metadata={"correlation_id": ...})`. Nhờ vậy mọi observation trong trace đều có metadata `correlation_id`. Cùng giá trị đó nằm trong mọi dòng log của request và trong response header. Ví dụ: log `response_sent` có `correlation_id=req-e098446c` ↔ trace `ccd64d0b66c459dc62e805592ac07af5`.
- **Không lưu PII trong trace:** chỉ gửi `summarize_text()` (scrub rồi cắt 80 ký tự), user ID được hash (`userId=1ec7627271d1`), root dùng `capture_input/capture_output=False`. Tôi quét regex email/điện thoại/thẻ trên input, output và metadata của 54 observations: 0 leak (dòng đầu `evidence/06-trace-list.txt`), dù workload có email, số điện thoại và số thẻ mẫu.
- **Prompt name:** `day13-chat`, dạng text prompt, giữ 3 biến `{{feature}}`, `{{docs}}`, `{{message}}` (`evidence/09-prompt-versions.txt`).
- **Version/label baseline:** version 1, labels `baseline` và `production`, template tối giản `Feature/Docs/Question`.
- **Version/label candidate:** version 2, label `candidate`, thêm một câu hướng dẫn "trả lời tối đa 3 bullet ngắn, chỉ dùng docs". Với cùng input, `tokens_in` tăng từ 45 lên 71.
- **Trace ID của mỗi version:** cùng input "Explain why metrics traces and logs work together for monitoring":

  | Bước | `LANGFUSE_PROMPT_LABEL` | `prompt_version` | tokens_in | correlation_id | trace_id |
  |---|---|---|---:|---|---|
  | Label baseline | `baseline` | 1 | 45 | `req-9553ca6d` | `023944831956ce88d0c4869926e624dd` |
  | Label candidate | `candidate` | 2 | 71 | `req-a1670765` | `48f117820c5f13b24820359e1f73bd03` |
  | Sau promote `production` → v2 | `production` | 2 | 71 | `req-3d518570` | `a27b0017519222a17908f4ef7ccbde2a` |
  | Sau rollback `production` → v1 | `production` | 1 | 45 | `req-e098446c` | `ccd64d0b66c459dc62e805592ac07af5` |

- **Cách promote và rollback `production`:** không sửa code, chỉ di chuyển label trên Langfuse.
  - Promote: `update_prompt(name="day13-chat", version=2, new_labels=["candidate", "production"])`.
  - Rollback: `update_prompt(name="day13-chat", version=1, new_labels=["baseline", "production"])`, tương đương kéo label trên UI Prompt Management.

  Sau mỗi bước tôi khởi động lại API để bỏ cache prompt 60 giây của SDK, rồi gửi lại đúng input trên. Trace metadata vẫn ghi `prompt_label=production` nhưng `prompt_version` đổi 2 → 1, chứng minh rollback có hiệu lực (`evidence/10-prompt-rollback.txt`).

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** dashboard runtime tại `GET /dashboard` (`app/dashboard.py`), lấy dữ liệu từ `GET /dashboard/data`. Endpoint này đọc trực tiếp `data/logs.jsonl` và lấy threshold từ `config/dashboard.yaml`. Cửa sổ 60 phút, bucket 1 phút, tự refresh 30 giây. Sáu panel đúng contract:
  1. Latency: P50/P95/P99 của `response_sent.latency_ms` và TTFT P95, đơn vị ms, đường P95 limit 3000 ms.
  2. Traffic: số `request_received` theo phút và tổng request trong cửa sổ.
  3. Errors: error rate (`request_failed`/`request_received`) và retrieval success (`tool_success` của `tool_name=retrieval`), có đường error ≤ 2% và retrieval target 90%.
  4. Cost: tổng `cost_usd` theo phút và toàn cửa sổ, window limit $2.50.
  5. Tokens: tổng `tokens_in`/`tokens_out` theo phút, window limit 50,000.
  6. Quality: mean `quality_score`, minimum 0.75.

  Ảnh: `evidence/11-dashboard-overview.png`. Số liệu cùng thời điểm: `evidence/11-dashboard-data.json`. Validator: `evidence/03-dashboard-validator.txt` (`HỢP LỆ: 6/6 panel`).
- **SLO và lý do chọn:** `config/slo.yaml` định nghĩa SLO `fast_successful_requests`: trong cửa sổ 28 ngày, 99.5% request phải vừa thành công (`response_sent`) vừa có `latency_ms <= 3000`. Tôi gộp lỗi và độ chậm vào một SLI vì với người dùng, câu trả lời đến sau hơn 3 giây cũng là trải nghiệm hỏng. Ngưỡng 3000 ms khớp threshold panel latency; khi warm, latency thực tế chỉ khoảng 150 ms nên còn nhiều dư địa cho LLM thật.
- **Cách tính error budget:** error budget = 100% − 99.5% = 0.5% số request. Với 10,000 request trong 28 ngày, tối đa 50 request được phép lỗi hoặc chậm hơn 3000 ms. Áp dụng cho cửa sổ dashboard lúc 04:43 UTC: 72 `request_received`, 72 `response_sent`, trong đó 68 request có latency ≤ 3000 ms, tức SLI = 94.4%. Budget 0.5% của 72 request chỉ là 0.36 request, nên 4 request chậm đã vượt budget của cửa sổ này. Cả 4 đều là request đầu tiên sau khi một process API vừa khởi động (1.2–6.6 s): lần fetch prompt đầu tiên từ Langfuse nằm trong đường xử lý request. Các request warm đều khoảng 150 ms. Hướng xử lý: prefetch prompt khi app khởi động (lifespan) và giữ fallback local.
- **Ba alert và runbook tương ứng:** định nghĩa trong `config/alert_rules.yaml` và `docs/alerts.md`. Cả ba đều symptom-based, duration 5m, gửi Slack `#k4-l3b-alerts`, owner `student-2A202602852`:
  - `HighLatencyP95` (warning): P95 `latency_ms` > 3000 ms → [runbook alert-1](../docs/alerts.md#alert-1).
  - `HighRequestErrorRate` (critical): `request_failed/request_received` > 2% → [runbook alert-2](../docs/alerts.md#alert-2).
  - `LowRetrievalSuccess` (warning): retrieval `tool_success` < 90% → [runbook alert-3](../docs/alerts.md#alert-3).

  Mỗi runbook đi theo Metrics → Logs → Traces: xác nhận trên panel, lọc log lấy `correlation_id`, mở trace cùng ID để so sánh span retrieval với generation, rồi mới chọn mitigation. Chỉ rollback prompt khi trace cho thấy generation/prompt là nguyên nhân.

> Ví dụ cách viết error budget: "SLO 99.5% trong 28 ngày nghĩa là error budget 0.5%. Nếu workload có 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn ngưỡng SLO."

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (cohort K4, seed 1312, `latency_threshold_ms=2000`). File `config/challenge.json` do Lab Coach gửi riêng, đã được `.gitignore` và không commit.
- **Cách chạy:** `python scripts/inject_incident.py` rồi `python scripts/load_test.py --challenge --concurrency 5`. Script giữ nguyên, chỉ trỏ `BASE_URL` sang server của tôi ở port 8011 vì port 8000 đang có một process cũ khác. Trước đó tôi gửi một request warm-up để cache prompt, tránh độ trễ cold-start làm nhiễu tín hiệu. Tôi cũng chạy một lượt challenge khi chưa bật incident để có baseline. Transcript đầy đủ ở `evidence/12-incident-metric.txt`.
- **Khoảng thời gian điều tra:** 2026-09-30 05:24–05:27 UTC (12:24–12:27 giờ VN). Incident nằm trong phút 05:25: `incident_enabled` lúc 05:25:09, `incident_disabled` lúc 05:26:56.
- **Triệu chứng từ metrics** (`evidence/12-incident-metric.png`, `evidence/12-incident-metric.txt`):

  | Phút (UTC) | Requests | P50 | P95 | TTFT P95 | Error | Retrieval OK | Tokens/cost |
  |---|---:|---:|---:|---:|---:|---:|---|
  | 05:24 baseline | 6 | 151 ms | 1423 ms* | 50 ms | 0% | 100% | bình thường |
  | **05:25 incident** | 10 | **2653 ms** | **2654 ms** | 50 ms | 0% | 100% | không đổi |
  | 05:26 sau fix | 5 | 152 ms | 152 ms | 50 ms | 0% | 100% | không đổi |

  \* Là request warm-up (feature `qa`); các challenge query ở phút 05:24 đều 151–152 ms.

  Latency tăng khoảng 17 lần và vượt ngưỡng challenge 2000 ms, chỉ ở feature `monitoring`. TTFT, token, cost, error rate và quality không đổi. Như vậy LLM không chậm hơn và request không lỗi, nên phần thời gian tăng thêm phải nằm ngoài generation.
- **Log line và correlation ID liên quan** (`evidence/13-incident-log.txt`): lọc `event == response_sent`, `feature == monitoring` trong khoảng 05:24–05:28. Cả 10 request trong phút 05:25 có `latency_ms` 2652–2654 nhưng `ttft_ms=50`. Request đại diện:

  ```json
  {"ts": "2026-09-30T05:25:14.697701Z", "event": "response_sent", "correlation_id": "req-6e2f18dd", "feature": "monitoring", "latency_ms": 2653, "ttft_ms": 50, "tokens_out": 117, "tool_name": "retrieval", "tool_success": true}
  ```

  Mốc so sánh là `req-24dc26e3` (cùng challenge, incident tắt): `latency_ms=152`.
- **Trace ID và span gây ảnh hưởng** (`evidence/14-incident-trace.txt`, `evidence/14-incident-trace.png`): trace `b90428ad34d4143815edfb3b3a919b42` có metadata `correlation_id=req-6e2f18dd`.
  - `lab-agent-run`: 2653 ms
  - └─ `retrieval`: **2501 ms (94.3%)**
  - └─ `fake-llm-generate`: 151 ms (5.7%), usage 36/117 token, prompt `day13-chat` v1

  Với trace baseline `b3f8306756e33cd0c9eff44a83d4f164`, `retrieval` mất 0 ms và generation 151 ms. Generation giống hệt nhau giữa hai trace; chỉ span retrieval tăng thêm khoảng 2.5 s.
- **Root cause:** bước retrieval (RAG / vector store) chậm thêm khoảng 2.5 s mỗi request. Cả ba lớp cùng chỉ về một chỗ:
  - Metrics: latency tăng nhưng TTFT, token và cost không đổi.
  - Logs: mọi request `monitoring` trong phút 05:25 đều khoảng 2653 ms, và bắt đầu ngay sau `incident_enabled rag_slow`.
  - Trace: 94% thời gian nằm trong span `retrieval`.

  Retrieval vẫn trả kết quả (`tool_success=true`, `doc_count=1`), nên đây là suy giảm latency chứ không phải lỗi. Vì vậy error rate và alert retrieval success không phát hiện được sự cố này; chỉ alert latency bắt được.
- **Hiệu ứng phụ phát hiện thêm:** phía client, request chờ tới 10.6–13.3 s trong khi server chỉ ghi 2.65 s mỗi request. Nguyên nhân: endpoint `async def chat` gọi `retrieve()` đồng bộ nên chặn event loop, 5 request đồng thời phải chạy tuần tự. Log thể hiện điều này qua các `response_sent` cách nhau đúng khoảng 2.65 s.
- **Fix action:** khôi phục retrieval bằng cách tắt incident (`python scripts/inject_incident.py --disable` → `rag_slow: false`). Chạy lại cùng challenge workload ngay sau đó, latency về 151–152 ms (phút 05:26). Không rollback prompt, vì trace cho thấy prompt và generation không đổi.
- **Preventive measure:**
  1. Alert: thêm alert theo span retrieval (P95 thời gian `retrieval` > 1000 ms trong 5 phút), để cảnh báo đúng thành phần trước khi P95 end-to-end vượt SLO 3000 ms. Challenge dùng ngưỡng 2000 ms, nên alert `HighLatencyP95` hiện tại ở 3000 ms sẽ không bắn cho sự cố này. Cân nhắc thêm một alert warning ở 2000 ms.
  2. Guardrail trong code: đặt timeout cho retrieval (ví dụ 1 s), quá hạn thì fallback về câu trả lời không có context và ghi `tool_success=false`, để sự cố hiện lên panel retrieval success thay vì chỉ làm chậm.
  3. Chuyển `retrieve()` / `generate()` sang chạy trong threadpool (`run_in_threadpool`) hoặc bản async, để một dependency chậm không chặn các request khác.
  4. Runbook: [alert-1](../docs/alerts.md#alert-1) đã có bước so sánh span retrieval với generation. Lần điều tra này xác nhận thêm dấu hiệu nhận biết nhanh: latency tăng mà TTFT/token không đổi thì kiểm tra retrieval trước.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** tách `LabAgent.run` thành root observation cùng hai child (`retrieval` loại `retriever`, `fake-llm-generate` loại `generation`), và truyền `correlation_id` qua `propagate_attributes` thay vì chỉ ghi vào root. Nhờ vậy ở CP3, trace cho thấy ngay 94% thời gian nằm trong `retrieval`. Nếu chỉ có một observation thì chỉ biết request chậm mà không biết bước nào chậm. Generation nhận `prompt=` là managed prompt, nên Langfuse tự link trace với prompt version, không phải ghi version giả bằng tay.
- **Một lỗi/blocker đã gặp:** lần đầu chạy thử promote/rollback, mọi trace đều ghi `prompt_label=production`, dù tôi đã đặt `LANGFUSE_PROMPT_LABEL=baseline`/`candidate`. Sau khi promote lên v2, trace vẫn ra v1.
- **Cách tìm nguyên nhân và xử lý:** thay vì sửa code, tôi kiểm tra từng giả thuyết:
  1. `python-dotenv` không override biến môi trường: đúng, nên không phải do `.env`.
  2. `netstat` cho thấy port 8001 đã có sẵn một uvicorn khác chạy label `production`. Request của tôi đi vào server đó, còn server mới không bind được port.

  Cách xử lý: chuyển sang port trống, kiểm tra port trước khi khởi động, và restart server sau mỗi lần đổi label vì SDK cache prompt 60 giây. Sau đó `tokens_in` (45 với v1, 71 với v2) xác nhận đúng version được dùng. Tôi cũng phát hiện request đầu tiên của mỗi process chậm 1–6.6 s do fetch prompt lần đầu, kéo P95 dashboard lên 3281 ms. Tôi ghi nhận điều này ở mục 6 thay vì xóa dữ liệu.
- **Cách hiểu luồng Metrics → Logs → Traces:**
  - Metrics trả lời "có vấn đề không, từ khi nào, loại gì". Ở CP3, P95 phút 05:25 tăng từ 152 lên 2654 ms, trong khi TTFT/token/error không đổi, nên loại trừ được LLM và lỗi.
  - Logs thu hẹp xuống request cụ thể: lọc `response_sent` trong phút đó, lấy `req-6e2f18dd`, thấy `latency_ms=2653` nhưng `ttft_ms=50`.
  - Trace có cùng `correlation_id` chỉ ra bước gây ra: `retrieval` 2501 ms.

  Chỉ khi cả ba lớp cùng chỉ về một chỗ mới kết luận root cause. Đi theo thứ tự này tránh mở trace ngẫu nhiên hoặc đoán theo cảm tính.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
  - Prompt là một phần của hệ thống. v2 chỉ thêm một câu nhưng làm `tokens_in` tăng 58% (45 → 71), tức cost input tăng tương ứng.
  - Nhờ label, việc promote/rollback không cần deploy code: chỉ di chuyển `production`. Mỗi trace ghi version nên có thể quy regression về đúng version.
  - SLO và error budget biến "hệ thống có ổn không" thành con số: 99.5% trong 28 ngày nghĩa là 50/10,000 request được phép hỏng. Khi budget bị đốt (như cửa sổ lab: 68/72 đạt), đó là tín hiệu ưu tiên sửa độ tin cậy trước khi ra tính năng mới.
- **Điều quan trọng nhất đã học:** một sự cố "không có lỗi" vẫn có thể là sự cố. `rag_slow` giữ error rate 0% và retrieval success 100%, nên chỉ alert theo triệu chứng latency và trace theo từng bước mới phát hiện được. Vì vậy observability cần đo đúng trải nghiệm người dùng, không chỉ đếm exception.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**
  - Evidence tests/validators/log là file `.txt` (được phép theo `submission/evidence/README.md`) thay vì ảnh chụp terminal.
  - Dashboard là trang tự dựng bằng FastAPI + Chart.js, không phải Grafana.
  - Alert mới là contract YAML, chưa nối Slack thật.
  - Preventive measures ở mục 7 (timeout retrieval, chạy retrieval trong threadpool, prefetch prompt lúc startup, alert theo span retrieval) mới là đề xuất, chưa implement.
  - CP3 chạy trên port 8011 thay vì 8000 vì port 8000 có process cũ không thuộc phiên làm việc này; script chính thức được giữ nguyên, chỉ đổi `BASE_URL`.

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
