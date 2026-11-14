# Báo cáo cá nhân — Day 6

Học viên: Hoang The Duyet · MSSV 2A202603980 · Lớp L3B. Mọi số liệu lấy từ các lần chạy thật ngày 2026-11-14 (giờ UTC trong tên thư mục). Danh sách các lần chạy, kể cả lần lỗi, ở [results/RUNS.md](../../results/RUNS.md); lệnh setup và chạy ở [README](../../README.md#bài-làm-setup-và-chạy).

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - **Chủ đề:** nghèo đói, thịnh vượng chung và biến đổi khí hậu (báo cáo chính sách của Ngân hàng Thế giới).
  - **Nguồn:** World Bank (2024), *Poverty, Prosperity, and Planet Report 2024: Pathways Out of the Polycrisis*, doi:10.1596/978-1-4648-2123-3. URL tải nằm trong [data/manifest.json](../../data/manifest.json) (`source_path_or_url`). File PDF có 300 trang, sha256 `0f22fde0…faaf746`.
  - **Quyền:** CC BY 3.0 IGO, ghi công theo trường `attribution`. Theo `rights_notes`, hình, bảng và bản đồ có thể thuộc bên thứ ba, nên corpus không đưa chúng vào. PDF không commit vào repo; người chấm tải theo URL và pipeline kiểm tra lại sha256 cùng số trang.
  - **Số trang:** phạm vi là phần Overview, PDF 35–73 (trang in 1–39, lệch 34). Tính **36 trang nội dung** có đoạn văn thân bài.
  - **Quy tắc tính trang:**
    - Không tính PDF 37, 48 và 50, vì chữ trích được ở các trang này chỉ là nhãn hình/bản đồ, Source và Note.
    - Loại PDF 1–34 (bìa, mục lục, lời nói đầu…) và phần sau trang 73, theo trường `selection.excluded`.
    - Manifest ghi số ký tự của từng trang (tổng 104.127) và số trang in của từng trang.
  - **Section:** chia thành `progress` (PDF 35–53), `pathways` (53–64) và `priorities` (64–73). PDF 53 và 64 chứa hai section, nên ranh giới đặt theo vị trí ký tự của heading.
- **Chuẩn hóa, lỗi và giới hạn:**
  - **Đọc và chuẩn hóa:**
    - Đọc bằng pypdf 6.21.4. Unicode NFC khi đọc, rồi NFKC, bỏ ký tự vô hình, đổi NBSP thành dấu cách.
    - Bỏ 71 dòng header chạy đầu trang và số trang; sửa 7 lỗi tách chữ "Y et" thành "Yet"; nối từ gạch nối cuối dòng; bỏ 199 dòng chỉ có số (trục biểu đồ).
    - Tạo đoạn văn theo hai lượt, dựa vào độ dài dòng và dấu kết câu.
  - **Bỏ hình/bản đồ:** bỏ 17 khối, tổng 16.770 ký tự, tính từ nhãn FIGURE/MAP tới hết dòng Source/Note. Danh sách nằm trong `figure_blocks_removed.jsonl`. Ba khối không có dòng Source/Note (PDF 42, 43, 70) đều là hình "(continued)" ở cuối trang. Đoạn chữ trong BOX vẫn được giữ.
  - **Kiểm tra lúc chạy:**
    - không trang nào rỗng;
    - số trang in khớp 36/36;
    - chỗ chia section trên PDF 53 và 64 khớp đúng offset trong manifest (1406 và 997);
    - pipeline dừng nếu heading neo xuất hiện khác đúng một lần;
    - cả 20 câu evidence đều còn nguyên trong văn bản sau chuẩn hóa.
  - **Lỗi trong lúc chạy** (có `console.log` trong `results/`):
    1. `ingest_20261114T053443Z`: `ValueError` vì thiếu torchvision và Pillow (config của model khai báo một image processor). Đã cài thêm và ghi vào `requirements.txt`.
    2. `ingest_20261114T053809Z`: model được nạp ở bfloat16 dù cấu hình float32, nên mình dừng tay trước khi ghi DB. Code giờ ép dtype và kiểm tra dtype thực tế lúc chạy.

    Pypdf cũng cảnh báo thiếu fontTools; mình đọc kiểm tra phần chữ thân bài và vẫn đúng.
  - **Giới hạn:**
    - số chú thích dính vào từ ("deaths21");
    - heading xuống dòng bị tách ("Latin" / "America");
    - nội dung trong hình và bảng không có trong corpus, nên không hỏi được.
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:**
  - **Model:** `google/embeddinggemma-2` chạy local (provider: Hugging Face, chạy bằng Sentence Transformers).
    - Snapshot `f9972ac22e696a105c482202646979e33e4b5a1e`. Lúc chạy không khóa revision; đây là snapshot duy nhất trong cache.
    - Phiên bản thư viện: sentence-transformers 6.3.0, transformers 5.23.0, torch 2.15.0 (bản đầy đủ trong `starter/requirements.txt` và `requirements-lock.txt`).
    - **768 chiều**, kiểm tra lúc chạy bằng `get_embedding_dimension` và một vector thử.
    - Chạy float32 trên CPU, vector chuẩn hóa độ dài 1.
    - **Cách xử lý câu hỏi và văn bản** theo hướng dẫn của model: câu hỏi dùng prompt `SearchQuery` (`task: search result | query: `), văn bản dùng prompt `Document` (`title: none | text: `).
    - Không có vector giả: lỗi nào cũng dừng chương trình.
  - **Vector store:** PostgreSQL 16.16 + pgvector 0.8.7.
    - Khởi tạo: Docker image `pgvector/pgvector:0.8.7-pg16`, cổng `127.0.0.1:55433`; `init.sql` bật extension; code tạo bảng `day6_chunks` (`embedding vector(768)`) cùng index `(strategy, document_id, section)`. Dữ liệu lưu trong Docker volume nên còn nguyên sau khi tắt máy.
    - **Metric: khoảng cách cosine (`<=>`), score = 1 − khoảng cách; tìm kiếm exact** (không có ANN index). Hai kết quả cùng score thì xếp theo `chunk_id`.
  - **Lệnh chạy** (từ `starter/`): `python -m src.run inspect | ingest | retrieve --split dev | retrieve --split test --selected-strategy C --criteria "…"` (chi tiết trong README).
  - **Chi phí: 0 USD** (model và DB đều local).
  - Không cần seed: chunking là tất định, và embedding không có bước lấy mẫu ngẫu nhiên.
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**
  - **Bắt buộc:**
    - `document_id` (text, `wb-ppp-2024`);
    - `source` (text, tên file PDF);
    - `pdf_page` (integer).
  - **Trường truy vết thêm:**
    - `printed_page` (integer);
    - `char_start` / `char_end` (integer, vị trí trong segment trang);
    - `segment_index` / `chunk_index` (integer);
    - `chunk_id` ổn định, dạng `{strategy}:{doc}:p{page}s{segment}:c{idx}`.
  - **Trường lọc:** `section` (text, một trong `progress` / `pathways` / `priorities`).
    - Nguồn giá trị: heading chương của tài liệu, ghi trong manifest; không suy đoán.
    - Lý do chọn: đây là ba phạm vi có thật, phân biệt rõ và khá cân bằng (B có 50 / 47 / 33 chunk), và người dùng có thể nêu chúng trước khi truy xuất ("trong phần Progress…").
    - Bộ lọc là input giả định được cung cấp sẵn trong câu hỏi; không bao giờ lấy từ gold.

## Cấu hình và benchmark

- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**
  - **A:** cửa sổ cố định 500 ký tự, overlap 50, bắt đầu lại ở mỗi segment trang/section. Không lọc.
  - **B:** theo đoạn, tối đa 800 ký tự, không overlap. Heading luôn đi cùng đoạn sau nó; đoạn dài hơn 800 ký tự được chia theo câu; chunk cũng bắt đầu lại ở mỗi segment. Không lọc.
  - **C:** dùng chính chunk và vector của B (cùng index), thêm `WHERE section = %s` **chỉ** cho câu có `filter`. Với 16 câu không có filter, C chạy không lọc và kết quả giống hệt B.
  - **Khác biệt duy nhất B–C là bộ lọc section;** A–B chỉ khác cách chia chunk. Cùng corpus, model, store, metric, top-3 và bộ câu hỏi. Cấu hình nằm ở `starter/src/config.py` và [artifacts/experiment_log.csv](../../artifacts/experiment_log.csv).
- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - **Bộ câu hỏi:** [benchmark/questions.json](../../benchmark/questions.json) có 20 câu: 15 dev, 5 test. Gồm 9 câu trực tiếp, 4 diễn đạt lại, 3 có điều kiện và 4 có filter.
  - **Thời điểm chia:** chia trước khi chạy pipeline. Bộ câu hỏi commit lúc `4ed963f` (04:33 UTC); lần `inspect` đầu chạy lúc 05:10 UTC.
  - **Câu có filter:** q04 (dev, `progress`), q13 (dev, `priorities`), q18 (test, `pathways`), q19 (test, `priorities`).
  - **Cách chia:** cả hai tập lấy từ cùng một tài liệu (corpus chỉ có một), rải đều 3 section. Trang gold của test (PDF 46, 58, 61, 67, 73) không trùng trang gold nào của dev.
  - **Nguy cơ rò rỉ giữa dev và test:**
    - cùng tài liệu và cùng văn phong;
    - có trang kề nhau và chủ đề gần nhau, ví dụ q13 (dev, PDF 66) và q19 (test, PDF 67) cùng nói về các nước IDA.
  - **Kiểm chứng evidence:**
    - Mỗi `evidence_quote` được đối chiếu với chữ của trang gold (đọc trực tiếp PDF) trước khi chạy.
    - Lúc chạy, pipeline kiểm tra lại cho cả 20 câu và đều thấy evidence còn nguyên sau chuẩn hóa.
    - Bộ câu hỏi do AI soạn nháp (`review_status = assistant_checked`). Các câu có quote chưa đủ ý (q05, q08, q11, q19) được mở rộng quote hoặc viết lại câu hỏi; q15 và q20 được thay bằng câu mới, cũng trước khi chạy.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:** ghi vào `experiment_log.csv` trước mọi lần chạy truy xuất.
  1. Evidence Hit@3 trên dev cao nhất.
  2. Nếu hòa, chọn Hit@1 trên dev cao hơn.
  3. Nếu vẫn hòa, chọn cấu hình đơn giản hơn (ít chunk hơn, không lọc).

  Grounding chỉ chấm trên test và không dùng để chọn. Test chỉ chạy **một lần**, sau khi đã chọn C (`selection.earlier_test_runs = []` trong `run_metadata.json`).

## Kết quả

Hit = chunk thuộc đúng nguồn, đúng trang PDF gold và chứa **đủ** câu evidence (so khớp sau khi chuẩn hóa Unicode và khoảng trắng). Kết quả từng câu ở [Phụ lục A](#phụ-lục-a--kết-quả-từng-câu).

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 9/15 | 10/15 | 189 | Embed 77 s · truy xuất dev 3,9 s (chung A/B/C) | 0 USD |
| B | dev | 11/15 | 13/15 | 130 | Embed 3.289 s* · truy xuất dev 3,9 s (chung A/B/C) | 0 USD |
| C | dev | 11/15 | **14/15** | 130 (dùng chung index B) | Không embed thêm · truy xuất dev 3,9 s (chung A/B/C) | 0 USD |
| A | test | 3/5 | 4/5 | 189 | Truy xuất test 1,2 s (chung A/B/C) | 0 USD |
| B | test | 4/5 | 4/5 | 130 | Truy xuất test 1,2 s (chung A/B/C) | 0 USD |
| **C (đã chọn)** | test | **4/5** | **5/5** | 130 | Truy xuất test 1,2 s (chung A/B/C) | 0 USD |

Ghi chú cho bảng trên:
- **Độ dài và token:**

  | | Tổng ký tự | Token (kể cả prompt) | Ký tự ngắn nhất / trung vị / dài nhất |
  |---|---|---|---|
  | A | 86.708 | 19.663 (dài nhất 152) | 59 / 500 / 500 |
  | B | 79.081 | 17.351 (dài nhất 198) | 167 / 650 / 797 |

- **Thời gian:**
  - Lần ingest chính (`ingest_20261114T054628Z`) mất tổng 3.407 s: đọc và chuẩn hóa 4,5 s, chia chunk 0,003 s, nạp model 36 s, ghi DB 0,3 s cho A và 0,2 s cho B.
  - Thời gian truy xuất được đo chung cho cả A/B/C, không đo riêng từng cấu hình: 45 truy vấn dev hết 3,9 s, 15 truy vấn test hết 1,2 s, mỗi lần chưa tính 25–29 s nạp model.
- **Nạp lại không trùng** (`ingest_20261114T064359Z`): không chunk nào phải embed lại, 189 chunk A và 130 chunk B được dùng lại, không dòng nào bị xóa. Số dòng giữ nguyên A 189 / B 130, chunk_id và hash đều không trùng. Lần này mất 40 s.
- \* **Thời gian embed của B bất thường:** B ít token hơn A nhưng embed lâu gấp khoảng 43 lần. Nguyên nhân chưa xác định (có thể máy ngủ hoặc CPU bận việc khác). Vì vậy không dùng con số này để kết luận A nhanh hơn B.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1,1 (10): 0 câu điểm 0, 9 câu điểm 1, 1 câu điểm 2 | 15/15 | dev 1/2 · test 1/2 | 0 / 0 / 5 · 2,0 |
| B | 1,7 (10): 0 câu điểm 0, 3 câu điểm 1, 7 câu điểm 2 | 15/15 | dev 0/2 · test 0/2 | 1 / 0 / 4 · 1,6 |
| C | 1,7 (10; cùng chunk với B) | 15/15 | dev 2/2 · test 2/2 | 0 / 0 / 5 · 2,0 |

Đường dẫn trace, nhãn thủ công và cách chọn mẫu:
- **Trace top-3** (câu hỏi, chunk ID, text, score, metadata, cờ hit): [dev](../../results/retrieve_dev_20261114T064853Z/traces.jsonl) và [test](../../results/retrieve_test_20261114T065016Z/traces.jsonl); chỉ số nằm trong `metrics.md` / `metrics.json` cùng thư mục. Cấu hình và phiên bản của từng lần chạy nằm trong `run_metadata.json`.
- **Nhãn thủ công:** [coherence_labels.csv](../../results/labels/coherence_labels.csv), [metadata_labels.csv](../../results/labels/metadata_labels.csv), [grounding_labels.csv](../../results/labels/grounding_labels.csv); bảng tổng hợp ở [labels_summary.json](../../results/labels/labels_summary.json) (`starter/scripts/summarize_labels.py`).
- **Cách chọn mẫu:**
  - **Coherence:** 10 vị trí chọn tự động lúc ingest, **trước khi có điểm truy xuất**. Đó là điểm giữa của segment đầu tiên trên 10 trang nội dung đầu tiên đã sắp xếp (PDF 35, 36, 38, 39, 40, 41, 42, 43, 44, 45). Với mỗi vị trí, chấm chunk A và chunk B chứa nó; C dùng chunk của B.
  - **Metadata:** 5 câu test × top-3 × A/B/C = 45 bản ghi, đối chiếu bằng [verify_metadata.py](../../starter/scripts/verify_metadata.py). Script đọc chữ gốc của PDF độc lập với code chuẩn hóa của pipeline, rồi kiểm tra:
    - toàn bộ chữ của chunk có nằm trên đúng trang không;
    - `source`, `printed_page` và `section` có khớp manifest không; với PDF 53, section kiểm tra theo phần trang mà chunk nằm trong.

    Không phát hiện lỗi metadata nào. Các chunk lệch section so với bộ lọc (A q19 hạng 3; B q18 hạng 3 và q19 hạng 3) được ghi là lỗi tuân thủ bộ lọc, không phải lỗi metadata.
  - **Grounding:** 5 câu test × A/B/C.
- **Người chấm và nguy cơ thiên lệch:**
  - Claude (Claude Code) chấm nháp cả 90 nhãn kèm lý do; tác giả đọc lại và duyệt 90/90, không sửa nhãn nào. Cột `labeled_by` / `author_review` trong từng file ghi rõ điều này.
  - Nguy cơ thiên lệch: nhãn được chấm **sau** khi đã thấy Hit@k, và người duyệt cũng là tác giả pipeline. Đây không phải chấm độc lập.

## Phân tích và kết luận

- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:**
  - **A–B (chỉ khác cách chia chunk):**
    - B hơn A trên dev: Evidence Hit@3 13/15 so với 10/15, Hit@1 11 so với 9. Độ mạch lạc cũng cao hơn (1,7 so với 1,1).
    - B tốn ít tài nguyên hơn: 130 chunk so với 189, 17,4 nghìn token so với 19,7 nghìn, vì không có overlap.
    - Page Hit@3 của A là 15/15, tức A luôn tìm đúng trang. Cả 5 câu dev A trượt Evidence Hit@3 (q07, q08, q11, q14, q15) đều là câu evidence bị cửa sổ 500 ký tự cắt đôi. Lỗi của A nằm ở ranh giới chunk, không phải ở việc tìm kiếm.
    - Trong 10 chunk A được chấm mạch lạc, 9 chunk bị cắt giữa từ hoặc giữa câu.
    - A lại thắng B ở 2 câu dev:
      - q04: không có bộ lọc, top-3 của B lấy chunk thuộc section `priorities`;
      - q05: evidence bị tách trong B.
    - Lỗi riêng của B:
      - bắt đầu lại ở mỗi trang nên câu nối giữa hai trang bị cắt (coherence pos07, pos08);
      - đoạn dài bị chia theo câu nên evidence của q05 bị tách.
  - **B–C (chỉ khác bộ lọc):**
    - Hai cấu hình chỉ khác nhau ở 4 câu có filter. Tỷ lệ tuân thủ bộ lọc từ 0/2 lên 2/2 trên cả dev và test.
    - C lấy lại được q04 (dev) và q19 (test), nên Evidence Hit@3 hơn B đúng 1 câu ở mỗi tập. Grounding test cũng tăng từ 1,6 lên 2,0.
    - Hit@1 không đổi, vì bộ lọc chỉ loại chunk khác section chứ không xếp lại thứ tự trong cùng section: ở q04 và q19, chunk đúng của C đều đứng hạng 3.
    - C không tốn thêm tài nguyên (không embed thêm, chỉ thêm một điều kiện WHERE).
  - **Ví dụ sai 1 — dev q07, A** (nguồn `wb-ppp-2024`, PDF 49 / trang in 15, section progress):
    - Evidence "Nearly one in five people (17.9 percent) is at high risk from climate-related hazards globally, meaning … struggle to recover from." bị chia giữa `A:wb-ppp-2024:p049s0:c003` (ký tự 1350–1850) và `c004` (1800–2300). Overlap 50 ký tự không đủ để giữ trọn câu.
    - Top-2 là `c004`, mở đầu "is at high risk from climate-related hazards…", mất chủ thể "Nearly one in five people (17.9 percent)".
    - Kết quả: A trượt cả Hit@1 lẫn Evidence Hit@3, dù top-3 đều trên đúng trang 49. B giữ trọn đoạn này và đạt hạng 1.
  - **Ví dụ sai 2 — test q19, B** (nguồn `wb-ppp-2024`, PDF 67 / trang in 33, filter `section=priorities`):
    - Không có bộ lọc, top-3 của B là:
      1. `B:…p067s0:c004`, số của nhóm non-IDA (59% / 11%);
      2. `B:…p066s0:c001`, dự báo tỷ lệ người nghèo ở các nước IDA;
      3. `B:…p049s0:c003`, section **progress**, số liệu theo vùng.

      Chunk chứa "56 percent … 47 percent … 84 percent of those who are exposed" (`B:wb-ppp-2024:p067s0:c003`) không lọt top-3, nên grounding của B bằng 0.
    - C lọc theo `priorities` nên loại được chunk trang 49 và đưa `p067s0:c003` lên hạng 3; grounding của C bằng 2.
  - **Lỗi thêm — dev q05, B/C** (PDF 41 / trang in 7): câu evidence nằm vắt qua `B:wb-ppp-2024:p041s0:c002` (hết ở "(see box O.1).") và `c003` (bắt đầu "It is the average factor…"). Đây là đánh đổi đã chấp nhận khi sửa chunker B để không còn chunk chỉ chứa heading (xem `results/RUNS.md`).
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  - **Chọn C**, theo tiêu chí 1: Evidence Hit@3 trên dev 14/15, cao nhất và không hòa. Test cho kết quả cùng chiều (5/5, grounding 2,0), nhưng chỉ có 5 câu.
  - **Điều kiện áp dụng:** lợi thế của C chỉ phát huy khi người dùng thật sự cung cấp `section` đúng trước khi truy xuất. Không có filter, C chính là B.
  - **Đánh đổi:**
    - chunk B/C dài hơn A (trung vị 650 so với 500 ký tự), nên mỗi kết quả trả về nhiều chữ hơn;
    - bộ lọc sai sẽ loại mất bằng chứng đúng;
    - `section` quá thô (chỉ 3 giá trị), không giúp xếp hạng trong cùng section.
  - **Metadata hữu ích ở đâu:**
    - `pdf_page` và `printed_page` cho phép truy vết thẳng về trang nguồn: cả 45/45 bản ghi tìm thấy toàn bộ chữ trên đúng trang.
    - `section` là trường duy nhất tạo khác biệt giữa B và C (tuân thủ bộ lọc từ 0/2 lên 2/2).
  - **Hạn chế của metadata:**
    - section do người gán theo heading, và trên PDF 53/64 phải chia theo phần trang;
    - nếu tài liệu đổi bố cục, phải sửa manifest bằng tay;
    - pipeline dừng nếu không tìm thấy heading neo, hoặc tìm thấy nhiều hơn một.
  - **Xử lý khi tài liệu thay đổi:**
    - Mỗi chunk có `chunk_id` ổn định và một `content_hash`, tính từ model, revision, dtype, prompt văn bản, text và metadata vị trí.
    - Khi ingest: chỉ embed chunk có hash mới; ghi bằng `INSERT … ON CONFLICT (chunk_id) DO UPDATE`; xóa chunk ID không còn được tạo ra. Mọi thao tác nằm trong một transaction.
    - Nếu file PDF đổi, sha256 không khớp manifest nên pipeline dừng; phải cập nhật manifest có chủ đích trước khi chạy lại.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - **Dữ liệu:**
    - chỉ một tài liệu tiếng Anh và một model;
    - không có nội dung từ hình và bảng;
    - kết luận không áp dụng được cho corpus khác.
  - **Test nhỏ:**
    - 5 câu test, nên chênh lệch 1 câu đã bằng 20 điểm phần trăm;
    - chỉ 4 câu có filter (2 câu mỗi tập);
    - không đủ để khẳng định chiến lược nào tốt nhất nói chung.
  - **Nhãn:**
    - Nhãn do AI chấm nháp, tác giả duyệt, không có người chấm độc lập; bộ câu hỏi cũng do AI soạn nháp.
    - Định nghĩa hit khớp nguyên văn câu evidence nên rất chặt; chấm grounding tay thì rộng hơn. Ví dụ test q20 của A trượt hit tự động vì chunk mất 3 ký tự "Cur", nhưng grounding vẫn được 2 vì đủ số liệu và điều kiện.
  - **Lộ thông tin test trong lúc phát triển** (ghi theo RULES):
    - Các lần `inspect` ban đầu và lần `ingest` chính đã tính và in trạng thái chứa evidence theo chunk cho cả câu test (A tách evidence của q20, B giữ trọn). Giả thuyết của A trong `experiment_log.csv` ("6/20 questions split") cũng dùng con số tính cả câu test.
    - Các sửa đổi chunker B xuất phát từ q06 (dev) và lỗi chunk chỉ chứa heading, không nhắm vào câu test. Không tham số nào được chỉnh sau khi chạy `retrieve` trên test.
    - Dù vậy, tập test không hoàn toàn "mù". Sau audit, code đã sửa để chỉ tính trạng thái này cho dev (`inspect_20261114T072153Z`; chunk không đổi).
  - **Đo thời gian và chi phí:**
    - đo một lần trên CPU laptop;
    - thời gian embed của B bất thường;
    - thời gian truy xuất không đo riêng từng cấu hình;
    - chi phí 0 USD chưa tính điện năng hay phần cứng.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  - Cho B nối câu qua ranh giới trang trong cùng section, sửa lỗi pos07/pos08.
  - Cho A cắt theo ranh giới câu, hoặc tăng overlap, để không cắt đôi evidence ngắn.
  - Thử hybrid BM25 kết hợp dense (chọn tham số trên dev): các câu nhiều con số như q19 có thể hưởng lợi.
  - Viết thêm câu có filter và một tập test mới chưa từng chạy chẩn đoán.
  - Khóa `EMBEDDING_REVISION` ngay từ đầu.
  - Đo thời gian lặp lại nhiều lần và đo riêng từng cấu hình.
  - Nhờ một người khác chấm nhãn độc lập.

## Phụ lục A — Kết quả từng câu

✓/✗ = Hit@1 / Evidence Hit@3. Hạng của hit đầu tiên lấy trong trace.

| ID | Split | Loại | PDF (trang in) | Section | Filter | A | B | C |
|---|---|---|---|---|---|---|---|---|
| q01 | dev | direct | 35 (1) | progress | — | ✗/✓ (hạng 3) | ✗/✓ (hạng 3) | ✗/✓ (hạng 3) |
| q02 | dev | condition | 36 (2) | progress | — | ✓/✓ | ✓/✓ | ✓/✓ |
| q03 | dev | paraphrase | 40 (6) | progress | — | ✓/✓ | ✓/✓ | ✓/✓ |
| q04 | dev | metadata_filter | 41 (7) | progress | progress | ✓/✓ | ✗/✗ | ✗/✓ (hạng 3) |
| q05 | dev | direct | 41 (7) | progress | — | ✓/✓ | ✗/✗ (evidence bị tách) | ✗/✗ (evidence bị tách) |
| q06 | dev | direct | 44 (10) | progress | — | ✓/✓ | ✓/✓ | ✓/✓ |
| q07 | dev | paraphrase | 49 (15) | progress | — | ✗/✗ (evidence bị tách) | ✓/✓ | ✓/✓ |
| q08 | dev | direct | 55 (21) | pathways | — | ✗/✗ (evidence bị tách) | ✓/✓ | ✓/✓ |
| q09 | dev | direct | 57 (23) | pathways | — | ✓/✓ | ✓/✓ | ✓/✓ |
| q10 | dev | condition | 59 (25) | pathways | — | ✓/✓ | ✓/✓ | ✓/✓ |
| q11 | dev | paraphrase | 62 (28) | pathways | — | ✗/✗ (evidence bị tách) | ✓/✓ | ✓/✓ |
| q12 | dev | direct | 64 (30) | priorities | — | ✓/✓ | ✓/✓ | ✓/✓ |
| q13 | dev | metadata_filter | 66 (32) | priorities | priorities | ✓/✓ | ✓/✓ | ✓/✓ |
| q14 | dev | direct | 69 (35) | priorities | — | ✗/✗ (evidence bị tách) | ✓/✓ | ✓/✓ |
| q15 | dev | direct | 71 (37) | priorities | — | ✗/✗ (evidence bị tách) | ✗/✓ (hạng 2) | ✗/✓ (hạng 2) |
| q16 | test | paraphrase | 46 (12) | progress | — | ✗/✓ (hạng 3) | ✓/✓ | ✓/✓ |
| q17 | test | direct | 58 (24) | pathways | — | ✓/✓ | ✓/✓ | ✓/✓ |
| q18 | test | metadata_filter | 61 (27) | pathways | pathways | ✓/✓ | ✓/✓ | ✓/✓ |
| q19 | test | metadata_filter | 67 (33) | priorities | priorities | ✓/✓ | ✗/✗ | ✗/✓ (hạng 3) |
| q20 | test | condition | 73 (39) | priorities | — | ✗/✗ (evidence bị tách) | ✓/✓ | ✓/✓ |

**Lỗi evidence bị tách qua nhiều chunk** (GUIDE §4.1): A tách evidence ở 6 câu (dev q07, q08, q11, q14, q15; test q20); B tách ở 1 câu (dev q05). Danh sách chunk chứa evidence của từng câu dev nằm trong `results/inspect_20261114T072153Z/evidence_diagnostics.jsonl`.

**Tóm tắt lý do chấm tay** (lý do đầy đủ cho từng dòng nằm trong các file CSV ở `results/labels/`):
- **Coherence:**
  - A: 9/10 chunk bị cắt giữa từ hoặc giữa câu ở đầu hay cuối; điển hình là pos06, mở đầu "990 and 2022" do năm 1990 bị cắt mất chữ số đầu. Chunk A duy nhất được 2 là pos07, chỉ bị cắt ở phần trích dẫn.
  - B bị 1 ở ba vị trí:
    - pos05: mở đầu "This generation of students" nhưng thiếu phần nói trước đó là thế hệ nào;
    - pos07 và pos08: câu bị cắt ở chỗ chuyển trang.
- **Grounding:** chỉ có B q19 được 0 (không chunk nào có số 56% / 47% / 84%). 14 dòng còn lại được 2, vì top-3 chứa đủ số liệu và điều kiện, truy được về đúng trang.

## Công cụ AI và cách kiểm tra

Dùng Claude Code (Claude Opus 5.5) để soạn manifest, bộ câu hỏi, code pipeline, nhãn nháp và bản nháp báo cáo này. Cách kiểm tra:
- evidence được so với chữ PDF sau chuẩn hóa, bằng script, cho cả 20 câu;
- metadata được kiểm tra bằng script độc lập với pipeline;
- nạp lại được kiểm tra bằng số dòng và hash trong DB;
- nhãn được tác giả đọc lại và duyệt;
- mọi lỗi lúc chạy được giữ lại trong `results/` (`RUNS.md`, `console.log`).

Tác giả chịu trách nhiệm về nội dung và phải giải thích được từng phần (RULES).
