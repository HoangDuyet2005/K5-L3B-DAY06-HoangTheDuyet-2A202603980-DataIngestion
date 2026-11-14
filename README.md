# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

> **Bài làm (HoangTheDuyet · 2A202603980):** cách setup và chạy ở mục [Bài làm: setup và chạy](#bài-làm-setup-và-chạy) cuối file. Báo cáo: [report/individual/2A202603980_HoangTheDuyet.md](report/individual/2A202603980_HoangTheDuyet.md).

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.

---

## Bài làm: setup và chạy

Corpus: **World Bank, *Poverty, Prosperity, and Planet Report 2024*** (CC BY 3.0 IGO), phần Overview PDF 35–73, tính 36 trang nội dung. Nguồn, giấy phép, sha256 và quy tắc tính trang nằm trong [data/manifest.json](data/manifest.json). PDF **không** nằm trong repo; tải bản gốc theo `source_path_or_url` trong manifest và kiểm tra sha256 `0f22fde0c8121a3d089db740e92a7bf7d36d9ae18d2d01014fad13288faaf746` (300 trang). Pipeline tự dừng nếu sha256 hoặc số trang không khớp.

| Thành phần | Giá trị |
|---|---|
| Embedding | `google/embeddinggemma-2` chạy local bằng Sentence Transformers; 768 chiều (kiểm tra lúc chạy); float32 trên CPU; prompt `SearchQuery` cho câu hỏi, `Document` cho văn bản; vector chuẩn hóa độ dài 1. Các lần chạy dùng snapshot Hugging Face `f9972ac22e696a105c482202646979e33e4b5a1e`. |
| Vector store | PostgreSQL 16.16 + pgvector 0.8.7 (Docker trong `starter/`), bảng `day6_chunks`, `vector(768)`, khoảng cách cosine `<=>`, tìm kiếm **exact** (không có ANN index). |
| Chiến lược | A: cửa sổ cố định 500 ký tự, overlap 50. B: theo đoạn/heading, tối đa 800 ký tự. C: chunk và vector của B, cộng lọc `section` **chỉ** với câu có filter. Cấu hình nằm ở `starter/src/config.py`. |
| Chi phí | 0 USD (model local, DB local). |

### Setup (Windows PowerShell; macOS/Linux đổi đường dẫn venv)

```bash
cd starter
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt   # bản đầy đủ: requirements-lock.txt
Copy-Item .env.example .env
docker compose -p day6_student_starter up -d --wait
.venv\Scripts\python.exe scripts/check_setup.py               # kỳ vọng: Setup OK
```

Thêm vào `starter/.env` (không commit file này):

```
CORPUS_PDF=<đường dẫn tới PDF đã tải>
EMBEDDING_DTYPE=float32
# Tùy chọn: EMBEDDING_REVISION=f9972ac22e696a105c482202646979e33e4b5a1e  (khóa đúng snapshot; vì revision nằm trong content hash, đặt biến này sẽ làm lần ingest kế tiếp embed lại toàn bộ)
```

`EMBEDDING_MODEL` để trống hoặc ghi đúng `google/embeddinggemma-2`; giá trị khác sẽ bị từ chối. Lần chạy đầu tải model từ Hugging Face (khoảng 740 triệu tham số).

### Chạy (từ thư mục `starter/`)

```bash
.venv\Scripts\python.exe -m src.run inspect                  # PDF -> segment -> chunk A/B + chẩn đoán; không cần model/DB
.venv\Scripts\python.exe -m src.run ingest                   # embed chunk đổi + upsert pgvector; chạy lại phải ra embedded=0
.venv\Scripts\python.exe -m src.run retrieve --split dev     # A/B/C trên 15 câu dev, dùng để chọn chiến lược
.venv\Scripts\python.exe -m src.run retrieve --split test --selected-strategy C --criteria "1) highest dev Evidence Hit@3; 2) tie -> higher dev Hit@1; 3) tie -> simpler config (fewer chunks, no filter)"
```

Lệnh `retrieve --split test` từ chối chạy nếu thiếu `--selected-strategy` / `--criteria` hoặc chưa có lần chạy dev cùng cấu hình; mọi lần chạy test trước đó được ghi vào `run_metadata.json` kèm cảnh báo. `python -m src.run` không kèm lệnh con (như ghi trong `starter/README.md`) sẽ báo lỗi và in danh sách lệnh con ở trên.

Kiểm tra nhãn audit (từ gốc repo):

```bash
starter/.venv/Scripts/python.exe -I starter/scripts/verify_metadata.py "<CORPUS_PDF>" data/manifest.json results/retrieve_test_20261114T065016Z/traces.jsonl results/labels/metadata_check.json
starter/.venv/Scripts/python.exe -I starter/scripts/summarize_labels.py results/labels
```

### Kết quả nằm ở đâu

| Đường dẫn | Nội dung |
|---|---|
| [results/RUNS.md](results/RUNS.md) | Danh sách mọi lần chạy, gồm 2 lần ingest lỗi/dừng kèm `console.log` |
| `results/ingest_20261114T054628Z/` | Metadata lần nạp chính (model, phiên bản, thời gian, token, số chunk), segment, chunk, mẫu chấm coherence |
| `results/ingest_20261114T064359Z/` | Bằng chứng nạp lại không trùng (embedded 0, deleted 0) |
| `results/retrieve_dev_20261114T064853Z/`, `results/retrieve_test_20261114T065016Z/` | Trace top-3 (`traces.jsonl`), `metrics.md`/`metrics.json` (Hit@1, Evidence Hit@3 dạng n/N) |
| `results/labels/` | Nhãn coherence / metadata / grounding đã duyệt và tổng hợp |
| [artifacts/experiment_log.csv](artifacts/experiment_log.csv) | Cấu hình, giả thuyết, tiêu chí chọn và kết quả A/B/C |
| [benchmark/questions.json](benchmark/questions.json) | 20 câu (15 dev / 5 test, 4 câu có filter) kèm evidence và trang gold |
