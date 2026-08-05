# Tổng hợp dự án: Multi-Agent E-commerce Dispute Resolution

## 1. Tóm tắt bài toán

Xây dựng một hệ thống **multi-agent** để điều tra và xử lý 50 yêu cầu hỗ trợ khách hàng (`EC_001` đến `EC_050`) dựa trên bộ dữ liệu Brazilian E-Commerce Public Dataset by Olist. Mỗi case cung cấp `claimed_order_id`; hệ thống phải truy vấn, join các CSV liên quan và đưa ra kết luận có thể kiểm chứng thay vì chỉ tin vào nội dung khiếu nại.

Với mỗi đơn hàng, hệ thống cần xác định:

- Vấn đề chính (`primary_issue`) và mức tin cậy.
- Các order, item, seller và payment bị ảnh hưởng.
- Nguyên nhân gốc, bên chịu trách nhiệm và bằng chứng hợp lệ.
- Tổng tiền item, phí vận chuyển, tổng thanh toán và số tiền hoàn đề xuất (BRL, làm tròn 2 chữ số thập phân).
- Hành động xử lý phù hợp.

Các domain dữ liệu cần đối chiếu gồm trạng thái đơn, item/seller, mốc seller bàn giao cho carrier, thời điểm giao thực tế, hạn giao dự kiến, payment, review và (khi cần) khách hàng/sản phẩm/vị trí. Join chính:

- `orders.customer_id -> customers.customer_id`
- `orders.order_id -> order_items/order_payments/order_reviews.order_id`
- `order_items.product_id -> products.product_id`
- `order_items.seller_id -> sellers.seller_id`
- Các cột zip code có thể nối với geolocation sau khi gộp theo zip code.

Không được suy diễn các dữ kiện Olist không cung cấp như refund ledger, transaction ID, tracking checkpoint theo item, giao sai hoặc giao thiếu. `customer_id` đại diện cho một order; dùng `customer_unique_id` nếu cần nhận diện khách hàng qua nhiều order. Một order có thể có nhiều item, seller và payment; `payment_value` là giá trị từng dòng thanh toán.

### Quy tắc nghiệp vụ EC_POLICY_V1 (theo thứ tự ưu tiên)

| Primary issue | Điều kiện | Trách nhiệm | Hoàn tiền | Hành động | Root cause |
| --- | --- | --- | ---: | --- | --- |
| `canceled_order_paid` | `order_status = canceled` và tổng payment > 0 | `platform` / `OLIST_PLATFORM` | Tổng payment | `issue_full_refund` | `ORDER_CANCELED_AFTER_PAYMENT` |
| `unavailable_order_paid` | `order_status = unavailable` và tổng payment > 0 | `platform` / `OLIST_PLATFORM` | Tổng payment | `issue_full_refund` | `ORDER_UNAVAILABLE_AFTER_PAYMENT` |
| `late_delivery_seller` | Giao sau estimated date, carrier nhận hàng sau `shipping_limit_date` | Seller vi phạm | Tổng freight | `refund_freight` | `SELLER_HANDOFF_AFTER_LIMIT` |
| `late_delivery_logistics` | Giao sau estimated date, carrier nhận hàng không muộn hơn `shipping_limit_date` | `logistics_provider` / `LOGISTICS_PROVIDER` | Tổng freight | `refund_freight` | `CARRIER_DELIVERED_AFTER_ESTIMATE` |
| `valid_split_payment` | Có từ 2 payment row, tổng payment khớp item + freight trong sai số 0.10 BRL | Không có | 0 | `explain_valid_split_payment` | `MULTIPLE_PAYMENTS_RECONCILED` |
| `unsupported_late_claim` | Đơn giao không muộn hơn estimated date và payment khớp | Không có | 0 | `reject_late_refund` | `DELIVERY_WITHIN_ESTIMATE` |

Với nhiều item, seller được xem là bàn giao muộn nếu `order_delivered_carrier_date > shipping_limit_date` của item thuộc seller đó. Bộ 50 case chính thức không có tình huống mơ hồ giữa nhiều seller.

Đầu ra cho từng input là một JSON cùng tên trong `output/`, tuân thủ schema README: giới hạn tối đa 5 ID mỗi entity set, 10 evidence, 3 root causes, 3 responsible parties, 5 actions; `confidence` thuộc `[0,1]`. `case_status` là `action_required` khi có hoàn tiền, ngược lại là `no_action`. Nếu không có item, để trống `item_ids`, `seller_ids` và đặt hai tổng item/freight là `0.0`.

Evidence chỉ được dùng đúng các dạng và phải dựng trực tiếp từ CSV/policy:

```text
order:<order_id>
item:<order_id>:<order_item_id>
payment:<order_id>:<payment_sequential>
seller:<seller_id>
policy:<root_cause_code>
```

## 2. Plan thực hiện toàn bộ dự án

1. **Khảo sát và chuẩn hóa dữ liệu**
   - Kiểm tra đủ 9 CSV trong `data/` và 50 JSON trong `input/`.
   - Đọc schema, parse timestamp theo nguyên bản CSV (không đổi múi giờ), chuẩn hóa kiểu số và ID.
   - Tạo lớp/truy vấn dữ liệu theo `order_id`; bảo đảm xử lý đúng quan hệ one-to-many của item và payment.

2. **Thiết kế kiến trúc multi-agent và tài liệu hóa**
   - Xây dựng `Coordinator Agent` nhận case, phân công, tổng hợp và quyết định cuối.
   - Xây dựng `Order & Seller Agent` kiểm tra trạng thái đơn, item, seller, shipping limit và carrier handoff.
   - Xây dựng `Payment Agent` tính tổng payment, item và freight; kiểm tra split payment với ngưỡng 0.10 BRL.
   - Xây dựng `Delivery Agent` đối chiếu delivered date với estimated date và gửi phát hiện giao trễ.
   - Xây dựng `Policy Agent` áp dụng quy tắc EC_POLICY_V1 đúng thứ tự ưu tiên để ra issue, nguyên nhân, trách nhiệm, refund và action.
   - Xây dựng `Verifier Agent` xác thực schema, ID evidence, giới hạn số phần tử, tổng tiền, làm tròn và tính nhất quán trước khi ghi file.
   - Viết `architecture.md` tại root, thể hiện vai trò, quyền truy cập dữ liệu và luồng handoff thực tế giữa các agent.

3. **Xây dựng hợp đồng handoff và logic xác định case**
   - Chuẩn hóa payload trao đổi giữa agent: `case_id`, `order_id`, facts đã kiểm chứng, số liệu, evidence ID và cảnh báo thiếu dữ liệu.
   - Coordinator lấy `claimed_order_id`, yêu cầu các agent phân tích độc lập theo domain, sau đó gửi facts hợp nhất sang Policy Agent.
   - Policy Agent áp dụng thứ tự: canceled paid → unavailable paid → late seller → late logistics → valid split payment → unsupported late claim.
   - Chỉ tạo fact/evidence có nguồn dữ liệu hoặc policy rõ ràng; không bịa sự kiện thiếu trong Olist.

4. **Sinh kết quả cho 50 case**
   - Chạy luồng multi-agent cho từng file `input/EC_*.json`.
   - Sinh chính xác một file JSON tương ứng trong `output/`; tên output phải khớp input.
   - Ghi `trace.jsonl` của lần chạy mới nhất cho toàn bộ 50 case (ghi mới, không append), gồm các handoff và quyết định có thể audit.
   - Tạo `metadata.json` ghi model, parameter size, framework và runtime; tên model cũng phải được khai báo rõ trong source code.

5. **Kiểm thử và kiểm chứng trước khi nộp**
   - Kiểm tra có đúng 50 JSON từ `EC_001.json` đến `EC_050.json`, JSON hợp lệ và đúng schema.
   - Kiểm tra evidence tồn tại/đúng format, các entity ID thuộc order tương ứng, số tiền đúng và đã làm tròn 2 chữ số.
   - Kiểm tra tính nhất quán: refund > 0 thì `action_required`; split/unsupported claim có refund 0 và `no_action`.
   - Đánh giá theo rubric: primary issue/confidence 20%, entities 20%, root cause/responsibility 15%, evidence 15%, financial resolution 20%, actions 10%. Case vi phạm hard gate sẽ nhận 0 điểm nên validation cần chặn lỗi trước khi xuất.

6. **Hoàn thiện hồ sơ nộp bài**
   - Thêm báo cáo cá nhân `individual_5SoCuoiMHV_HoVaTen.md` tại root repo.
   - Đặt API key/secret trong `.env`, không commit; chỉ dùng model có không quá 10B parameters cho mỗi agent.
   - Commit toàn bộ source code và artifact cần thiết lên repo trước khi nộp.
   - Chỉ nén folder `output/` thành zip để nộp; zip chỉ chứa 50 JSON, không chứa source, `.env`, trace hay các file audit.
