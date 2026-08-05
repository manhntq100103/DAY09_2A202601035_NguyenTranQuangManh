# Báo cáo cá nhân — Day 09: Multi-Agent E-commerce Dispute Resolution

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Nguyễn Trần Quang Mạnh |
| MSSV | 2A202601035 |
| Khóa/Lớp | K3 |
| Hình thức thực hiện | Cá nhân — tự thực hiện toàn bộ dự án |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

Tôi là người duy nhất thực hiện dự án, chịu trách nhiệm toàn bộ luồng từ khảo sát dữ liệu đến sinh và kiểm chứng artifact nộp bài.

| Hạng mục | File/module phụ trách | Kết quả |
| --- | --- | --- |
| Chuẩn hóa và truy xuất dữ liệu Olist | `src/data_access.py`, `scripts/inspect_data.py` | Đọc 9 CSV, chuẩn hóa ID/timestamp/tiền và join theo `order_id` |
| Thiết kế multi-agent | `architecture.md`, `src/agents/graph.py`, `draw_graph.py` | Workflow LangGraph 6 agent và ảnh sơ đồ graph |
| Cấu hình Groq | `src/agents/llm.py`, `pyproject.toml` | Dùng `llama-3.1-8b-instant` (8B), đọc key từ `.env` |
| Facts, handoff và policy | `src/agents/contracts.py`, `src/agents/policy.py`, `src/agents/graph.py` | Handoff có audit; áp dụng EC_POLICY_V1 theo đúng ưu tiên |
| Sinh artifact chạy batch | `src/batch.py`, `main.py` | 50 JSON output, `trace.jsonl`, `metadata.json` |
| Kiểm chứng trước nộp | `src/validation.py`, `validate_submission.py` | Xác thực output, CSV evidence, money, policy, trace và metadata |

Không có thành viên hoặc module ngoài phạm vi trên cần hỗ trợ.

## 3. Kết quả thực hiện

| Nhiệm vụ | Artifact | Kết quả xác minh |
| --- | --- | --- |
| Nạp dữ liệu | `src/data_access.py` | Đọc thành công 9 CSV: 99,441 orders, 112,650 items, 103,886 payment rows |
| Điều phối agent | `src/agents/graph.py` | Mỗi case đi qua 6 handoff: Coordinator → Order & Seller → Payment → Delivery → Policy → Verifier |
| Phân loại case | `src/agents/policy.py` | 50 case: 8 canceled paid, 8 unavailable paid, 8 late seller, 8 late logistics, 9 split payment, 9 unsupported late claim |
| Sinh kết quả | `output/EC_001.json` … `output/EC_050.json` | Có đúng 50 JSON theo tên input |
| Audit runtime | `trace.jsonl` | 300 sự kiện handoff, tương ứng 6 × 50 case |
| Kiểm thử cuối | `validate_submission.py` | Validation pass cho schema, evidence, entity, financial resolution, policy, trace và metadata |

## 4. Giải thích kỹ thuật

### Vấn đề giải quyết

Mỗi khiếu nại chỉ nêu `claimed_order_id`, nên không thể kết luận dựa vào câu chữ của khách hàng. Pipeline phải nối order với item, seller và payment; so sánh mốc thời gian; sau đó áp dụng policy có thứ tự ưu tiên để tìm vấn đề, bên chịu trách nhiệm, bằng chứng và khoản hoàn tiền.

### Cách triển khai

`OlistDataStore` nạp CSV một lần, giữ ID dưới dạng chuỗi, tiền dưới dạng `Decimal` và timestamp theo đúng giá trị CSV, không đổi múi giờ. Hàm `order_context(order_id)` trả về toàn bộ item, payment, review, seller và product liên quan để không làm mất quan hệ một-nhiều.

LangGraph điều phối sáu node. Các agent domain không tạo sự kiện giả mà chỉ lập facts/evidence từ context dữ liệu:

- Order & Seller Agent xác định status, item, seller và seller handoff quá `shipping_limit_date`.
- Payment Agent cộng giá item, freight và payment; đối soát với sai số 0.10 BRL.
- Delivery Agent so sánh actual delivery với estimated delivery.
- Policy Agent áp dụng lần lượt canceled paid → unavailable paid → late seller → late logistics → split payment → unsupported claim.
- Verifier Agent kiểm tra handoff trước khi batch runner chuyển state thành JSON output.

Groq được cấu hình qua `.env`; model đã khai báo trong source là `llama-3.1-8b-instant` (8B), đáp ứng giới hạn không quá 10B parameters. Quyết định nghiệp vụ được tính tất định từ facts để bảo đảm tái lập và tránh hallucination của LLM.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | 50 `input/EC_*.json`, gồm `case_id`, `customer_request.claimed_order_id`, policy version |
| Handoff | Agent nguồn/đích, facts, financials, evidence IDs, warnings và trạng thái `completed`/`blocked` |
| Output | 50 JSON trong `output/`, tuân theo schema assessment, affected entities, root cause, evidence, financial resolution và actions |
| Trace | `trace.jsonl`, ghi 6 handoff/case, không chứa API key hoặc secret |
| Điều kiện lỗi | Thiếu order, thiếu facts cần thiết, không match policy, evidence sai format/không thuộc order, số tiền hoặc schema sai |

### Cách xác minh

```bash
uv run python scripts/inspect_data.py
uv run python main.py
uv run python validate_submission.py
```

Kết quả cuối: validator báo `Validation passed: 50 outputs, source-backed evidence, financials, trace and metadata are valid.`

## 5. Quyết định kỹ thuật quan trọng

- **Bối cảnh:** Có thể để LLM Groq tự diễn giải khiếu nại và chọn kết quả, nhưng dữ liệu Olist thiếu nhiều sự kiện (refund ledger, tracking theo item, giao thiếu/giao sai).
- **Phương án cân nhắc:** (1) LLM quyết định trực tiếp từ prompt và CSV; (2) LangGraph dùng LLM cho điều phối nhưng quyết định policy bằng rule/facts tất định.
- **Phương án chọn:** Phương án (2).
- **Lý do:** Chính sách EC_POLICY_V1 có điều kiện, thứ tự ưu tiên và phép tính tài chính xác định. Dùng `Decimal` và rule engine giúp kết quả có thể truy vết, lặp lại và không suy diễn dữ liệu không tồn tại.
- **Bằng chứng:** Chạy đủ 50 case không có warning; có 300 handoff và validator đối chiếu từng output với CSV/policy thành công.

## 6. Lỗi đã xử lý

- **Triệu chứng:** Payment Agent báo `SyntaxError: Generator expression must be parenthesized` khi chạy batch test ban đầu.
- **Nguyên nhân gốc:** Generator expression trong các phép `sum(..., Decimal("0"))` chưa được bọc ngoặc đúng cú pháp Python.
- **Cách xử lý:** Bọc generator expression cho `item_total`, `freight_total` và `payment_total` trong `src/agents/graph.py`.
- **Xác minh sau sửa:** Chạy lại toàn bộ 50 case; tất cả hoàn tất đủ 6 handoff và validator cuối pass.
- **Bài học:** Luôn chạy smoke test import/compile trước khi chạy batch đầy đủ, đặc biệt tại các điểm xử lý tiền tệ và dữ liệu số lượng lớn.

## 7. Hiểu biết về luồng end-to-end

1. Batch runner đọc và validate 50 input, sau đó dùng `claimed_order_id` để lấy `OrderContext` đã chuẩn hóa từ 9 CSV.
2. LangGraph tuần tự chuyển facts đã xác minh giữa các agent. Handoff là artifact audit, không phải lời giải thích tự do của LLM.
3. Policy Agent chọn chính xác một rule theo thứ tự ưu tiên. Các evidence ID chỉ có dạng được README cho phép và đều kiểm tra được trong dữ liệu/policy.
4. Batch runner dựng JSON output, ghi mới `trace.jsonl` và `metadata.json`.
5. Validator chạy độc lập, đối chiếu output với CSV, policy decision, financial total và trace. Chỉ khi validator pass thì artifact mới sẵn sàng nộp.

## 8. Cam kết

- [x] Báo cáo phản ánh đúng phần việc do cá nhân tôi trực tiếp thực hiện.
- [x] Tôi có thể giải thích luồng end-to-end của hệ thống.
- [x] Mọi kết quả nêu trong báo cáo đã được kiểm chứng bằng lệnh và artifact nêu trên.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này được viết cho dự án cá nhân, không sao chép báo cáo thành viên khác.

**Họ và tên:** Nguyễn Trần Quang Mạnh  
**Ngày xác nhận:** 2026-08-05
