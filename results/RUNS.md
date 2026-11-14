# Nhật ký các lần chạy

Mọi lần chạy đều được giữ lại, gồm cả lần lỗi. Mỗi thư mục có tên `<lệnh>_<run_id UTC>`. Thư mục nào có `run_metadata.json` thì file đó ghi cấu hình, phiên bản và thời gian chạy. `console.log` là toàn bộ output trên console; không có file này nghĩa là output chỉ được xem trực tiếp, không lưu lại.

| Thư mục | Lệnh | Trạng thái | Ghi chú |
|---|---|---|---|
| `inspect_20261114T051049Z` | inspect | OK | Chunker B **trước khi sửa**: 152 chunk (ngắn nhất 7 ký tự, tức có chunk chỉ chứa heading); evidence nằm trọn trong một chunk B ở 18/20 câu, gồm cả lỗi ngắt đoạn sai ở q06 (dev, PDF 44). Console và `evidence_diagnostics.jsonl` có trạng thái chứa evidence của cả câu **test** (xem báo cáo, mục hạn chế). |
| `inspect_20261114T051519Z` | inspect | OK | Sửa giữa chừng: tạo đoạn theo hai lượt (sửa q06); 133 chunk, evidence trọn trong một chunk B ở 20/20 câu, nhưng vẫn còn chunk chỉ chứa heading (ngắn nhất 70 ký tự). |
| `inspect_20261114T051600Z` | inspect | OK | Chunker B **chốt**: 130 chunk (ngắn nhất 167 ký tự), heading luôn đi cùng đoạn sau nó. Đánh đổi: evidence của q05 (dev) bị tách qua hai chunk (19/20). |
| `ingest_20261114T053443Z` | ingest | **LỖI** | `ValueError: Could not load any image processor class for google/embeddinggemma-2 … Missing optional dependencies: torchvision, Pillow` (xem `console.log`). Đã cài torchvision và pillow, thêm vào `requirements.txt`. Chưa ghi dòng nào vào DB. |
| `ingest_20261114T053809Z` | ingest | **DỪNG TAY** | Model được nạp ở `torch.bfloat16` dù cấu hình `EMBEDDING_DTYPE=float32` (cảnh báo trong `console.log`). Đã dừng trước khi ghi DB (bảng rỗng). Sửa: truyền `model_kwargs={"dtype": ...}` và kiểm tra dtype thực tế lúc chạy. |
| `ingest_20261114T054628Z` | ingest | OK | Lần nạp chính: A 189, B 130 vector, float32, 768 chiều; tổng 3407 s (embed B 3289 s, chậm bất thường, chưa rõ nguyên nhân). |
| `ingest_20261114T064359Z` | ingest | OK | Nạp lại để kiểm tra idempotent: embedded 0, reused 189/130, upserted 0, deleted 0, số dòng không đổi. |
| `retrieve_dev_20261114T064853Z` | retrieve --split dev | OK | A/B/C trên 15 câu dev. Chọn C theo tiêu chí đã chốt trước. |
| `retrieve_test_20261114T065016Z` | retrieve --split test --selected-strategy C | OK | Chạy test **một lần** (`earlier_test_runs: []`) sau khi đã chọn C; vẫn đo cả A/B/C (GUIDE yêu cầu đọc 5 câu test cho từng cấu hình). |
| `inspect_20261114T072153Z` | inspect | OK | Chạy sau audit, khi code đã thôi tính trạng thái chứa evidence cho câu test (`not_checked_test_split`). Segment, chunk A/B và mẫu coherence **giống hệt** `ingest_20261114T054628Z` (so khớp từng byte). |
| `labels/` | (chấm tay) | OK | Nhãn coherence, metadata, grounding: Claude chấm nháp, tác giả đọc lại và duyệt 90/90 dòng. `labels_summary.json` do `starter/scripts/summarize_labels.py` tạo ra; `metadata_check.json` do `starter/scripts/verify_metadata.py` tạo ra. |
