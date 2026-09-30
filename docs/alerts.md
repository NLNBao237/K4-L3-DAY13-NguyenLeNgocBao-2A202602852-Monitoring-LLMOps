# Alerts và Runbook

Alert được gửi tới Slack `#k4-l3b-alerts`; owner là `student-2A202602852`. Các điều kiện trong `config/alert_rules.yaml` là contract để chuyển sang hệ thống alert thực tế.

<a id="alert-1"></a>

## Alert 1: HighLatencyP95

- Severity: warning; duration: 5m; kênh: Slack `#k4-l3b-alerts`; owner: `student-2A202602852`.
- SLI/SLO liên quan: SLO `fast_successful_requests` (latency ≤ 3000 ms) và panel latency.
- Điều kiện: P95 của `response_sent.latency_ms` lớn hơn 3000 ms liên tục 5 phút.
- Ảnh hưởng: người dùng chờ lâu hơn trước khi nhận câu trả lời; SLO latency có nguy cơ bị vi phạm.
- Kiểm tra:
  1. Xem panel latency, xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` theo thời gian, lấy `correlation_id` của request chậm.
  3. Mở trace cùng ID trên Langfuse và so sánh thời gian retrieval với generation.
- Mitigation: rollback prompt nếu generation là nguyên nhân; nếu retrieval chậm/lỗi, tắt practice incident hoặc khôi phục dịch vụ retrieval.

<a id="alert-2"></a>

## Alert 2: HighRequestErrorRate

- Severity: critical; duration: 5m; kênh: Slack `#k4-l3b-alerts`; owner: `student-2A202602852`.
- SLI/SLO liên quan: SLO `fast_successful_requests` (request thành công) và guardrail `error_rate_pct_max: 2`.
- Điều kiện: tỷ lệ `request_failed` trên `request_received` lớn hơn 2% liên tục 5 phút.
- Ảnh hưởng: một phần request không trả được câu trả lời.
- Kiểm tra:
  1. Xem panel errors và breakdown theo `error_type`.
  2. Lấy `correlation_id` từ log `request_failed` đầu tiên trong cửa sổ cảnh báo.
  3. Mở trace tương ứng, kiểm tra trạng thái và span cuối cùng hoàn tất.
- Mitigation: tắt practice incident gây lỗi, khôi phục dependency/configuration gần nhất đã đổi và xác nhận error rate giảm.

<a id="alert-3"></a>

## Alert 3: LowRetrievalSuccess

- Severity: warning; duration: 5m; kênh: Slack `#k4-l3b-alerts`; owner: `student-2A202602852`.
- SLI/SLO liên quan: guardrail `retrieval_success_rate_pct_min: 90` và panel errors/retrieval success.
- Điều kiện: tỷ lệ `tool_success == true` trên các retrieval tool observations giảm dưới 90% liên tục 5 phút.
- Ảnh hưởng: câu trả lời có thể thiếu context hoặc request có thể thất bại.
- Kiểm tra:
  1. Xem panel errors/retrieval success và xác nhận mẫu số chỉ gồm retrieval attempts.
  2. Lọc log `request_failed` có `tool_name=retrieval` để lấy `correlation_id`.
  3. Mở trace tương ứng, kiểm tra retrieval observation và lỗi dependency.
- Mitigation: khôi phục retrieval service/configuration hoặc tắt practice incident; không rollback prompt trừ khi trace cho thấy prompt là nguyên nhân.
