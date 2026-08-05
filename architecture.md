# Kiến trúc multi-agent

## Mục tiêu

Hệ thống dùng LangGraph để điều phối sáu agent có phạm vi trách nhiệm tách biệt. Groq là LLM provider chung; cấu hình được nạp tại runtime từ `.env` qua `GROQ_API_KEY` và `GROQ_MODEL`. API key không được đưa vào source, trace hoặc output.

## Sơ đồ và luồng handoff

```text
START
  -> Coordinator
  -> Order & Seller Agent
  -> Payment Agent
  -> Delivery Agent
  -> Policy Agent
  -> Verifier Agent
  -> END
```

Coordinator là điểm vào duy nhất: nhận `case_id` và `claimed_order_id`, phân công và theo dõi handoff. Các agent domain chuyển tiếp facts đã kiểm chứng, không chuyển suy đoán hay tự tạo sự kiện. Policy Agent chỉ nhận facts đã hợp nhất để áp dụng `EC_POLICY_V1`; Verifier là điểm chặn cuối trước khi bất kỳ output nào được ghi.

## Vai trò và quyền truy cập

| Agent | Trách nhiệm | Dữ liệu/quyền truy cập | Đầu ra handoff |
| --- | --- | --- | --- |
| Coordinator | Khởi tạo case, điều phối và tổng hợp tiến trình | JSON case; trạng thái LangGraph | Lệnh phân tích và trạng thái case |
| Order & Seller | Kiểm tra order, customer, items, seller, shipping limit | orders, customers, order_items, sellers, products | Facts order/item/seller |
| Payment | Đối soát payment với item và freight | order_payments, item facts | Tổng payment và facts đối soát |
| Delivery | Đối chiếu carrier/customer delivery với estimated date | orders, item shipping limit | Facts giao hàng và thời hạn |
| Policy | Áp dụng EC_POLICY_V1 theo thứ tự ưu tiên | Facts từ ba agent domain; policy | Đề xuất issue, trách nhiệm, refund, action |
| Verifier | Kiểm tra schema, evidence, tiền và tính nhất quán | Proposed resolution và source facts | Kết quả xác thực hoặc lỗi |

## Hợp đồng an toàn

- ID, timestamp, số tiền và evidence phải đến từ dữ liệu đã chuẩn hóa; timestamp không đổi múi giờ, tiền dùng `Decimal`.
- Agent không được tự suy ra refund ledger, transaction ID, checkpoint giao hàng theo item, giao sai hoặc giao thiếu.
- Chỉ Verifier được phép cho phép ghi một kết quả đã kiểm chứng ở bước sinh output sau này.
- Trace sẽ ghi từng handoff ở bước chạy batch, không ghi secret.

## Hiện trạng triển khai

`src/agents/graph.py` đã khai báo và compile topology LangGraph cùng contract handoff. Coordinator, các agent domain và Policy Agent hiện đã truy xuất facts chuẩn hóa, tạo evidence có nguồn và áp dụng `EC_POLICY_V1` theo thứ tự ưu tiên. Việc xây JSON output/trace thuộc bước 4; validation đầy đủ schema và evidence-set thuộc bước 5.
