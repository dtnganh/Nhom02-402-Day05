# VinFast Smart Assistant (VSA) - Evaluation & Risk Framework

Thư mục này chứa toàn bộ hệ thống đánh giá chất lượng tự động (Auto-evaluator) và Red-Teaming dành cho AI Chatbot.

## Cấu trúc thư mục 

```text
evaluation/
├── data/
│   └── golden_dataset.json       # Tập dữ liệu gốc chứa 100 câu hỏi và Ground Truth (Barem chấm điểm)
├── outputs/
│   ├── eval_results.json         # Bài làm thô do AI sinh ra (đầu ra của eval_framework)
│   ├── judge_results.json        # Bài chấm điểm chi tiết (đầu ra của judge)
│   └── final_eval_report.log     # Bảng điểm tổng hợp (Factuality, Fallback, Latency P90)
├── eval_framework.py             # Script bắt AI lên bảng làm bài (Mô phỏng Offline)
├── judge.py                      # Máy chấm thi (LLM-as-a-judge)
├── test_failure_modes.py         # Kịch bản tấn công giả lập (Red-Teaming)
└── README.md                     # Tài liệu hướng dẫn bạn đang đọc
```

## Hướng dẫn chạy Test

Quá trình kiểm thử được chia làm các bước riêng biệt để đảm bảo tiết kiệm tài nguyên LLM. Hãy chạy lần lượt:

### Bước 1: Cho AI làm bài thi
Chạy script dưới đây để nạp 100 câu hỏi từ `data/golden_dataset.json` vào Graph và ép file AI trả lời.
```bash
python eval_framework.py
```
*(Kết quả sẽ được ghi vào thư mục `outputs/`)*

### Bước 2: Gọi Máy Chấm Thi
Script này sẽ mượn sức mạnh của mô hình mạnh nhất hiện có (khác với LLM dùng để làm bài thi) để đọc hiểu từng câu trả lời thực tế và đối chiếu với barem để phát hiện ảo giác (Hallucination).
```bash
python judge.py
```
*(Đọc báo cáo tại `outputs/final_eval_report.log`)*

### Bước 3: Kiểm thử Kháng Độc (Test Anti-Failure Modes)
Nếu Team Dev vừa commit một bản vá lỗi Prompt mới và bạn muốn kiểm tra xem 3 tử huyệt của dự án đã được khắc phục chưa, hãy chạy lệnh này:
```bash
python test_failure_modes.py
```
Script sẽ tiêm (inject) các câu hỏi bẫy khó nhằn nhất vào hệ thống và đưa ra quyết định Pass/Fail trong vòng vài giây.
